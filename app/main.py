import logging
import sys
import io
import json
import queue
import threading
import time
from pathlib import Path

# Configura codificação de fluxo para UTF-8 no Windows antes de qualquer saída
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 1. Ajusta o sys.path PRIMEIRO
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# 2. Importações organizadas — apenas serviços essenciais no topo
from services.ai_service import AIService, ServiceUnavailableException, TokenExhaustedException
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

# Serviços Vetoriais e RAG (Memória Semântica e Contextual)
from services.vector.vector_store_service import VectorStoreService
from services.vector.memory_service import MemoryService
from services.vector.context_retrieval_service import ContextRetrievalService

# Serviços de voz/áudio — importados mas NÃO instanciados no startup
from services.voice_service import VoiceService
from services.audio_service import AudioService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TEMPO_RETRY = 3.0
MAX_TENTATIVAS = 3


# =============================================================================
# EMISSÃO IPC PADRONIZADA
# =============================================================================

def emitir_electron(tipo, payload=None):
    """Auxiliar para padronizar o envio de mensagens JSON ao Electron."""
    msg = {"type": tipo}
    if payload is not None:
        msg["payload"] = payload
    print(json.dumps(msg, ensure_ascii=False), flush=True)


# =============================================================================
# GERENCIADOR DE SESSÃO
# =============================================================================

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


# =============================================================================
# RUNTIME PRINCIPAL — TEXT-FIRST COM ATIVAÇÃO DINÂMICA DE VOZ
# =============================================================================

