import sys
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from services.vector.vector_store_service import VectorStoreService, DEFAULT_COLLECTION
from scripts.migrate_vector_database import migrar_sqlite_para_chroma

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("RebuildEmbeddings")


def reconstruir_embeddings():
    """
    Limpa a coleção principal do ChromaDB e recria todos os embeddings do zero.
    Util para atualizações do modelo de embedding ou re-inicializações limpas.
    """
    logger.info("Initializing vector embeddings rebuild process...")
    vector_store = VectorStoreService()

    try:
        logger.info(f"Deleting collection '{DEFAULT_COLLECTION}' from ChromaDB...")
        vector_store.client.delete_collection(DEFAULT_COLLECTION)
        logger.info("Collection deleted successfully.")
    except Exception as e:
        logger.warning(f"Could not delete collection (it may not exist yet): {e}")

    logger.info("Executing database re-indexing...")
    migrar_sqlite_para_chroma()
    logger.info("Embedding rebuild process completed successfully!")


if __name__ == "__main__":
    reconstruir_embeddings()
