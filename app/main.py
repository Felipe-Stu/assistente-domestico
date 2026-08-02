import logging
import sys
import time
from pathlib import Path

# 1. Ajusta o sys.path PRIMEIRO para permitir as importações de 'services' e 'core'
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# 2. Importações do projeto
from services.audio_service import AudioService
from services.ai_service import AIService, TokenExhaustedException, ServiceUnavailableException
from services.voice_service import VoiceService
from services.db_service import DatabaseService
from services.inventory_assistant import InventoryAssistant
from services.shopping_assistant import ShoppingAssistant
from services.logger_service import logger as custom_logger  # Renomeado para evitar conflito


# Configuração do Logging nativo do Python (Console/Terminal)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)



# Grava o evento de inicialização no arquivo Logs/main/main_log.txt
custom_logger.log_geral("Inicialização do sistema.")

# Constante do tempo de espera para reententar a requisição em caso de erro 503
TEMPO_RETRY_503 = 5

def rodar_assistente():
    logger.info("=========================================================")
    logger.info("Iniciando Orquestração do Assistente Doméstico (MVP + V2 - PATCH 1 - Correção GEMINI, orquestração do sistema, criação de LOGS)")
    logger.info("=========================================================")
    
    # 1. Inicialização dos Serviços
    try:
        db_service = DatabaseService()
        audio_service = AudioService()
        ai_service = AIService()
        voice_service = VoiceService()
        
        # Inicializa os assistentes especializados
        inventory_assistant = InventoryAssistant(db_service)
        shopping_assistant = ShoppingAssistant(ai_service=ai_service, db_service=db_service)
    except Exception as e:
        msg_erro = f"Erro fatal ao inicializar os serviços do sistema: {e}"
        logger.critical(msg_erro)
        custom_logger.log_geral(msg_erro)
        sys.exit(1)

    # 2. Execução do Fluxo de Operações
    try:
        # [V3] GATILHO 1: Varredura preditiva de inicialização
        inventory_assistant.verificar_itens_expirados_inicializacao()
        
        # Passo 1: Captura de voz e transcrição do áudio
        transcricao = audio_service.capturar_audio_e_transcrever()
        
        # Registra a transcrição real e o direcionamento no arquivo de log geral
        if transcricao:
            custom_logger.log_geral(f"Áudio: '{transcricao}'")
            custom_logger.log_geral("LOG de qual assistente foi encaminhada a demanda: shopping_assistant")
        
        # Passo 2: O ShoppingAssistant processa a extração e grava no SQLite (Com resiliência a erro 503)
        resultado = None
        while True:
            try:
                resultado = shopping_assistant.processar_texto_compra(transcricao)
                break  # Sucesso! Sai do loop de retry
            except ServiceUnavailableException as e_503:
                msg_congestionado = "Tráfego congestionado. Fazendo nova requisição."
                logger.warning(f"⚠️ {msg_congestionado} (Detalhe: {e_503})")
                custom_logger.log_geral(f"ERRO 503 DETECTADO: {e_503}")
                custom_logger.log_geral(f"Ação: Transcrição salva. Disparando áudio e aguardando {TEMPO_RETRY_503}s para reenvio.")
                
                # Alerta sonoro ao usuário
                voice_service.falar(msg_congestionado)
                
                # Timer de espera de 5 segundos antes de reententar
                time.sleep(TEMPO_RETRY_503)
        
        # Exibe e grava a confirmação do assistente
        if resultado:
            mensagem_resultado = resultado.get("mensagem")
            logger.info("Resultado do processamento: %s", mensagem_resultado)
            custom_logger.log_geral(f"Processamento concluído: {mensagem_resultado}")
            
        logger.info("=========================================================")
        logger.info("Fluxo de orquestração multiflexível finalizado com sucesso!")
        logger.info("=========================================================")

    except TokenExhaustedException as e:
        # Trata o esgotamento de tokens capturado no ai_service
        msg_aviso = f"AVISO AO USUÁRIO: {e}"
        logger.warning(msg_aviso)
        custom_logger.log_geral(msg_aviso)

    except Exception as e:
        msg_falha = f"Falha na orquestração principal do MVP: {e}"
        logger.error(msg_falha)
        custom_logger.log_geral(msg_falha)
        sys.exit(1)

if __name__ == "__main__":
    rodar_assistente()