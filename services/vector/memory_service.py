import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from services.vector.vector_store_service import VectorStoreService, VectorDocument
from services.logger_service import logger as custom_logger

logging_logger = logging.getLogger(__name__)

# Palavras/Comandos descartados automaticamente da vetorização de longo prazo
TERMOS_IGNORADOS_LONG_TERM = {
    "olá", "ola", "bom dia", "boa tarde", "boa noite", "oi", "tchau", "ok", 
    "obrigado", "valeu", "sim", "não", "nao", "confirmado", "entendido",
    "ativar qwen", "desativar qwen", "modo qwen", "modo programador"
}


class MemoryService:
    """
    Serviço gerenciador da Memória de Curto e Longo Prazo.
    Define critérios para salvar, filtrar, resumir e descartar interações do sistema.
    """

    def __init__(self, vector_store: Optional[VectorStoreService] = None):
        self.vector_store = vector_store or VectorStoreService()

    def _deve_salvar_em_longo_prazo(self, texto: str, assistant: str) -> bool:
        """
        Avalia se uma mensagem possui valor semântico relevante para persistência em longo prazo.
        Descarta saudações, interjeições simples e comandos de infraestrutura.
        """
        if not texto or len(texto.strip()) < 5:
            return False

        texto_lower = texto.lower().strip()
        if texto_lower in TERMOS_IGNORADOS_LONG_TERM:
            return False

        # Se for sobre compras ou inventário, sempre salvar a representação semântica
        if assistant in ["compras", "inventario"]:
            return True

        # Se for conversa geral, apenas salvar se contiver informações declarativas sobre o usuário
        indicadores_preferencia = ["gosto", "prefiro", "não gosto", "nao gosto", "compro", "minha marca", "sou", "tenho"]
        if any(ind in texto_lower for ind in indicadores_preferencia):
            return True

        return len(texto.split()) >= 4

    def salvar_memoria_longo_prazo(
        self,
        conteudo: str,
        assistant: str = "geral",
        category: str = "observacao",
        entity_type: str = "user_memory",
        entity_id: Optional[int] = None,
        source: str = "system",
        importance: int = 3
    ) -> Optional[str]:
        """
        Persiste uma nova memória semântica na coleção vetorial de longo prazo.
        Retorna o ID da memória gerada ou None se descartada.
        """
        if not self._deve_salvar_em_longo_prazo(conteudo, assistant):
            custom_logger.log_assistente(
                "memory",
                f"[MEMORY] Texto descartado da memória de longo prazo: '{custom_logger.conteudo(conteudo[:30])}...'"
            )
            return None

        mem_id = f"mem_{uuid.uuid4().hex[:12]}"
        now_str = datetime.now().isoformat()

        metadata = {
            "assistant": assistant,
            "category": category,
            "entity_type": entity_type,
            "entity_id": entity_id if entity_id is not None else -1,
            "source": source,
            "created_at": now_str,
            "importance": importance
        }

        doc = VectorDocument(
            id=mem_id,
            content=conteudo,
            metadata=metadata
        )

        sucesso = self.vector_store.upsert_documents([doc])
        if sucesso:
            msg = f"[MEMORY] Memória salva: id={mem_id} assistant={assistant} category={category}"
            logging_logger.info(msg)
            custom_logger.log_assistente("memory", msg)
            return mem_id

        return None

    def buscar_memorias_relevantes(
        self,
        query: str,
        assistant: Optional[str] = None,
        category: Optional[str] = None,
        top_k: int = 5,
        min_score: float = 0.60
    ) -> List[Dict[str, Any]]:
        """
        Recupera memórias semânticas de longo prazo baseadas na relevância contextual.
        """
        where_clause = {}
        if assistant:
            where_clause["assistant"] = assistant
        if category:
            where_clause["category"] = category

        filter_arg = where_clause if where_clause else None

        return self.vector_store.search_similarity(
            query_text=query,
            top_k=top_k,
            where_filter=filter_arg,
            min_score=min_score
        )
