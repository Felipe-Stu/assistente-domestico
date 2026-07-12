import logging
import sys
from pathlib import Path

# Ajusta o sys.path para permitir importações absolutas dos módulos 'core' e 'services'
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from services.audio_service import AudioService
from services.ai_service import processar_texto_com_gemini
from services.db_service import DatabaseService
# Importação do novo Assistente de Inventário da V3
from services.inventory_assistant import InventoryAssistant

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def rodar_assistente():
    logger.info("=========================================================")
    logger.info("Iniciando Orquestração do Assistente Doméstico (MVP + V3)")
    logger.info("=========================================================")
    
    # 1. Inicialização dos Serviços
    try:
        db_service = DatabaseService()
        audio_service = AudioService()
        # Inicializa o assistente de estoque passando a conexão do banco
        inventory_assistant = InventoryAssistant(db_service)
    except Exception as e:
        logger.critical("Erro fatal ao inicializar os serviços do sistema: %s", e)
        sys.exit(1)

    # 2. Execução do Fluxo de Operações
    try:
        # [V3] GATILHO 1: Varredura preditiva de inicialização
        # Verifica se itens ativos passaram do tempo e pergunta ao usuário via voz
        inventory_assistant.verificar_itens_expirados_inicializacao()
        
        # Passo 1: Captura de voz e transcrição do áudio bruto de novas compras/despesas
        transcricao = audio_service.capturar_audio_e_transcrever()
        
        # Passo 2: Envio do texto bruto para estruturação via Inteligência Artificial
        retorno_ia = processar_texto_com_gemini(transcricao)
        
        # Garante que pegamos a lista de compras independente de como o JSON foi envelopado
        listagem_compras = []
        if isinstance(retorno_ia, dict):
            listagem_compras = retorno_ia.get("compras", [retorno_ia])
        elif isinstance(retorno_ia, list):
            listagem_compras = retorno_ia
            
        if not listagem_compras:
            raise ValueError("Nenhuma estrutura de compra válida foi detectada pelo Gemini.")

        logger.info(f"IA detectou {len(listagem_compras)} compra(s) distinta(s). Iniciando gravação...")

        # Passo 3: Iterar sobre cada mercado encontrado e persistir no banco
        for dados_compra in listagem_compras:
            lista_itens = dados_compra.get("itens")
            total_compra = dados_compra.get("valor_total_compra")
            estabelecimento = dados_compra.get('estabelecimento', 'Não informado')
            
            if not lista_itens or total_compra is None:
                logger.warning(f"Pulando registro de '{estabelecimento}' devido a dados inválidos ou vazios.")
                continue
                
            logger.info("Dados estruturados recebidos com sucesso da IA:")
            logger.info("Comércio: %s | Total calculado: R$ %.2f", estabelecimento, total_compra)
            
            # [V3] GATILHO 2: Interrupção Conversacional de Autonomia para Itens Comprados
            # Avalia item por item da lista para ver se há resíduo antes de salvar a compra
            for item in lista_itens:
                nome_prod = item.get("produto")
                qtd_comprada = float(item.get("quantidade", 1))
                
                if nome_prod:
                    # Executa o motor de estoque (Confirmação ou Negativas 1 e 2)
                    residuo_calculado = inventory_assistant.processar_estoque_nova_compra(
                        nome_produto=nome_prod.lower().strip(), 
                        nova_quantidade=qtd_comprada
                    )
                    
                    # Atualiza o item na memória do JSON caso queira que o db_service leia a sobra
                    item["quantidade_residual"] = residuo_calculado

            # Passo 4: Persistência no SQLite de cada compra individual (Estrutura original mantida)
            compra_id = db_service.salvar_compra_da_ia(dados_compra)
            logger.info("Compra gravada com sucesso! ID no Banco: %d", compra_id)
            
        logger.info("=========================================================")
        logger.info("Fluxo de orquestração multiflexível finalizado com sucesso!")
        logger.info("=========================================================")
        
    except Exception as e:
        logger.error("Falha na orquestração principal do MVP: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    rodar_assistente()