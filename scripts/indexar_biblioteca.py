"""
Monta ou atualiza a biblioteca de contexto da skill de programação (SKP).
Só reindexa os arquivos que mudaram. Roda no PC (precisa do ChromaDB e do modelo de embeddings).

    python scripts/indexar_biblioteca.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import DB_DIR  # noqa: E402
from services.biblioteca_service import BibliotecaService  # noqa: E402


def criar_biblioteca() -> BibliotecaService:
    from services.vector.vector_store_service import VectorStoreService
    return BibliotecaService(VectorStoreService(), ROOT, DB_DIR / "biblioteca_indice.json")


def main():
    biblioteca = criar_biblioteca()
    print(f"Fontes: {len(biblioteca.fontes())} arquivos")
    contagem = biblioteca.indexar()
    print(f"Arquivos: {contagem['arquivos']} | atualizados: {contagem['atualizados']} | "
          f"trechos: {contagem['trechos']} | removidos: {contagem['removidos']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
