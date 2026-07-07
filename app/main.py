import logging
import sys
from pathlib import Path

# Ajusta o sys.path para permitir importações absolutas dos módulos 'core' e 'services'
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from services.audio_service import AudioService
from services.ai_service import processar_texto_com_gemini  # Importação direta da nova função
from services.db_service import DatabaseService

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def rodar_assistente():
    logger.info("=========================================================")
    logger.info("Iniciando Orquestração do Assistente Doméstico (MVP)")
    logger.info("=========================================================")
    
    # 1. Inicialização dos Serviços
    try:
        db_service = DatabaseService()
        audio_service = AudioService()
    except Exception as e:
        logger.critical("Erro fatal ao inicializar os serviços do sistema: %s", e)
        sys.exit(1)

    # 2. Execução do Fluxo de Operações
    try:
        # Passo 1: Captura de voz e transcrição do áudio
        transcricao = audio_service.capturar_audio_e_transcrever()
        
        # Passo 2: Envio do texto bruto para estruturação via Inteligência Artificial (Novo Gemini SDK)
        dados_estruturados = processar_texto_com_gemini(transcricao)
        
        # Passo 3: Validação básica do retorno estruturado (Mapeado para o novo JSON)
        lista_itens = dados_estruturados.get("itens")
        total_compra = dados_estruturados.get("valor_total_compra")
        
        if not lista_itens or total_compra is None:
            raise ValueError(
                "Estrutura JSON retornada pela IA inválida. "
                "Necessita das chaves 'itens' e 'valor_total_compra'."
            )
            
        logger.info("Dados estruturados recebidos com sucesso da IA:")
        logger.info("Comércio: %s | Total calculado: R$ %.2f", 
                    dados_estruturados.get('estabelecimento', 'Não informado'), 
                    total_compra)
        
        # Passo 4: Persistência no SQLite de forma atômica usando a nova função alinhada
        compra_id = db_service.salvar_compra_da_ia(dados_estruturados)
        
        logger.info("Fluxo finalizado com sucesso! Compra gravada sob o ID: %d", compra_id)
        
    except Exception as e:
        logger.error("Falha na orquestração principal do MVP: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    rodar_assistente()