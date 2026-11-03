import logging
import time
from typing import List, Union
from core.config import EMBEDDING_MODEL_NAME
from services.logger_service import logger as custom_logger

logging_logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Serviço responsável por gerar embeddings vetoriais locais utilizando a CPU.
    Utiliza SentenceTransformers com fallback resiliente para garantir que o 
    modelo generativo Ollama (na VRAM/GPU) não seja impactado.
    """

    _instancia_modelo = None  # Singleton para evitar recarregar o modelo da CPU em memória

    def __init__(self, model_name: str = None):
        self.model_name = model_name or EMBEDDING_MODEL_NAME
        self._inicializar_modelo()

    def _inicializar_modelo(self):
        if EmbeddingService._instancia_modelo is None:
            try:
                t0 = time.time()
                from sentence_transformers import SentenceTransformer
                logging_logger.info(f"Carregando modelo de embeddings na CPU: '{self.model_name}'...")
                EmbeddingService._instancia_modelo = SentenceTransformer(self.model_name)
                elapsed_ms = int((time.time() - t0) * 1000)
                msg = f"[EMBEDDING] Modelo '{self.model_name}' carregado com sucesso na CPU ({elapsed_ms}ms)."
                logging_logger.info(msg)
                custom_logger.log_assistente("embedding_service", msg)
            except Exception as e:
                msg_erro = f"[EMBEDDING] Erro ao carregar modelo '{self.model_name}': {e}"
                logging_logger.error(msg_erro)
                custom_logger.log_assistente("embedding_service", msg_erro)
                raise

    def gerar_embedding(self, texto: str) -> List[float]:
        """
        Gera um vetor (embedding) para uma única string de texto.
        """
        if not texto or not texto.strip():
            return []

        t0 = time.time()
        try:
            vector = EmbeddingService._instancia_modelo.encode(texto, convert_to_numpy=True).tolist()
            elapsed_ms = int((time.time() - t0) * 1000)
            custom_logger.log_assistente(
                "embedding_service",
                f"[EMBEDDING] texto_len={len(texto)} dim={len(vector)} elapsed={elapsed_ms}ms"
            )
            return vector
        except Exception as e:
            msg_erro = f"[EMBEDDING] Falha ao gerar embedding para o texto '{texto[:30]}...': {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente("embedding_service", msg_erro)
            return []

    def gerar_embeddings_em_lote(self, textos: List[str]) -> List[List[float]]:
        """
        Gera embeddings em lote para otimizar inferência na CPU.
        """
        if not textos:
            return []

        t0 = time.time()
        try:
            vectors = EmbeddingService._instancia_modelo.encode(textos, convert_to_numpy=True, batch_size=32).tolist()
            elapsed_ms = int((time.time() - t0) * 1000)
            custom_logger.log_assistente(
                "embedding_service",
                f"[EMBEDDING] batch_size={len(textos)} elapsed={elapsed_ms}ms"
            )
            return vectors
        except Exception as e:
            msg_erro = f"[EMBEDDING] Falha ao gerar embeddings em lote ({len(textos)} itens): {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente("embedding_service", msg_erro)
            return []
