import os
import sys
import logging
from pathlib import Path

# Ajusta o sys.path para garantir importação dos pacotes do projeto
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from services.db_service import DatabaseService
from services.vector.vector_store_service import VectorStoreService, VectorDocument
from services.vector.embedding_service import EmbeddingService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MigrateVectorDB")


def migrar_sqlite_para_chroma():
    """
    Script de migração idempotente:
    Lê os dados existentes no SQLite (compras, itens de compra, controle de consumo)
    e cria/atualiza seus correspondentes vetoriais no ChromaDB.
    """
    logger.info("Starting migration of SQLite records to ChromaDB...")

    db = DatabaseService()
    vector_store = VectorStoreService()
    embedding_svc = EmbeddingService()

    total_itens_migrados = 0
    total_erros = 0

    # 1. Migração de Itens de Compras (`itens_compra` JOIN `compras`)
    logger.info("Migrating historical purchase items...")
    query_compras = """
        SELECT i.id, i.compra_id, i.produto, i.marca, i.quantidade, i.unidade, 
               i.valor_unitario, i.valor_total, i.categoria, c.data_compra, c.nome_comercio
        FROM itens_compra i
        JOIN compras c ON i.compra_id = c.id
    """
    itens_compra = db.executar_consulta(query_compras)
    logger.info(f"Found {len(itens_compra)} purchase items in SQLite.")

    docs_compra = []
    for row in itens_compra:
        try:
            item_id, compra_id, produto, marca, qtd, unidade, v_unit, v_tot, cat, data_c, comercio = row
            comercio_str = comercio if comercio else "Não especificado"
            marca_str = f" da marca {marca}" if marca else ""
            cat_str = cat if cat else "geral"

            # Representação em linguagem natural rica
            texto_doc = (
                f"Compra de {qtd} {unidade} de {produto}{marca_str} no estabelecimento {comercio_str} "
                f"por R$ {v_tot:.2f} (R$ {v_unit:.2f}/{unidade}) na data {data_c}. Categoria: {cat_str}."
            )

            doc_id = f"purchase_item_{item_id}"
            metadata = {
                "assistant": "compras",
                "category": cat_str.lower(),
                "entity_type": "purchase_item",
                "entity_id": item_id,
                "compra_id": compra_id,
                "produto": produto.lower(),
                "estabelecimento": comercio_str.lower(),
                "created_at": data_c,
                "source": "sqlite_migration"
            }

            docs_compra.append(VectorDocument(id=doc_id, content=texto_doc, metadata=metadata))
        except Exception as e:
            logger.error(f"Error preparing purchase item record {row}: {e}")
            total_erros += 1

    if docs_compra:
        sucesso = vector_store.upsert_documents(docs_compra)
        if sucesso:
            total_itens_migrados += len(docs_compra)
            logger.info(f"Successfully migrated {len(docs_compra)} purchase items into vector store.")

    # 2. Migração de Controle de Consumo (`controle_consumo`)
    logger.info("Migrating inventory consumption control items...")
    query_estoque = """
        SELECT id, produto_nome, categoria, tempo_medio_calculado, data_ultima_compra, 
               quantidade_comprada, quantidade_residual_confirmada, status_estoque
        FROM controle_consumo
    """
    itens_estoque = db.executar_consulta(query_estoque)
    logger.info(f"Found {len(itens_estoque)} inventory items in SQLite.")

    docs_estoque = []
    for row in itens_estoque:
        try:
            item_id, produto_nome, cat, ritmo, data_u, qtd_c, qtd_r, status = row
            cat_str = cat if cat else "geral"
            status_str = "ativo" if status == 1 else "esgotado"

            texto_doc = (
                f"Controle de estoque do produto {produto_nome} (Categoria: {cat_str}). "
                f"Status: {status_str}. Ritmo estimado de consumo: {ritmo:.1f} dias. "
                f"Última compra em {data_u} (Qtd: {qtd_c}, Resíduo: {qtd_r})."
            )

            doc_id = f"inventory_item_{item_id}"
            metadata = {
                "assistant": "inventario",
                "category": cat_str.lower(),
                "entity_type": "inventory_item",
                "entity_id": item_id,
                "produto": produto_nome.lower(),
                "status_estoque": status,
                "created_at": data_u,
                "source": "sqlite_migration"
            }

            docs_estoque.append(VectorDocument(id=doc_id, content=texto_doc, metadata=metadata))
        except Exception as e:
            logger.error(f"Error preparing inventory record {row}: {e}")
            total_erros += 1

    if docs_estoque:
        sucesso = vector_store.upsert_documents(docs_estoque)
        if sucesso:
            total_itens_migrados += len(docs_estoque)
            logger.info(f"Successfully migrated {len(docs_estoque)} inventory items into vector store.")

    logger.info("==================================================")
    logger.info(f"Migration finished. Total vector records inserted/updated: {total_itens_migrados}. Errors: {total_erros}.")
    logger.info("==================================================")


if __name__ == "__main__":
    migrar_sqlite_para_chroma()