class AssistenteRuntime:
    """
    Runtime unificado do Assistente Doméstico.
    
    Modelo Text-First:
    - Fase 1: Serviços essenciais (DB, AI, LLM) → chat disponível imediatamente.
    - Fase 2: Serviços de voz (VoiceService, AudioService) → lazy, sob demanda.
    """

    def __init__(self):
        self.estado = "STARTING"
        self.is_muted = False
        self.voice_mode_active = False
        self.deve_encerrar = False
        self.fila = queue.Queue()
        self.sessao = GerenciadorDeSessao()

        # Serviços essenciais (inicializados na Fase 1)
        self.db_service = None
        self.ai_service = None
        self.local_llm = None
        self.cloud_llm = None
        self.inventory_assistant = None
        self.shopping_assistant = None

        # Serviços de voz (inicializados sob demanda na Fase 2)
        self.voice_service = None
        self.audio_service = None

        # Emite estado inicial
        self._set_estado("STARTING")

    # -------------------------------------------------------------------------
    # Estado & Emissão
    # -------------------------------------------------------------------------

    def _set_estado(self, novo_estado: str):
        self.estado = novo_estado
        emitir_electron("state_changed", {"state": self.estado})
        logger.info(f"Estado do sistema alterado para: {self.estado}")

    # -------------------------------------------------------------------------
    # FASE 1: Inicialização Essencial (Text-First)
    # -------------------------------------------------------------------------

    def _inicializar_servicos_essenciais(self):
        """
        Inicializa apenas serviços necessários para o modo texto.
        Falha aqui = erro fatal (sem DB/AI não há funcionalidade).
        """
        self._set_estado("INITIALIZING")
        emitir_electron("debug_log", {"message": "Inicializando serviços essenciais (Modo Texto)..."})

        try:
            # 1. Serviços de Infraestrutura
            self.db_service = DatabaseService()
            emitir_electron("debug_log", {"message": "✓ Banco de dados relacional (SQLite) conectado."})

            self.vector_store = VectorStoreService()
            self.memory_service = MemoryService(vector_store=self.vector_store)
            self.context_retrieval = ContextRetrievalService(memory_service=self.memory_service)
            emitir_electron("debug_log", {"message": "✓ Banco vetorial (ChromaDB) e Memória Semântica prontos."})

            self.ai_service = AIService()
            emitir_electron("debug_log", {"message": "✓ Serviço de IA inicializado."})

            # 2. Provedores LLM
            self.local_llm = LocalLLMProvider(modelo="gemma4:e4b")
            self.cloud_llm = CloudLLMProvider(ai_service=self.ai_service)
            emitir_electron("debug_log", {"message": "✓ Provedores LLM configurados."})

            # 3. Serviços de voz em modo lazy (construtor leve, sem init de hardware).
            #    Criados antes dos assistentes para serem compartilhados com eles.
            self.voice_service = VoiceService()
            self.audio_service = AudioService()

            # 4. Assistentes de Domínio
            self.inventory_assistant = InventoryAssistant(
                db_service=self.db_service,
                llm_provider=self.local_llm,
                ai_service=self.ai_service,
                voice_service=self.voice_service,
                audio_service=self.audio_service,
                modo_voz_ativo=lambda: self.voice_mode_active
            )

            self.shopping_assistant = ShoppingAssistant(
                ai_service=self.ai_service,
                db_service=self.db_service,
                llm_provider=self.local_llm,
                vector_store=self.vector_store
            )
            emitir_electron("debug_log", {"message": "✓ Assistentes de domínio prontos."})

        except Exception as e:
            logger.critical(f"Erro fatal na inicialização dos serviços essenciais: {e}")
            emitir_electron("error", {"message": f"Erro fatal na inicialização: {e}"})
            self._set_estado("ERROR")
            sys.exit(1)

    # -------------------------------------------------------------------------
    # FASE 2: Ativação Dinâmica de Voz (Lazy, sob demanda)
    # -------------------------------------------------------------------------

    def _ativar_modo_voz(self):
        """
        Tenta inicializar VoiceService (TTS) e AudioService (Microfone).
        Retorna dict com status detalhado para o frontend.
        Nunca lança exceção.
        """
        emitir_electron("debug_log", {"message": "Ativando modo voz... Verificando hardware..."})

        tts_ready = False
        mic_ready = False
        erro = None

        # TTS (Síntese de Voz)
        if self.voice_service:
            tts_ready = self.voice_service.inicializar()
            if not tts_ready:
                erro = self.voice_service.obter_erro()
                emitir_electron("debug_log", {"message": f"⚠️ TTS indisponível: {erro}"})
            else:
                emitir_electron("debug_log", {"message": "✓ TTS (síntese de voz) ativado."})

        # Microfone (Captura de Áudio)
        if self.audio_service:
            mic_ready = self.audio_service.inicializar()
            if not mic_ready:
                mic_erro = self.audio_service.obter_erro()
                if not erro:
                    erro = mic_erro
                else:
                    erro += f" | {mic_erro}"
                emitir_electron("debug_log", {"message": f"⚠️ Microfone indisponível: {mic_erro}"})
            else:
                emitir_electron("debug_log", {"message": "✓ Microfone detectado e pronto."})

        available = tts_ready or mic_ready
        self.voice_mode_active = available

        status = {
            "available": available,
            "tts_ready": tts_ready,
            "mic_ready": mic_ready,
            "error": erro
        }

        if available:
            emitir_electron("debug_log", {"message": "Modo voz ativado com sucesso."})
        else:
            emitir_electron("debug_log", {"message": "Modo voz indisponível — nenhum hardware detectado."})

        return status

    def _desativar_modo_voz(self):
        """Desativa o modo voz e aborta capturas em andamento."""
        self.voice_mode_active = False

        if self.audio_service:
            self.audio_service.abortar_captura()

        emitir_electron("debug_log", {"message": "Modo voz desativado."})

        return {
            "available": False,
            "tts_ready": self.voice_service.esta_disponivel() if self.voice_service else False,
            "mic_ready": self.audio_service.esta_disponivel() if self.audio_service else False,
            "error": None
        }

    # -------------------------------------------------------------------------
    # Falar (resposta por voz) — condicional
    # -------------------------------------------------------------------------

    def _falar_se_permitido(self, texto):
        """Executa TTS apenas se: modo voz ativo + não mutado + voice_service disponível."""
        if self.is_muted:
            return
        if not self.voice_mode_active:
            return
        if self.voice_service and self.voice_service.esta_disponivel():
            try:
                self.voice_service.falar(texto)
            except Exception as e:
                logger.error(f"Erro ao reproduzir áudio: {e}")

    # -------------------------------------------------------------------------
    # Processamento de Solicitação (Orquestração)
    # -------------------------------------------------------------------------

    def _processar_solicitacao(self, transcricao: str):
        """Pipeline completo de processamento: Orquestração → Execução → Resposta."""
        solicitacao_original = transcricao

        logger.info(f"👤 [Usuário]: '{solicitacao_original}'")
        custom_logger.log_geral(f"Entrada recebida: '{solicitacao_original}'")

        self._set_estado("PROCESSING")

        # =====================================================================
        # PASSO 1: Orquestração Gemma 4
        # =====================================================================
        try:
            decisao = execute_with_retry(
                func=orquestrar_requisicao,
                args=(solicitacao_original,),
                kwargs={"contexto_atual": self.sessao.contexto_ativo},
                max_tentativas=MAX_TENTATIVAS,
                tempo_espera=TEMPO_RETRY,
                excecoes_recuperaveis=(InvalidOrchestratorOutputException, Exception),
                voice_service=self.voice_service if self.voice_mode_active else None,
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

        # =====================================================================
        # INTERCEPTAÇÃO: Resposta direta
        # =====================================================================
        if "resposta_direta" in decisao:
            resposta_texto = decisao["resposta_direta"]
            self.sessao.atualizar_sessao(contexto, solicitacao_original, resposta_texto, mudanca_de_contexto=mudanca_contexto)

            logger.info(f"🗣️ [Resposta Final]: {resposta_texto}")
            self._falar_se_permitido(resposta_texto)

            emitir_electron("assistant_message", {"text": resposta_texto})
            self._set_estado("WAITING_INPUT")
            return resposta_texto

        resposta_texto = ""

        # =====================================================================
        # PASSO 2: Roteamento de Execução
        # =====================================================================
        if dificuldade == "facil":
            logger.info("⚡ Processando LOCALMENTE...")

            try:
                if contexto == "compras":
                    res_compra = execute_with_retry(
                        func=self.shopping_assistant.processar_texto_compra,
                        args=(solicitacao_original,),
                        max_tentativas=MAX_TENTATIVAS,
                        tempo_espera=TEMPO_RETRY,
                        voice_service=self.voice_service if self.voice_mode_active else None,
                        mensagem_espera_voz="Estou tentando registrar suas compras novamente.",
                        nome_servico="ShoppingAssistant"
                    )
                    resposta_texto = res_compra.get("mensagem", "Compra registrada com sucesso.")

                elif contexto == "inventario":
                    resposta_texto = "Consulta ao inventário realizada com sucesso."

                else:
                    resposta_texto = execute_with_retry(
                        func=executar_assistente_local,
                        args=(contexto, self.sessao.historico, solicitacao_original),
                        max_tentativas=MAX_TENTATIVAS,
                        tempo_espera=TEMPO_RETRY,
                        voice_service=self.voice_service if self.voice_mode_active else None,
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
                    func=self.ai_service.processar_requisicao_complexa,
                    args=(solicitacao_original, self.sessao.historico),
                    max_tentativas=MAX_TENTATIVAS,
                    tempo_espera=TEMPO_RETRY,
                    excecoes_recuperaveis=(ServiceUnavailableException, Exception),
                    voice_service=self.voice_service if self.voice_mode_active else None,
                    mensagem_espera_voz="Tráfego congestionado na nuvem. Aguardando reenvio.",
                    nome_servico="Gemini-Nuvem"
                )
            except MaxRetriesExceededException:
                resposta_texto = "Desculpe, o serviço de inteligência na nuvem está indisponível no momento. Tente novamente mais tarde."
                self._falar_se_permitido(resposta_texto)
                emitir_electron("assistant_message", {"text": resposta_texto})
                self._set_estado("WAITING_INPUT")
                return resposta_texto

        self.sessao.atualizar_sessao(contexto, solicitacao_original, resposta_texto, mudanca_de_contexto=mudanca_contexto)

        # =====================================================================
        # PASSO 3: Resposta
        # =====================================================================
        if resposta_texto:
            logger.info(f"🗣️ [Resposta Final]: {resposta_texto}")
            self._falar_se_permitido(resposta_texto)
            emitir_electron("assistant_message", {"text": resposta_texto})

        self._set_estado("WAITING_INPUT")
        return resposta_texto

    # -------------------------------------------------------------------------
    # Threads de Leitura
    # -------------------------------------------------------------------------

    def _leitor_stdin(self):
        """Thread daemon para ler comandos do Electron via stdin."""
        while not self.deve_encerrar:
            try:
                linha = sys.stdin.readline()
                if not linha:
                    logger.info("Stdin fechado (EOF). Encerrando processo Python.")
                    self.deve_encerrar = True
                    self.fila.put({"type": "shutdown"})
                    break

                conteudo = linha.strip()
                if not conteudo:
                    continue

                try:
                    cmd = json.loads(conteudo)
                    self.fila.put(cmd)
                except json.JSONDecodeError:
                    # Se não for JSON, trata como texto puro (entrada manual no terminal)
                    self.fila.put({"type": "send_text", "payload": {"text": conteudo}})
            except Exception as e:
                logger.error(f"Erro ao processar stdin: {e}")

    def _loop_microfone(self):
        """Thread daemon para captação contínua do microfone físico."""
        while not self.deve_encerrar:
            if (self.voice_mode_active 
                and self.audio_service 
                and self.audio_service.esta_disponivel() 
                and self.estado == "WAITING_INPUT"):
                
                emitir_electron("voice_mode_status", {
                    "available": True,
                    "tts_ready": self.voice_service.esta_disponivel() if self.voice_service else False,
                    "mic_ready": True,
                    "listening": True,
                    "error": None
                })
                
                try:
                    transcricao = self.audio_service.capturar_audio_e_transcrever(ativar_trava_inicial=True)
                    if transcricao and transcricao.strip():
                        if self.voice_mode_active and self.estado == "WAITING_INPUT":
                            self.fila.put({"type": "voice_input", "payload": {"text": transcricao}})
                except Exception as e:
                    logger.error(f"Erro no loop do microfone: {e}")
                    # Se o mic foi desconectado em runtime, atualiza estado
                    if self.audio_service and not self.audio_service.esta_disponivel():
                        self.voice_mode_active = False
                        emitir_electron("voice_mode_status", {
                            "available": False,
                            "tts_ready": self.voice_service.esta_disponivel() if self.voice_service else False,
                            "mic_ready": False,
                            "listening": False,
                            "error": "Microfone desconectado durante uso."
                        })
                        emitir_electron("debug_log", {"message": "⚠️ Microfone desconectado. Voltando ao modo texto."})
                    time.sleep(1)
                finally:
                    emitir_electron("voice_mode_status", {
                        "available": self.voice_mode_active,
                        "tts_ready": self.voice_service.esta_disponivel() if self.voice_service else False,
                        "mic_ready": self.audio_service.esta_disponivel() if self.audio_service else False,
                        "listening": False,
                        "error": None
                    })
            else:
                time.sleep(0.3)

    # -------------------------------------------------------------------------
    # Loop Principal
    # -------------------------------------------------------------------------

    def rodar(self):
        """Entrypoint principal do runtime."""
        logger.info("Iniciando Assistente Doméstico (Modelo Text-First)")

        # =====================================================================
        # FASE 1: Serviços Essenciais (Chat disponível imediatamente depois)
        # =====================================================================
        self._inicializar_servicos_essenciais()

        # Inicia thread de leitura do stdin
        t_stdin = threading.Thread(target=self._leitor_stdin, daemon=True)
        t_stdin.start()

        # Inicia thread do microfone (ficará em espera até voice_mode_active=True)
        t_mic = threading.Thread(target=self._loop_microfone, daemon=True)
        t_mic.start()

        # Varredura inicial do estoque (em background para não bloquear)
        def _varredura_background():
            try:
                emitir_electron("debug_log", {"message": "Executando varredura preditiva de estoque inicial..."})
                self.inventory_assistant.verificar_itens_expirados_inicializacao()
                emitir_electron("debug_log", {"message": "✓ Varredura inicial de estoque concluída."})
            except Exception as e:
                logger.error(f"Erro na varredura inicial de estoque: {e}")
                emitir_electron("debug_log", {"message": f"⚠️ Erro na varredura de estoque: {e}"})

        t_varredura = threading.Thread(target=_varredura_background, daemon=True)
        t_varredura.start()

        # =====================================================================
        # SISTEMA PRONTO PARA TEXTO — Chat desbloqueado!
        # =====================================================================
        self._set_estado("READY")
        emitir_electron("system_ready")
        self._set_estado("WAITING_INPUT")

        logger.info("🟢 Assistente pronto no MODO TEXTO. Chat desbloqueado para o usuário.")
        emitir_electron("debug_log", {"message": "Sistema pronto! Modo texto ativo. Digite suas mensagens."})

        # =====================================================================
        # EVENT LOOP PRINCIPAL
        # =====================================================================
        while not self.deve_encerrar:
            try:
                cmd = self.fila.get(timeout=1.0)
            except queue.Empty:
                continue

            tipo = cmd.get("type")
            payload = cmd.get("payload", {})

            logger.info(f"Comando recebido: {cmd}")

            # -----------------------------------------------------------------
            # SHUTDOWN
            # -----------------------------------------------------------------
            if tipo == "shutdown":
                logger.info("Comando de shutdown recebido do Electron. Encerrando...")
                self.deve_encerrar = True
                break

            # -----------------------------------------------------------------
            # TEXTO DO CHAT
            # -----------------------------------------------------------------
            elif tipo in ["send_text", "user_message", "text"]:
                text = payload.get("text", "").strip()
                if not text:
                    continue

                # Comandos manuais de saída
                if text.lower() in ["sair", "exit", "quit"]:
                    logger.info("Encerrando o Assistente Doméstico...")
                    self.deve_encerrar = True
                    break

                # Aborta captura de áudio se houver uma em andamento
                if self.audio_service:
                    self.audio_service.abortar_captura()

                # Echo para a UI
                emitir_electron("user_message", {"text": text})

                try:
                    self._processar_solicitacao(text)
                except TokenExhaustedException as e:
                    logger.warning(f"AVISO DE TOKENS: {e}")
                    self._falar_se_permitido("Limite de cota atingido para processamento na nuvem.")
                    emitir_electron("error", {"message": f"Limite de cota atingido: {e}"})
                except Exception as e:
                    logger.error(f"Falha ao processar solicitação: {e}")
                    emitir_electron("error", {"message": f"Falha ao processar solicitação: {e}"})
                finally:
                    self._set_estado("WAITING_INPUT")

            # -----------------------------------------------------------------
            # INPUT DE VOZ (vindo da thread do microfone)
            # -----------------------------------------------------------------
            elif tipo == "voice_input":
                text = payload.get("text", "").strip()
                if not text:
                    continue

                # Echo para a UI (transcrição de voz)
                emitir_electron("user_message", {"text": text})

                if self.audio_service:
                    self.audio_service.abortar_captura()

                try:
                    self._processar_solicitacao(text)
                except TokenExhaustedException as e:
                    logger.warning(f"AVISO DE TOKENS: {e}")
                    self._falar_se_permitido("Limite de cota atingido para processamento na nuvem.")
                except Exception as e:
                    logger.error(f"Falha ao processar solicitação por voz: {e}")
                    emitir_electron("error", {"message": f"Falha ao processar: {e}"})
                finally:
                    self._set_estado("WAITING_INPUT")

            # -----------------------------------------------------------------
            # TOGGLE MODO VOZ (ativação/desativação dinâmica)
            # -----------------------------------------------------------------
            elif tipo == "toggle_voice_mode":
                enabled = payload.get("enabled", False)

                if enabled:
                    status = self._ativar_modo_voz()
                else:
                    status = self._desativar_modo_voz()

                emitir_electron("voice_mode_status", status)

            # -----------------------------------------------------------------
            # TOGGLE MUTE (apenas controla TTS, não afeta microfone)
            # -----------------------------------------------------------------
            elif tipo == "toggle_mute":
                self.is_muted = payload.get("muted", not self.is_muted)
                logger.info(f"🔊 Estado do Áudio alterado: Mudo = {self.is_muted}")
                emitir_electron("debug_log", {
                    "message": f"{'🔇 Áudio silenciado.' if self.is_muted else '🔊 Áudio ativado.'}"
                })

            # -----------------------------------------------------------------
            # COMPATIBILIDADE: toggle_microphone antigo → redireciona
            # -----------------------------------------------------------------
            elif tipo == "toggle_microphone":
                enabled = payload.get("enabled", False)
                logger.info(f"toggle_microphone recebido (compatibilidade) → redirecionando para toggle_voice_mode")
                self.fila.put({"type": "toggle_voice_mode", "payload": {"enabled": enabled}})

            else:
                logger.warning(f"Comando desconhecido recebido: {tipo}")

        # =====================================================================
        # SHUTDOWN GRACEFUL
        # =====================================================================
        logger.info("Iniciando shutdown graceful...")
        self._set_estado("STOPPING")

        if self.audio_service:
            self.audio_service.abortar_captura()
        if self.voice_service:
            self.voice_service.encerrar()

        AudioService.remover_callbacks()
        VoiceService.remover_callbacks()

        logger.info("Runtime finalizado com sucesso.")


if __name__ == "__main__":
    runtime = AssistenteRuntime()
    runtime.rodar()