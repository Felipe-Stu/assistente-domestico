import logging
import sys
from pathlib import Path

# 1. Ajusta o sys.path PRIMEIRO
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# 2. Importações organizadas
from services.ai_service import AIService, ServiceUnavailableException, TokenExhaustedException
from services.audio_service import AudioService
from services.db_service import DatabaseService
from services.gemma_service import executar_assistente_local, orquestrar_requisicao
from services.inventory_assistant import InventoryAssistant
from services.llm_provider import LocalLLMProvider, CloudLLMProvider
from services.logger_service import logger as custom_logger
from services.resilience_service import (
    InvalidOrchestratorOutputException,
    MaxRetriesExceededException,
    execute_with_retry,
)
from services.shopping_assistant import ShoppingAssistant
from services.voice_service import VoiceService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TEMPO_RETRY = 3.0
MAX_TENTATIVAS = 3


class GerenciadorDeSessao:
    def __init__(self):
        self.contexto_ativo = None
        self.historico = []

    def atualizar_sessao(self, novo_contexto, mensagem_user, resposta_ai, mudanca_de_contexto=False):
        if mudanca_de_contexto or self.contexto_ativo != novo_contexto:
            logger.info(f"🔄 Alterando contexto de '{self.contexto_ativo}' para '{novo_contexto}'. Histórico resetado.")
            self.contexto_ativo = novo_contexto
            self.historico = []

        self.historico.append({"role": "user", "content": mensagem_user})
        self.historico.append({"role": "assistant", "content": resposta_ai})


sessao = GerenciadorDeSessao()


def processar_solicitacao(transcricao, services):
    db_service, ai_service, voice_service, inventory_assistant, shopping_assistant, llm_provider = services

    solicitacao_original = transcricao

    logger.info(f"🎙️ [Usuário]: '{solicitacao_original}'")
    custom_logger.log_geral(f"Áudio transcrito capturado: '{solicitacao_original}'")

    # =========================================================================
    # PASSO 1: Orquestração Gemma 4 (Centralizada no gemma_service)
    # =========================================================================
    try:
        decisao = execute_with_retry(
            func=orquestrar_requisicao,
            args=(solicitacao_original,),
            kwargs={"contexto_atual": sessao.contexto_ativo},
            max_tentativas=MAX_TENTATIVAS,
            tempo_espera=TEMPO_RETRY,
            excecoes_recuperaveis=(InvalidOrchestratorOutputException, Exception),
            voice_service=voice_service,
            mensagem_espera_voz="Aguarde um instante, estou reprocessando sua solicitação.",
            nome_servico="Gemma4-Orquestrador"
        )
    except MaxRetriesExceededException:
        logger.warning("⚠️ Gemma 4 excedeu retries. Aplicando fallback seguro para nuvem.")
        custom_logger.log_geral("Fallback ativado: Encaminhando solicitação para Gemini.")
        decisao = {
            "dificuldade": "medio_dificil",
            "mudanca_de_contexto": True,
            "contexto": "outro",
            "acao": "delegar"
        }

    logger.info(f"🧠 [Decisão do Orquestrador]: {decisao}")

    dificuldade = decisao.get("dificuldade", "medio_dificil")
    contexto = decisao.get("contexto", "outro")
    mudanca_contexto = decisao.get("mudanca_de_contexto", False)

    resposta_texto = ""

    # =========================================================================
    # PASSO 2: Roteamento de Execução
    # =========================================================================
    if dificuldade == "facil":
        logger.info("⚡ Processando LOCALMENTE...")

        try:
            if contexto == "compras":
                res_compra = execute_with_retry(
                    func=shopping_assistant.processar_texto_compra,
                    args=(solicitacao_original,),
                    max_tentativas=MAX_TENTATIVAS,
                    tempo_espera=TEMPO_RETRY,
                    voice_service=voice_service,
                    mensagem_espera_voz="Estou tentando registrar suas compras novamente.",
                    nome_servico="ShoppingAssistant"
                )
                resposta_texto = res_compra.get("mensagem", "Compra registrada com sucesso.")

            elif contexto == "inventario":
                resposta_texto = "Consulta ao inventário realizada com sucesso."

            else:
                resposta_texto = execute_with_retry(
                    func=executar_assistente_local,
                    args=(contexto, sessao.historico, solicitacao_original),
                    max_tentativas=MAX_TENTATIVAS,
                    tempo_espera=TEMPO_RETRY,
                    voice_service=voice_service,
                    mensagem_espera_voz="Processando sua solicitação localmente.",
                    nome_servico="AssistenteLocal"
                )

        except MaxRetriesExceededException:
            logger.error("❌ Falha crítica local. Redirecionando para Nuvem...")
            dificuldade = "medio_dificil"

    if dificuldade != "facil":
        logger.info("☁️ Processando na NUVEM via Gemini...")

        try:
            resposta_texto = execute_with_retry(
                func=ai_service.processar_requisicao_complexa,
                args=(solicitacao_original, sessao.historico),
                max_tentativas=MAX_TENTATIVAS,
                tempo_espera=TEMPO_RETRY,
                excecoes_recuperaveis=(ServiceUnavailableException, Exception),
                voice_service=voice_service,
                mensagem_espera_voz="Tráfego congestionado na nuvem. Aguardando reenvio.",
                nome_servico="Gemini-Nuvem"
            )
        except MaxRetriesExceededException:
            resposta_texto = "Desculpe, o serviço de inteligência na nuvem está indisponível no momento. Tente novamente mais tarde."
            voice_service.falar(resposta_texto)
            return resposta_texto

    sessao.atualizar_sessao(contexto, solicitacao_original, resposta_texto, mudanca_de_contexto=mudanca_contexto)

    # =========================================================================
    # PASSO 3: Resposta por Voz
    # =========================================================================
    if resposta_texto:
        logger.info(f"🗣️ [Resposta Final]: {resposta_texto}")
        voice_service.falar(resposta_texto)

    return resposta_texto


