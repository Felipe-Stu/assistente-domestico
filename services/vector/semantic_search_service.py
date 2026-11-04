import logging
from typing import Dict, List, Any, Optional, Union
from services.vector.vector_store_service import VectorStoreService
from services.vector.memory_service import MemoryService
from services.db_service import DatabaseService
from services.logger_service import logger as custom_logger

logging_logger = logging.getLogger(__name__)


class SemanticSearchService:
    """
    Serviço de Busca Semântica Híbrida (Vector Store + Hydration do SQLite).
    Recupera informações semânticas no ChromaDB e hidrata dados exatos do SQLite quando necessário.
    """

    def __init__(
        self,
        vector_store: Optional[VectorStoreService] = None,
        db_service: Optional[DatabaseService] = None
    ):
        self.vector_store = vector_store or VectorStoreService()
        self.db_service = db_service or DatabaseService()

    def busca_semantica_pura(
        self,
        query: str,
        assistant: Optional[Union[str, List[str]]] = None,
        top_k: int = 5,
        min_score: float = 0.65
    ) -> List[Dict[str, Any]]:
        """
        Executa busca vetorial pura no ChromaDB com score mínimo e filtro de metadados.
        assistant aceita um contexto ou uma lista de contextos permitidos.
        """
        where_filter = None
        if isinstance(assistant, (list, tuple, set)):
            where_filter = {"assistant": {"$in": list(assistant)}}
        elif assistant:
            where_filter = {"assistant": assistant}
        return self.vector_store.search_similarity(
            query_text=query,
            top_k=top_k,
            where_filter=where_filter,
            min_score=min_score
        )

    def busca_hibrida_compra(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Busca semântica híbrida para o assistente de compras:
        1. Localiza os itens semanticamente equivalentes no ChromaDB (ex: "frango" -> "Peito de Frango Seara").
        2. Se houver `entity_id` apontando para `itens_compra.id` no SQLite, busca os valores exatos e atualizados no SQLite.
        3. Monta uma estrutura consolidada contendo tanto a representação semântica quanto os valores financeiros exatos.
        """
        res_vetoriais = self.busca_semantica_pura(
            query=query,
            assistant="compras",
            top_k=top_k,
            min_score=0.60
        )

        resultados_hibridos = []

        for item in res_vetoriais:
            meta = item.get("metadata", {})
            entity_type = meta.get("entity_type")
            entity_id = meta.get("entity_id")

            dado_hibrido = {
                "vector_id": item["id"],
                "content_semantico": item["content"],
                "score": item["score"],
                "dados_relacionais": None
            }

            # Hidratação do SQLite se houver referência de entidade
            if entity_type == "purchase_item" and entity_id and entity_id > 0:
                query_sql = """
                    SELECT i.id, i.compra_id, i.produto, i.marca, i.quantidade, i.unidade, 
                           i.valor_unitario, i.valor_total, i.categoria, c.data_compra, c.nome_comercio
                    FROM itens_compra i
                    JOIN compras c ON i.compra_id = c.id
                    WHERE i.id = ?
                """
                row = self.db_service.executar_consulta_uma_linha(query_sql, (entity_id,))
                if row:
                    dado_hibrido["dados_relacionais"] = {
                        "item_id": row[0],
                        "compra_id": row[1],
                        "produto": row[2],
                        "marca": row[3],
                        "quantidade": row[4],
                        "unidade": row[5],
                        "valor_unitario": row[6],
                        "valor_total": row[7],
                        "categoria": row[8],
                        "data_compra": row[9],
                        "estabelecimento": row[10]
                    }

            resultados_hibridos.append(dado_hibrido)

        custom_logger.log_assistente(
            "semantic_search",
            f"[HYBRID_SEARCH] query='{query[:30]}...' retornou {len(resultados_hibridos)} itens hidratados."
        )

        return resultados_hibridos
