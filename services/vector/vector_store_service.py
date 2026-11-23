import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from core.config import CHROMA_DIR
from services.vector.embedding_service import EmbeddingService
from services.logger_service import logger as custom_logger

logging_logger = logging.getLogger(__name__)

# Nome Padrão da Coleção Principal
DEFAULT_COLLECTION = "assistente_domestico_memory"


@dataclass
class VectorDocument:
    """
    Representação estruturada de um documento vetorial no sistema.
    """
    id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None


class VectorStoreService:
    """
    Serviço central de integração com o banco vetorial ChromaDB.
    Armazena e recupera vetores com suporte a metadados e persistência local no Windows.
    """

    _client = None

    def __init__(self, persistent_dir: str = None, embedding_service: Optional[EmbeddingService] = None):
        self.persistent_dir = str(persistent_dir or CHROMA_DIR)
        self.embedding_service = embedding_service or EmbeddingService()
        self._inicializar_chroma()

    def _inicializar_chroma(self):
        if VectorStoreService._client is None:
            try:
                import chromadb
                from chromadb.config import Settings
                logging_logger.info(f"Inicializando ChromaDB PersistentClient em: '{self.persistent_dir}'...")
                VectorStoreService._client = chromadb.PersistentClient(
                    path=self.persistent_dir,
                    settings=Settings(anonymized_telemetry=False, allow_reset=True)
                )
                msg = f"[VECTOR_STORE] ChromaDB inicializado em '{self.persistent_dir}'."
                logging_logger.info(msg)
                custom_logger.log_assistente("vector_store", msg)
            except Exception as e:
                msg_erro = f"[VECTOR_STORE] Erro ao inicializar ChromaDB: {e}"
                logging_logger.error(msg_erro)
                custom_logger.log_assistente("vector_store", msg_erro)
                raise

    @property
    def client(self):
        return VectorStoreService._client

    def _obter_colecao(self, name: str = DEFAULT_COLLECTION):
        """Retorna uma coleção do ChromaDB sem função de embedding interna para usar nosso EmbeddingService (CPU)."""
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"}
        )

    def upsert_documents(self, documents: List[VectorDocument], collection_name: str = DEFAULT_COLLECTION) -> bool:
        """
        Insere ou atualiza documentos no ChromaDB de forma idempotente.
        Se os vetores não tiverem sido calculados préviamente, invoca o EmbeddingService na CPU.
        """
        if not documents:
            return True

        t0 = time.time()
        try:
            colecao = self._obter_colecao(collection_name)

            ids = [doc.id for doc in documents]
            contents = [doc.content for doc in documents]
            metadatas = [doc.metadata for doc in documents]

            # Vetorização em lote na CPU para documentos sem embeddings pré-calculados
            docs_sem_emb = [i for i, doc in enumerate(documents) if doc.embedding is None]
            if docs_sem_emb:
                textos_para_vetorizar = [contents[i] for i in docs_sem_emb]
                embeddings_gerados = self.embedding_service.gerar_embeddings_em_lote(textos_para_vetorizar)
                for idx_orig, emb in zip(docs_sem_emb, embeddings_gerados):
                    documents[idx_orig].embedding = emb

            embeddings = [doc.embedding for doc in documents]
            if any(not emb for emb in embeddings):
                # Sem vetor próprio, o ChromaDB usaria outro modelo de embeddings; melhor não gravar
                msg = f"[VECTOR_STORE] Upsert cancelado: embeddings indisponíveis para {len(documents)} doc(s)."
                logging_logger.warning(msg)
                custom_logger.log_assistente("vector_store", msg)
                return False

            colecao.upsert(
                ids=ids,
                documents=contents,
                metadatas=metadatas,
                embeddings=embeddings
            )

            elapsed_ms = int((time.time() - t0) * 1000)
            msg = f"[VECTOR_STORE] Upsert concluído: {len(documents)} doc(s) na coleção '{collection_name}' ({elapsed_ms}ms)."
            logging_logger.info(msg)
            custom_logger.log_assistente("vector_store", msg)
            return True

        except Exception as e:
            msg_erro = f"[VECTOR_STORE] Falha ao fazer upsert na coleção '{collection_name}': {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente("vector_store", msg_erro)
            return False

    def search_similarity(
        self,
        query_text: str,
        top_k: int = 5,
        where_filter: Optional[dict] = None,
        min_score: float = 0.0,
        collection_name: str = DEFAULT_COLLECTION
    ) -> List[Dict[str, Any]]:
        """
        Realiza busca vetorial semântica por similaridade de cosseno com metadados e filtro de corte (threshold).
        Retorna lista de dicionários contendo: id, content, metadata, score e distance.
        """
        if not query_text or not query_text.strip():
            return []

        if self.embedding_service.carregando() and not self.embedding_service.pronto():
            # Início do sistema: a resposta ao usuário não espera a carga do modelo (segue sem RAG)
            custom_logger.log_assistente(
                "vector_store",
                "[SEMANTIC_SEARCH] Modelo de embeddings ainda carregando; busca ignorada."
            )
            return []

        t0 = time.time()
        try:
            colecao = self._obter_colecao(collection_name)

            # Vetoriza a consulta do usuário na CPU
            query_vector = self.embedding_service.gerar_embedding(query_text)
            if not query_vector:
                return []

            kwargs = {
                "query_embeddings": [query_vector],
                "n_results": top_k,
                "include": ["documents", "metadatas", "distances"]
            }
            if where_filter:
                kwargs["where"] = where_filter

            res = colecao.query(**kwargs)

            resultados = []
            if res and res.get("ids") and res["ids"][0]:
                ids = res["ids"][0]
                docs = res["documents"][0]
                metas = res["metadatas"][0]
                distances = res["distances"][0]

                for doc_id, content, meta, dist in zip(ids, docs, metas, distances):
                    # ChromaDB com espaço cosseno retorna distância cosseno (0 = idêntico, 1 = oposto)
                    # Convertemos para score de similaridade (1 - distância)
                    score = max(0.0, min(1.0, 1.0 - dist))

                    if score >= min_score:
                        resultados.append({
                            "id": doc_id,
                            "content": content,
                            "metadata": meta,
                            "distance": round(dist, 4),
                            "score": round(score, 4)
                        })

            elapsed_ms = int((time.time() - t0) * 1000)
            best_score = resultados[0]["score"] if resultados else 0.0
            msg = f"[SEMANTIC_SEARCH] query='{query_text[:30]}...' results={len(resultados)} best_score={best_score} elapsed={elapsed_ms}ms"
            logging_logger.info(msg)
            custom_logger.log_assistente("vector_store", msg)

            return resultados

        except Exception as e:
            msg_erro = f"[SEMANTIC_SEARCH] Erro durante busca semântica: {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente("vector_store", msg_erro)
            return []

    def delete_documents(self, ids: List[str], collection_name: str = DEFAULT_COLLECTION) -> bool:
        """Remove documentos do banco vetorial pelo ID."""
        if not ids:
            return True
        try:
            colecao = self._obter_colecao(collection_name)
            colecao.delete(ids=ids)
            msg = f"[VECTOR_STORE] {len(ids)} documento(s) removido(s) da coleção '{collection_name}'."
            logging_logger.info(msg)
            custom_logger.log_assistente("vector_store", msg)
            return True
        except Exception as e:
            msg_erro = f"[VECTOR_STORE] Erro ao deletar documentos no ChromaDB: {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente("vector_store", msg_erro)
            return False

    def count_documents(self, collection_name: str = DEFAULT_COLLECTION) -> int:
        """Retorna a quantidade total de registros na coleção."""
        try:
            colecao = self._obter_colecao(collection_name)
            return colecao.count()
        except Exception:
            return 0
