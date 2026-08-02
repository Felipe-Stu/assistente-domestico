import sqlite3
import logging
from typing import Dict, List, Any, Optional
from core.config import DB_PATH
from services.logger_service import logger as custom_logger

# Logger do console (terminal)
logging_logger = logging.getLogger(__name__)

NOME_ASSISTENTE = "db_service"

class DatabaseService:
    """
    Serviço responsável por gerenciar a conexão com o banco de dados SQLite,
    inicialização de tabelas e persistência de dados de compras, itens e controle de consumo.
    """

    def __init__(self):
        self.db_path = DB_PATH
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Inicialização do DatabaseService (DB Path: {self.db_path}).")
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
            msg_erro = f"Erro ao conectar ao banco de dados: {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)
            raise

    def initialize_database(self):
        """
        Cria a estrutura inicial do banco de dados se não existir
        e aplica migrações de schema ordenadas via PRAGMA user_version.
        """
        # Versão alvo atual da aplicação
        SCHEMA_VERSION = 1

        query_compras = """
        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_compra TEXT NOT NULL,
            nome_comercio TEXT,
            total_gasto REAL NOT NULL
        );
        """

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

        query_controle_consumo = """
        CREATE TABLE IF NOT EXISTS controle_consumo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_nome TEXT UNIQUE NOT NULL,
            categoria TEXT,
            tempo_medio_calculado REAL NOT NULL,
            data_ultima_compra TEXT NOT NULL,
            quantidade_comprada REAL NOT NULL,
            quantidade_residual_confirmada REAL DEFAULT 0,
            status_estoque INTEGER DEFAULT 1,
            validacao_pendente INTEGER DEFAULT 0,
            ultima_qtd_comprada REAL DEFAULT 0,
            quantidade_residual_esgotada REAL DEFAULT 0
        );
        """

        query_indice_estoque = """
        CREATE INDEX IF NOT EXISTS idx_estoque_ativo 
        ON controle_consumo (status_estoque, data_ultima_compra);
        """

        query_indice_nome = """
        CREATE INDEX IF NOT EXISTS idx_produto_nome 
        ON controle_consumo (produto_nome);
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 1. Cria a estrutura base do banco (DDL idempotente)
                cursor.execute(query_compras)
                cursor.execute(query_itens)
                cursor.execute(query_controle_consumo)
                cursor.execute(query_indice_estoque)
                cursor.execute(query_indice_nome)

                # 2. Verifica a versão atual do schema
                cursor.execute("PRAGMA user_version;")
                atual_version = cursor.fetchone()[0]

                # 3. Executa migrações incrementais se necessário
                if atual_version < 1:
                    msg_migracao = "Aplicando migração v1: garantindo coluna 'categoria' em controle_consumo."
                    logging_logger.info(msg_migracao)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_migracao)
                    
                    # Verifica se a coluna já existe antes de tentar alteração
                    cursor.execute("PRAGMA table_info(controle_consumo);")
                    colunas = [coluna[1] for coluna in cursor.fetchall()]
                    
                    if "categoria" not in colunas:
                        cursor.execute("ALTER TABLE controle_consumo ADD COLUMN categoria TEXT;")

                    # Atualiza o ponteiro de versão do banco
                    cursor.execute("PRAGMA user_version = 1;")
                    atual_version = 1

                conn.commit()
            
            msg_sucesso_init = f"Banco de dados SQLite inicializado/migrado na versão v{atual_version}."
            logging_logger.info(msg_sucesso_init)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_sucesso_init)
        except sqlite3.Error as e:
            msg_erro_init = f"Falha ao inicializar/migrar tabelas do banco de dados: {e}"
            logging_logger.error(msg_erro_init)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro_init)
            raise

    # =========================================================================
    # MÉTODOS DE EXECUÇÃO GENÉRICOS (AERODINÂMICOS)
    # =========================================================================

    def executar_comando(self, query: str, params: tuple = ()) -> None:
        """Executa comandos de alteração na base de dados (INSERT, UPDATE, DELETE)."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                custom_logger.log_assistente(NOME_ASSISTENTE, f"Comando SQL executado com sucesso: {query.strip().split()[0]}")
        except sqlite3.Error as e:
            msg_erro = f"Erro ao executar comando de escrita no SQLite: {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)
            raise

    def executar_consulta(self, query: str, params: tuple = ()) -> List[tuple]:
        """Executa uma consulta SQL e retorna uma lista contendo todas as tuplas encontradas."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                resultados = cursor.fetchall()
                custom_logger.log_assistente(NOME_ASSISTENTE, f"Consulta SQL executada ({len(resultados)} registros retornados).")
                return resultados
        except sqlite3.Error as e:
            msg_erro = f"Erro ao executar consulta (múltiplas linhas) no SQLite: {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)
            return []

    def executar_consulta_uma_linha(self, query: str, params: tuple = ()) -> Optional[tuple]:
        """Executa uma consulta SQL e retorna apenas o primeiro resultado encontrado ou None."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                resultado = cursor.fetchone()
                custom_logger.log_assistente(NOME_ASSISTENTE, f"Consulta de linha única executada (Encontrado: {resultado is not None}).")
                return resultado
        except sqlite3.Error as e:
            msg_erro = f"Erro ao executar consulta (linha única) no SQLite: {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)
            return None

    # =========================================================================
    # PERSISTÊNCIA DE COMPRAS
    # =========================================================================

    def salvar_compra_da_ia(self, dados_ia: Dict[str, Any]) -> int:
        """
        Recebe o JSON extraído pelo Gemini e faz a inserção relacional das compras e itens.
        Garante tratamento de fallback para chaves sinônimas e tipos numéricos.
        
        :param dados_ia: Dicionário retornado pelo serviço de IA
        :return: ID da compra gerada
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            # Extração de cabeçalho da compra com fallbacks de chave
            data_compra = dados_ia.get("data_compra") or dados_ia.get("data")
            nome_comercio = dados_ia.get("estabelecimento") or dados_ia.get("nome_comercio") or "Não Identificado"
            total_gasto = float(dados_ia.get("valor_total_compra") or dados_ia.get("total_gasto") or 0.0)

            cursor.execute(
                """
                INSERT INTO compras (data_compra, nome_comercio, total_gasto)
                VALUES (?, ?, ?)
                """,
                (data_compra, nome_comercio, total_gasto)
            )
            compra_id = cursor.lastrowid

            itens = dados_ia.get("itens", [])

            for item in itens:
                # Normalização e resolução de assincronia entre JSON da IA e a DDL da tabela
                produto_nome = item.get("produto") or item.get("nome") or "Produto Indefinido"
                marca = item.get("marca") or ""
                quantidade = float(item.get("quantidade") or item.get("qtd") or 1.0)
                unidade = item.get("unidade") or item.get("unidade_medida") or "UN"
                valor_unitario = float(item.get("valor_unitario") or item.get("preco_unitario") or 0.0)
                valor_total = float(item.get("valor_total") or item.get("preco_total") or (quantidade * valor_unitario))
                categoria = item.get("categoria") or "Geral"

                cursor.execute(
                    """
                    INSERT INTO itens_compra (
                        compra_id, 
                        produto, 
                        marca, 
                        quantidade, 
                        unidade, 
                        valor_unitario, 
                        valor_total, 
                        categoria
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        compra_id,
                        produto_nome,
                        marca,
                        quantidade,
                        unidade,
                        valor_unitario,
                        valor_total,
                        categoria
                    )
                )

            conn.commit()
            msg_gravar = f"Procedimentos feitos: Compra (ID: {compra_id}) e {len(itens)} itens gravados no banco de dados SQLite."
            logging_logger.info("Compra (ID: %d) e %d itens gravados com sucesso via IA.", compra_id, len(itens))
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_gravar)
            return compra_id

        except sqlite3.Error as e:
            conn.rollback()
            msg_rollback = f"Erro durante inserção da compra. Transação desfeita (Rollback): {e}"
            logging_logger.error(msg_rollback)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_rollback)
            raise
        finally:
            conn.close()

    # =========================================================================
    # MÉTODOS ESPECÍFICOS DE CONTROLE DE CONSUMO E ESTOQUE (V2)
    # =========================================================================

    def obter_itens_expirados_para_validacao(self) -> List[tuple]:
        """
        Calcula no próprio SQLite os itens cujo tempo decorrido desde a última compra
        ultrapassou o tempo médio calculado/estimado de consumo.
        
        Retorna: Lista de tuplas contendo
        (id, produto_nome, quantidade_comprada, quantidade_residual_confirmada, tempo_medio_calculado, data_ultima_compra, dias_decorridos)
        """
        query = """
        SELECT 
            id,
            produto_nome,
            quantidade_comprada,
            quantidade_residual_confirmada,
            tempo_medio_calculado,
            data_ultima_compra,
            CAST(
                (julianday('now', 'localtime') - julianday(data_ultima_compra)) AS REAL
            ) AS dias_decorridos
        FROM controle_consumo
        WHERE status_estoque = 1
          AND (julianday('now', 'localtime') - julianday(data_ultima_compra)) >= tempo_medio_calculado;
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, "Buscando itens expirados para validação...")
        return self.executar_consulta(query)

    def obter_dados_produto_por_nome(self, produto_nome: str) -> Optional[tuple]:
        """
        Busca o estado atual do controle de consumo de um produto pelo nome.
        
        Retorna: (id, quantidade_comprada, quantidade_residual_confirmada, tempo_medio_calculado, data_ultima_compra)
        """
        query = """
        SELECT id, quantidade_comprada, quantidade_residual_confirmada, tempo_medio_calculado, data_ultima_compra
        FROM controle_consumo
        WHERE produto_nome = ? AND status_estoque = 1;
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Buscando dados do produto: '{produto_nome}'")
        return self.executar_consulta_uma_linha(query, (produto_nome,))

    def atualizar_recompra_e_ritmo(
        self, 
        item_id: int, 
        nova_qtd_comprada: float, 
        residuos_reais: float, 
        consumo_real: float, 
        dias_decorridos: float
    ) -> None:
        """
        Aplica o recálculo do ritmo dinâmico de consumo (tempo_medio_calculado) 
        e atualiza o estoque residual total com a nova compra.
        """
        query = """
        UPDATE controle_consumo
        SET 
            quantidade_comprada = ?,
            quantidade_residual_confirmada = ? + ?,
            tempo_medio_calculado = CASE 
                WHEN ? > 0 THEN ? / ?
                ELSE tempo_medio_calculado
            END,
            data_ultima_compra = date('now', 'localtime'),
            status_estoque = 1,
            validacao_pendente = 0
        WHERE id = ?;
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Atualizando recompra e ritmo do item ID {item_id}.")
        self.executar_comando(
            query, 
            (
                nova_qtd_comprada,          # 1
                residuos_reais,             # 2
                nova_qtd_comprada,          # 3
                consumo_real,               # 4 (condição CASE)
                dias_decorridos,            # 5 (numerador da divisão)
                consumo_real,               # 6 (denominador da divisão)
                item_id                     # 7 (WHERE id)
            )
        )

    def zerar_estoque_item(self, item_id: int) -> None:
        """Marca o produto como totalmente consumido/esgotado no banco de dados."""
        query = """
        UPDATE controle_consumo
        SET 
            quantidade_residual_confirmada = 0.0,
            status_estoque = 0,
            validacao_pendente = 0
        WHERE id = ?;
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Zerando estoque do item ID {item_id}.")
        self.executar_comando(query, (item_id,))

    def zerar_estoque_por_nome(self, produto_nome: str) -> None:
        """
        Marca o produto como totalmente consumido/esgotado diretamente pelo nome.
        Utilizado principalmente quando a intenção NEGATIVA_ZERADO é capturada via IA.
        """
        query = """
        UPDATE controle_consumo
        SET 
            quantidade_residual_confirmada = 0.0,
            status_estoque = 0,
            validacao_pendente = 0
        WHERE produto_nome = ? AND status_estoque = 1;
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Zerando estoque do produto por nome: '{produto_nome}'.")
        self.executar_comando(query, (produto_nome,))

    def marcar_validacao_pendente(self, item_id: int) -> None:
        """
        Sinaliza que o item foi identificado como expirado e aguarda
        confirmação ativa do usuário via voz ou texto.
        """
        query = """
        UPDATE controle_consumo
        SET validacao_pendente = 1
        WHERE id = ?;
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Sinalizando validação pendente para o item ID {item_id}.")
        self.executar_comando(query, (item_id,))