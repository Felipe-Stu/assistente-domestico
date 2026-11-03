import sys
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from services.vector.vector_store_service import VectorStoreService, DEFAULT_COLLECTION

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("InspectVectorDB")


def inspecionar_banco():
    vector_store = VectorStoreService()
    total = vector_store.count_documents(DEFAULT_COLLECTION)

    print("\n==================================================")
    print(f"INSPEÇÃO DO BANCO VETORIAL CHROMADB")
    print(f"Coleção: '{DEFAULT_COLLECTION}' | Total de Registros: {total}")
    print("==================================================\n")

    if total == 0:
        print("A coleção está vazia. Execute 'python scripts/migrate_vector_database.py' para popular.")
        return

    # Inspeciona os 10 primeiros registros
    res = vector_store.client.get_collection(DEFAULT_COLLECTION).get(limit=10, include=["documents", "metadatas"])

    print("Primeiros registros armazenados:\n")
    for doc_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
        print(f"ID: {doc_id}")
        print(f"  Conteúdo: {doc}")
        print(f"  Metadata: {meta}")
        print("-" * 50)


if __name__ == "__main__":
    inspecionar_banco()
