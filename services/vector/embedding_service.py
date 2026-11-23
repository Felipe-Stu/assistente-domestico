import logging
import threading
import time
from typing import Callable, List, Optional
from core.config import EMBEDDING_DEVICE, EMBEDDING_MODEL_NAME
from services.logger_service import logger as custom_logger

logging_logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Serviço responsável por gerar embeddings vetoriais locais utilizando a CPU.
    Utiliza SentenceTransformers com fallback resiliente para garantir que o
    modelo generativo Ollama (na VRAM/GPU) não seja impactado.

    O modelo leva vários segundos para carregar. Por isso o construtor é leve:
    a carga ocorre no primeiro uso ou em segundo plano (carregar_em_segundo_plano),
    para que o chat fique disponível antes da memória semântica.
    """

    _instancia_modelo = None  # Singleton para evitar recarregar o modelo da CPU em memória
    _trava_carga = threading.Lock()    # protege a carga do modelo (pode durar vários segundos)
    _trava_thread = threading.Lock()   # protege apenas o registro da thread de carga
    _thread_carga: Optional[threading.Thread] = None
    _erro_carga: Optional[str] = None

    def __init__(self, model_name: str = None, carregar_agora: bool = False):
        self.model_name = model_name or EMBEDDING_MODEL_NAME
        if carregar_agora:
            self._inicializar_modelo()

    @classmethod
    def pronto(cls) -> bool:
        """True quando o modelo já está em memória."""
        return cls._instancia_modelo is not None

    @classmethod
    def carregando(cls) -> bool:
        """True enquanto a carga em segundo plano está em andamento."""
        thread = cls._thread_carga
        return thread is not None and thread.is_alive()

    @classmethod
    def erro_carga(cls) -> Optional[str]:
        """Mensagem da última falha de carga, ou None."""
        return cls._erro_carga

    def _inicializar_modelo(self):
        """Carrega o modelo uma única vez. Chamadas concorrentes aguardam a mesma carga."""
        if EmbeddingService._instancia_modelo is not None:
            return
        with EmbeddingService._trava_carga:
            if EmbeddingService._instancia_modelo is not None:
                return
            if EmbeddingService._erro_carga is not None:
                # Uma carga já falhou nesta execução; repetir custaria vários segundos a cada chamada
                raise RuntimeError(f"Modelo de embeddings indisponível: {EmbeddingService._erro_carga}")
            try:
                t0 = time.time()
                from sentence_transformers import SentenceTransformer
                logging_logger.info(f"Carregando modelo de embeddings ({EMBEDDING_DEVICE}): '{self.model_name}'...")
                try:
                    # Só o cache local: evita ~30 consultas ao Hugging Face a cada início e funciona sem rede
                    modelo = SentenceTransformer(self.model_name, device=EMBEDDING_DEVICE, local_files_only=True)
                except Exception as e_local:
                    # Primeira execução (modelo fora do cache) ou versão sem local_files_only: baixa normalmente
                    logging_logger.info(f"[EMBEDDING] Cache local indisponível ({e_local}); carregando com acesso à rede.")
                    modelo = SentenceTransformer(self.model_name, device=EMBEDDING_DEVICE)
                EmbeddingService._instancia_modelo = modelo
                elapsed_ms = int((time.time() - t0) * 1000)
                msg = f"[EMBEDDING] Modelo '{self.model_name}' carregado com sucesso ({EMBEDDING_DEVICE}, {elapsed_ms}ms)."
                logging_logger.info(msg)
                custom_logger.log_assistente("embedding_service", msg)
            except Exception as e:
                EmbeddingService._erro_carga = str(e)
                msg_erro = f"[EMBEDDING] Erro ao carregar modelo '{self.model_name}': {e}"
                logging_logger.error(msg_erro)
                custom_logger.log_assistente("embedding_service", msg_erro)
                raise

    def carregar_em_segundo_plano(
        self, ao_concluir: Optional[Callable[[bool, Optional[str]], None]] = None
    ) -> threading.Thread:
        """
        Inicia a carga do modelo em uma thread daemon e retorna imediatamente.
        ao_concluir(sucesso, erro) é chamado ao final, na própria thread de carga.
        """
        def _carregar():
            erro = None
            try:
                self._inicializar_modelo()
            except Exception as e:
                erro = str(e)
            if ao_concluir:
                try:
                    ao_concluir(erro is None, erro)
                except Exception as e_cb:
                    logging_logger.error(f"Erro no aviso de conclusão da carga de embeddings: {e_cb}")

        with EmbeddingService._trava_thread:
            thread = EmbeddingService._thread_carga
            if thread is not None and thread.is_alive():
                return thread
            thread = threading.Thread(target=_carregar, name="carga-embeddings", daemon=True)
            EmbeddingService._thread_carga = thread
            thread.start()
        return thread

    def gerar_embedding(self, texto: str) -> List[float]:
        """
        Gera um vetor (embedding) para uma única string de texto.
        """
        if not texto or not texto.strip():
            return []

        t0 = time.time()
        try:
            self._inicializar_modelo()
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
            self._inicializar_modelo()
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
