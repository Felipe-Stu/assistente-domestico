import logging
from typing import List, Optional, Union
from services.vector.semantic_search_service import SemanticSearchService
from services.vector.memory_service import MemoryService
from services.logger_service import logger as custom_logger

logging_logger = logging.getLogger(__name__)


class ContextRetrievalService:
    """
    Serviço responsável por recuperar e formatar o contexto relevante da Memória Vetorial
    para injeção dinâmica nos Prompts do Orquestrador e dos Assistentes Especialistas (RAG).
    """

    def __init__(
        self,
        semantic_search_service: Optional[SemanticSearchService] = None,
        memory_service: Optional[MemoryService] = None
    ):
        self.semantic_search = semantic_search_service or SemanticSearchService()
        self.memory_service = memory_service or MemoryService()

    def montar_contexto_recuperado(
        self,
        query_usuario: str,
        assistant: Optional[Union[str, List[str]]] = None,
        top_k: int = 4,
        min_score: float = 0.65
    ) -> str:
        """
        Executa a recuperação de memória semântica e gera uma string formatada
        pronta para ser anexada como contexto ao prompt da LLM.
        """
        if not query_usuario or not query_usuario.strip():
            return ""

        # 1. Recupera memórias semânticas com corte de relevância
        memorias = self.semantic_search.busca_semantica_pura(
            query=query_usuario,
            assistant=assistant,
            top_k=top_k,
            min_score=min_score
        )

        if not memorias:
            return ""

        linhas_contexto = []
        for mem in memorias:
            content = mem["content"]
            meta = mem.get("metadata", {})
            cat = meta.get("category", "geral")
            data = meta.get("created_at", "")[:10]

            if data:
                linhas_contexto.append(f"- [{cat.upper()} | {data}]: {content}")
            else:
                linhas_contexto.append(f"- [{cat.upper()}]: {content}")

        bloco_contexto = "\n".join(linhas_contexto)

        contexto_formatado = f"""
==================================================
MEMÓRIA SEMÂNTICA RECUPERADA (CONTEXTO HISTÓRICO):
==================================================
{bloco_contexto}
==================================================
"""
        msg = f"[RAG] Contexto montado com {len(memorias)} memória(s) relevante(s) para query='{query_usuario[:30]}...'."
        logging_logger.info(msg)
        custom_logger.log_assistente("context_retrieval", msg)

        return contexto_formatado
