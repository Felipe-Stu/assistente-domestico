import sys
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from services.vector.semantic_search_service import SemanticSearchService
from services.vector.memory_service import MemoryService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ValidateVectorDB")


def testar_busca_semantica():
    logger.info("==================================================")
    logger.info("INICIANDO SUÍTE DE TESTES DA MEMÓRIA VETORIAL (RAG)")
    logger.info("==================================================")

    mem_service = MemoryService()
    search_service = SemanticSearchService()

    # 1. Inserir sementes de teste
    logger.info("1. Inserindo dados de teste de preferências e compras...")
    mem_service.salvar_memoria_longo_prazo(
        conteudo="Felipe prefere utilizar sabão em pó da marca OMO para lavar roupas pesadas.",
        assistant="geral",
        category="preferencia"
    )
    mem_service.salvar_memoria_longo_prazo(
        conteudo="O usuário costuma comprar peito de frango congelado no mercado Max Atacadista.",
        assistant="compras",
        category="alimentacao"
    )

    # 2. Teste 1: Busca Semântica por Sinônimos (Detergente/Sabão)
    logger.info("\n--- TESTE 1: Consulta por 'produto para lavar roupas' ---")
    query_1 = "produto para lavar roupas"
    res_1 = search_service.busca_semantica_pura(query_1, top_k=3, min_score=0.40)

    for i, item in enumerate(res_1, 1):
        logger.info(f"  Resultado {i}: [Score: {item['score']}] '{item['content']}'")

    if res_1 and any("sabão" in item['content'].lower() or "omo" in item['content'].lower() for item in res_1):
        logger.info("✅ TESTE 1 PASSOU: Sabão em pó OMO localizado com sucesso via semântica.")
    else:
        logger.warning("⚠️ TESTE 1 FALHOU: Produto de lavar roupa não localizado.")

    # 3. Teste 2: Consulta por 'carne de frango'
    logger.info("\n--- TESTE 2: Consulta por 'carne de frango' ---")
    query_2 = "carne de frango"
    res_2 = search_service.busca_semantica_pura(query_2, assistant="compras", top_k=3, min_score=0.40)

    for i, item in enumerate(res_2, 1):
        logger.info(f"  Resultado {i}: [Score: {item['score']}] '{item['content']}'")

    if res_2 and any("frango" in item['content'].lower() for item in res_2):
        logger.info("✅ TESTE 2 PASSOU: Peito de frango localizado com sucesso via semântica.")
    else:
        logger.warning("⚠️ TESTE 2 FALHOU: Frango não localizado na busca semântica.")

    # 4. Teste 3: Busca Híbrida Hidratada (ChromaDB + SQLite)
    logger.info("\n--- TESTE 3: Busca Híbrida Hidratada ---")
    query_3 = "onde comprei frango?"
    res_3 = search_service.busca_hibrida_compra(query_3, top_k=3)

    for i, item in enumerate(res_3, 1):
        logger.info(f"  Resultado {i}: [Score: {item['score']}] '{item['content_semantico']}' | SQLite Hidratado: {item['dados_relacionais']}")

    logger.info("\n==================================================")
    logger.info("SUÍTE DE TESTES CONCLUÍDA")
    logger.info("==================================================")


if __name__ == "__main__":
    testar_busca_semantica()
