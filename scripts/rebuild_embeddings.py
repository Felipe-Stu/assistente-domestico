import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from core.config import BACKUP_DIARIOS, BACKUP_DIR, BACKUP_SEMANAIS, CHROMA_DIR, DB_PATH  # noqa: E402
from services.backup_service import BackupService  # noqa: E402
from services.vector.vector_store_service import VectorStoreService, VectorDocument, DEFAULT_COLLECTION  # noqa: E402
from scripts.migrate_vector_database import migrar_sqlite_para_chroma  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("RebuildEmbeddings")

PREFIXO_MEMORIA = "mem_"


class ReconstrucaoAbortada(Exception):
    """A coleção não foi apagada porque as memórias não puderam ser preservadas."""


def _nomes_das_colecoes(client) -> list:
    # ChromaDB >= 0.6 devolve nomes; versões antigas devolvem objetos Collection
    return [getattr(c, "name", c) for c in client.list_collections()]


def exportar_memorias(vector_store) -> list:
    """
    Lê as memórias (ids mem_*) da coleção. Elas não vêm do SQLite: a migração não as recria (P13).
    Sem vetor: serão recalculadas com o modelo de embeddings atual.
    """
    if DEFAULT_COLLECTION not in _nomes_das_colecoes(vector_store.client):
        return []
    colecao = vector_store.client.get_collection(DEFAULT_COLLECTION)
    dados = colecao.get(include=["documents", "metadatas"])
    metadados = dados.get("metadatas") or [None] * len(dados["ids"])
    return [
        VectorDocument(id=doc_id, content=conteudo, metadata=dict(meta or {}))
        for doc_id, conteudo, meta in zip(dados["ids"], dados["documents"], metadados)
        if doc_id.startswith(PREFIXO_MEMORIA)
    ]


def salvar_exportacao(memorias: list, pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"memorias-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    conteudo = [{"id": m.id, "content": m.content, "metadata": m.metadata} for m in memorias]
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def reconstruir_embeddings(vector_store=None, migrar=migrar_sqlite_para_chroma, backup=None, pasta_exportacao=None):
    """
    Recria todos os embeddings do zero (ex.: troca do modelo de embeddings), sem perder memórias:
    1. cópia de segurança do SQLite e do ChromaDB;
    2. exporta as memórias mem_* para JSON;
    3. apaga a coleção e reindexa compras e estoque a partir do SQLite;
    4. regrava as memórias com o modelo atual.
    """
    logger.info("Iniciando a reconstrução dos embeddings...")
    if backup is None:
        backup = BackupService(DB_PATH, CHROMA_DIR, BACKUP_DIR, diarios=BACKUP_DIARIOS, semanais=BACKUP_SEMANAIS)
    if backup is not False:
        logger.info(f"Cópia de segurança gravada em {backup.fazer_backup(forcar=True)}")

    vector_store = vector_store or VectorStoreService()
    try:
        memorias = exportar_memorias(vector_store)
    except Exception as e:
        raise ReconstrucaoAbortada(f"Não foi possível ler as memórias; nada foi apagado: {e}") from e

    if memorias:
        exportacao = salvar_exportacao(memorias, Path(pasta_exportacao or BACKUP_DIR))
        logger.info(f"{len(memorias)} memória(s) exportada(s) para {exportacao}")

    if DEFAULT_COLLECTION in _nomes_das_colecoes(vector_store.client):
        logger.info(f"Apagando a coleção '{DEFAULT_COLLECTION}'...")
        vector_store.client.delete_collection(DEFAULT_COLLECTION)

    logger.info("Reindexando compras e estoque a partir do SQLite...")
    migrar()

    if memorias:
        if not vector_store.upsert_documents(memorias):
            raise RuntimeError(
                f"As {len(memorias)} memórias não foram regravadas. Elas estão salvas em {exportacao}; "
                "rode o script de novo quando o modelo de embeddings estiver disponível."
            )
        logger.info(f"{len(memorias)} memória(s) regravada(s).")

    logger.info("Reconstrução concluída.")
    return len(memorias)


if __name__ == "__main__":
    reconstruir_embeddings()