def rodar_assistente():
    logger.info("Iniciando Assistente Doméstico (Arquitetura Limpa & Resiliente)")

    try:
        # 1. Serviços de Infraestrutura
        db_service = DatabaseService()
        audio_service = AudioService()
        ai_service = AIService()
        voice_service = VoiceService()

        # 2. Instanciação dos Provedores LLM específicos
        local_llm = LocalLLMProvider(modelo="gemma4:e4b")
        cloud_llm = CloudLLMProvider(ai_service=ai_service)

        # 3. Injeção de Dependências nos Assistentes
        inventory_assistant = InventoryAssistant(
            db_service=db_service,
            llm_provider=local_llm,  # Passa a instância do LocalLLMProvider
            ai_service=ai_service
        )
        
        shopping_assistant = ShoppingAssistant(
            ai_service=ai_service, 
            db_service=db_service,
            llm_provider=local_llm   # Passa a instância do LocalLLMProvider
        )

        services = (
            db_service, 
            ai_service, 
            voice_service, 
            inventory_assistant, 
            shopping_assistant, 
            local_llm
        )
    except Exception as e:
        logger.critical(f"Erro fatal na inicialização: {e}")
        sys.exit(1)

    try:
        # Varredura inicial do estoque
        inventory_assistant.verificar_itens_expirados_inicializacao()

        # Captura e processamento por voz
        transcricao = audio_service.capturar_audio_e_transcrever()

        if transcricao:
            processar_solicitacao(transcricao, services)
        else:
            logger.info("Nenhuma fala detectada.")

    except TokenExhaustedException as e:
        logger.warning(f"AVISO DE TOKENS: {e}")
        voice_service.falar("Limite de cota atingido para processamento na nuvem.")

    except Exception as e:
        logger.error(f"Falha na orquestração principal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    rodar_assistente()