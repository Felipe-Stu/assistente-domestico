import sqlite3
import logging
from typing import Dict, List, Any
from core.config import DB_PATH

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class DatabaseService:
    """
    Serviço responsável por gerenciar a conexão com o banco de dados SQLite,
    inicialização de tabelas e persistência de dados de compras e itens.
    """
    def __init__(self):
        self.db_path = DB_PATH
        self.initialize_database()

    def get_connection(self) -> sqlite3.Connection:
        """
        Estabelece uma conexão com o banco de dados e ativa o suporte
        a chaves estrangeiras (Foreign Keys).
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON;")
            return conn
        except sqlite3.Error as e:
            logger.error("Erro ao conectar ao banco de dados: %s", e)
            raise

    def initialize_database(self):
        """
        Cria as tabelas 'compras' e 'itens_compra' se elas não existirem no esquema.
        """
        # Removido o NOT NULL de nome_comercio para aceitar quando a IA não identificar o local
        query_compras = """
        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_compra TEXT NOT NULL,
            nome_comercio TEXT,
            total_gasto REAL NOT NULL
        );
        """
        
        # Adicionado as colunas 'marca' e 'unidade' para bater com o mapeamento da IA
        query_itens = """
        CREATE TABLE IF NOT EXISTS itens_compra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compra_id INTEGER NOT NULL,
            produto TEXT NOT NULL,
            marca TEXT,
            quantidade REAL NOT NULL,
            unidade TEXT,
            valor_unitario REAL NOT NULL,
            valor_total REAL NOT NULL,
            categoria TEXT,
            FOREIGN KEY (compra_id) REFERENCES compras(id) ON DELETE CASCADE
        );
        """
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query_compras)
                cursor.execute(query_itens)
                conn.commit()
            logger.info("Banco de dados SQLite inicializado ou atualizado com sucesso.")
        except sqlite3.Error as e:
            logger.error("Falha ao inicializar tabelas do banco de dados: %s", e)
            raise

    def salvar_compra_da_ia(self, dados_ia: Dict[str, Any]) -> int:
        """
        Recebe o JSON direto extraído do Gemini e faz a inserção relacional no banco.
        
        :param dados_ia: Dicionário retornado pelo ai_service.py
        :return: ID da compra gerada
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            
            # Mapeamento do cabeçalho alinhado com o formato do JSON da IA
            data_compra = dados_ia.get("data_compra")
            nome_comercio = dados_ia.get("estabelecimento")
            total_gasto = dados_ia.get("valor_total_compra", 0.0)
            
            cursor.execute(
                """
                INSERT INTO compras (data_compra, nome_comercio, total_gasto)
                VALUES (?, ?, ?)
                """,
                (data_compra, nome_comercio, total_gasto)
            )
            compra_id = cursor.lastrowid
            
            # Lista de itens vindos da IA
            itens = dados_ia.get("itens", [])
            
            # Inserir cada item associado ao ID da compra mapeando marca e unidade
            for item in itens:
                cursor.execute(
                    """
                    INSERT INTO itens_compra (compra_id, produto, marca, quantidade, unidade, valor_unitario, valor_total, categoria)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        compra_id,
                        item.get("produto"),
                        item.get("marca"),
                        item.get("quantidade"),
                        item.get("unidade"),
                        item.get("valor_unitario"),
                        item.get("valor_total"),
                        item.get("categoria") # null por enquanto, preparado para o futuro
                    )
                )
            
            conn.commit()
            logger.info("Compra (ID: %d) e %d itens gravados com sucesso via IA.", compra_id, len(itens))
            return compra_id
            
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("Erro durante inserção da compra. Transação desfeita (Rollback): %s", e)
            raise
        finally:
            conn.close()