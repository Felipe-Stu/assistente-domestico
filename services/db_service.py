import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from core.config import DB_PATH
from services import estoque_service
from services.dinheiro import para_centavos, para_reais
from services.produtos_service import TABELA_PRODUTOS, resolver_produto
from services.logger_service import logger as custom_logger

# Logger do console (terminal)
logging_logger = logging.getLogger(__name__)

NOME_ASSISTENTE = "db_service"


class _ConexaoQueFecha(sqlite3.Connection):
    """
    Conexão que, além de confirmar (ou desfazer) a transação ao sair do `with`,
    também é fechada. O sqlite3 padrão só confirma e deixa a conexão aberta (P22).
    """

    def __exit__(self, tipo, valor, rastro):
        try:
            return super().__exit__(tipo, valor, rastro)
        finally:
            self.close()

# M09: origem de cada registro. Uma linha por pedido de compra extraído pelo modelo, gravado ou não,
# com o texto original e a resposta do modelo: permite auditar, reprocessar e alimentar as avaliações (M13).
TABELA_ENTRADAS = """
CREATE TABLE IF NOT EXISTS entradas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    tipo TEXT NOT NULL,              -- 'compra' (outras skills podem usar depois)
    canal TEXT NOT NULL,             -- 'chat', 'voz' ou 'telegram'
    texto TEXT NOT NULL,             -- o que a pessoa escreveu ou falou
    anexo TEXT,                      -- caminho de um arquivo enviado (futuro: PDF, imagem)
    resposta_json TEXT,              -- o que o modelo devolveu, antes da validação
    modelo TEXT,
    versao_prompt TEXT,              -- 8 primeiros caracteres do SHA-1 do prompt usado
    duracao_ms INTEGER,
    situacao TEXT NOT NULL           -- 'gravada', 'descartada' ou 'desfeita'
)
"""


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
            conn = sqlite3.connect(self.db_path, factory=_ConexaoQueFecha)
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
        SCHEMA_VERSION = 9

        query_compras = """
        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_compra TEXT NOT NULL,
            nome_comercio TEXT,
            total_gasto REAL NOT NULL
        );
        """

        query_hisorico = """
        CREATE TABLE IF NOT EXISTS historico_conversas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            papel TEXT NOT NULL, -- 'user', 'assistant' ou 'resumo' (M20)
            conteudo TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
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
            embalagem_quantidade REAL,
            embalagem_unidade TEXT,
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
                cursor.execute(query_hisorico)
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

                if atual_version < 2:
                    msg_migracao = "Aplicando migração v2: colunas de embalagem em itens_compra."
                    logging_logger.info(msg_migracao)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_migracao)

                    cursor.execute("PRAGMA table_info(itens_compra);")
                    colunas = [coluna[1] for coluna in cursor.fetchall()]

                    if "embalagem_quantidade" not in colunas:
                        cursor.execute("ALTER TABLE itens_compra ADD COLUMN embalagem_quantidade REAL;")
                    if "embalagem_unidade" not in colunas:
                        cursor.execute("ALTER TABLE itens_compra ADD COLUMN embalagem_unidade TEXT;")

                    cursor.execute("PRAGMA user_version = 2;")
                    atual_version = 2

                if atual_version < 3:
                    msg_migracao = "Aplicando migração v3 (M09): tabela 'entradas' e coluna compras.entrada_id."
                    logging_logger.info(msg_migracao)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_migracao)
                    cursor.execute(TABELA_ENTRADAS)
                    cursor.execute("PRAGMA table_info(compras);")
                    if "entrada_id" not in [coluna[1] for coluna in cursor.fetchall()]:
                        cursor.execute("ALTER TABLE compras ADD COLUMN entrada_id INTEGER REFERENCES entradas(id);")
                    cursor.execute("PRAGMA user_version = 3;")
                    atual_version = 3

                if atual_version < 4:
                    msg_migracao = "Aplicando migração v4 (M07): catálogo de produtos e itens_compra.produto_id."
                    logging_logger.info(msg_migracao)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_migracao)
                    cursor.execute(TABELA_PRODUTOS)
                    cursor.execute("PRAGMA table_info(itens_compra);")
                    if "produto_id" not in [coluna[1] for coluna in cursor.fetchall()]:
                        cursor.execute("ALTER TABLE itens_compra ADD COLUMN produto_id INTEGER REFERENCES produtos(id);")
                    # Itens já gravados entram no catálogo; o texto original de produto e categoria não muda
                    cursor.execute("SELECT id, produto, categoria, unidade FROM itens_compra WHERE produto_id IS NULL ORDER BY id")
                    for item_id, produto, categoria, unidade in cursor.fetchall():
                        produto_id = resolver_produto(cursor, produto, categoria, unidade, nome_primeiro=True)
                        cursor.execute("UPDATE itens_compra SET produto_id = ? WHERE id = ?", (produto_id, item_id))
                    cursor.execute("PRAGMA user_version = 4;")
                    atual_version = 4

                if atual_version < 5:
                    msg_migracao = "Aplicando migração v5 (M08): valores em centavos inteiros."
                    logging_logger.info(msg_migracao)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_migracao)
                    novas = {"compras": ["total_centavos"], "itens_compra": ["valor_unitario_centavos", "valor_total_centavos"]}
                    for tabela, colunas in novas.items():
                        cursor.execute(f"PRAGMA table_info({tabela});")
                        existentes = [coluna[1] for coluna in cursor.fetchall()]
                        for coluna in colunas:
                            if coluna not in existentes:
                                cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} INTEGER;")
                    # As colunas REAL antigas ficam como estão; as novas recebem a conversão (meio centavo para cima)
                    cursor.execute("SELECT id, total_gasto FROM compras")
                    for compra_id, total in cursor.fetchall():
                        cursor.execute("UPDATE compras SET total_centavos = ? WHERE id = ?", (para_centavos(total), compra_id))
                    cursor.execute("SELECT id, valor_unitario, valor_total FROM itens_compra")
                    for item_id, unitario, total in cursor.fetchall():
                        cursor.execute("UPDATE itens_compra SET valor_unitario_centavos = ?, valor_total_centavos = ? WHERE id = ?",
                                       (para_centavos(unitario), para_centavos(total), item_id))
                    cursor.execute("PRAGMA user_version = 5;")
                    atual_version = 5

                if atual_version < 6:
                    msg_migracao = "Aplicando migração v6 (M06): controle_consumo ligado ao catálogo (produto_id, unidade)."
                    logging_logger.info(msg_migracao)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_migracao)
                    cursor.execute("PRAGMA table_info(controle_consumo);")
                    existentes = [coluna[1] for coluna in cursor.fetchall()]
                    if "produto_id" not in existentes:
                        cursor.execute("ALTER TABLE controle_consumo ADD COLUMN produto_id INTEGER REFERENCES produtos(id);")
                    if "unidade" not in existentes:
                        cursor.execute("ALTER TABLE controle_consumo ADD COLUMN unidade TEXT;")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_consumo_produto ON controle_consumo (produto_id);")
                    # Sem preencher com compras antigas: sem ritmo conhecido, elas apareceriam como estoque cheio
                    cursor.execute("PRAGMA user_version = 6;")
                    atual_version = 6

                if atual_version < 7:
                    msg_migracao = "Aplicando migração v7: chave do documento (nota fiscal) nas entradas."
                    logging_logger.info(msg_migracao)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_migracao)
                    cursor.execute("PRAGMA table_info(entradas);")
                    if "chave_documento" not in [coluna[1] for coluna in cursor.fetchall()]:
                        cursor.execute("ALTER TABLE entradas ADD COLUMN chave_documento TEXT;")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entradas_chave ON entradas (chave_documento);")
                    cursor.execute("PRAGMA user_version = 7;")
                    atual_version = 7

                if atual_version < 8:
                    msg_migracao = "Aplicando migração v8 (M20): contexto no histórico das conversas."
                    logging_logger.info(msg_migracao)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_migracao)
                    cursor.execute("PRAGMA table_info(historico_conversas);")
                    if "contexto" not in [coluna[1] for coluna in cursor.fetchall()]:
                        cursor.execute("ALTER TABLE historico_conversas ADD COLUMN contexto TEXT;")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_historico_sessao ON historico_conversas (session_id, id);")
                    cursor.execute("PRAGMA user_version = 8;")
                    atual_version = 8

                if atual_version < 9:
                    msg_migracao = "Aplicando migração v9: observações em compras e itens."
                    logging_logger.info(msg_migracao)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_migracao)
                    for tabela in ("compras", "itens_compra"):
                        cursor.execute(f"PRAGMA table_info({tabela});")
                        if "observacao" not in [coluna[1] for coluna in cursor.fetchall()]:
                            cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN observacao TEXT;")
                    cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")
                    atual_version = SCHEMA_VERSION

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

    @staticmethod
    def _inserir_entrada(cursor: sqlite3.Cursor, entrada: Dict[str, Any], situacao: str) -> int:
        cursor.execute(
            """
            INSERT INTO entradas (criado_em, tipo, canal, texto, anexo, resposta_json, modelo, versao_prompt, duracao_ms,
                                  situacao, chave_documento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entrada.get("criado_em") or datetime.now().isoformat(timespec="seconds"),
                entrada.get("tipo", "compra"), entrada.get("canal", "chat"), entrada.get("texto", ""),
                entrada.get("anexo"), entrada.get("resposta_json"), entrada.get("modelo"),
                entrada.get("versao_prompt"), entrada.get("duracao_ms"), situacao, entrada.get("chave_documento"),
            ),
        )
        return cursor.lastrowid

    def documento_ja_gravado(self, chave: str) -> bool:
        """Nota com esta chave de acesso já registrada (e não desfeita)."""
        if not chave:
            return False
        return bool(self.executar_consulta_uma_linha(
            "SELECT 1 FROM entradas WHERE chave_documento = ? AND situacao = 'gravada'", (chave,)))

    def registrar_entrada(self, entrada: Dict[str, Any], situacao: str) -> int:
        """Registra uma entrada sem compra gravada (ex.: compra descartada pelo usuário)."""
        with self.get_connection() as conn:
            entrada_id = self._inserir_entrada(conn.cursor(), entrada, situacao)
            conn.commit()
        return entrada_id

    def _inserir_compra(self, cursor: sqlite3.Cursor, dados_ia: Dict[str, Any], entrada_id: Optional[int] = None) -> int:
        """Insere uma compra e seus itens na transação do cursor recebido."""
        # Extração de cabeçalho da compra com fallbacks de chave
        data_compra = dados_ia.get("data_compra") or dados_ia.get("data")
        nome_comercio = dados_ia.get("estabelecimento") or dados_ia.get("nome_comercio") or "Não Identificado"
        total_gasto = float(dados_ia.get("valor_total_compra") or dados_ia.get("total_gasto") or 0.0)

        cursor.execute(
            """
            INSERT INTO compras (data_compra, nome_comercio, total_gasto, total_centavos, entrada_id, observacao)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (data_compra, nome_comercio, total_gasto, para_centavos(total_gasto), entrada_id,
             (dados_ia.get("observacao") or None))
        )
        compra_id = cursor.lastrowid

        for item in dados_ia.get("itens", []):
            # Normalização e resolução de assincronia entre JSON da IA e a DDL da tabela
            produto_nome = item.get("produto") or item.get("nome") or "Produto Indefinido"
            marca = item.get("marca") or ""
            quantidade = float(item.get("quantidade") or item.get("qtd") or 1.0)
            unidade = item.get("unidade") or item.get("unidade_medida") or "UN"
            valor_unitario = float(item.get("valor_unitario") or item.get("preco_unitario") or 0.0)
            valor_total = float(item.get("valor_total") or item.get("preco_total") or (quantidade * valor_unitario))
            categoria = item.get("categoria") or "outros"
            produto_id = resolver_produto(cursor, produto_nome, categoria, unidade)

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
                    categoria,
                    embalagem_quantidade,
                    embalagem_unidade,
                    produto_id,
                    valor_unitario_centavos,
                    valor_total_centavos,
                    observacao
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    compra_id,
                    produto_nome,
                    marca,
                    quantidade,
                    unidade,
                    valor_unitario,
                    valor_total,
                    categoria,
                    item.get("embalagem_quantidade"),
                    item.get("embalagem_unidade"),
                    produto_id,
                    para_centavos(valor_unitario),
                    para_centavos(valor_total),
                    item.get("observacao") or None,
                )
            )
            # M06: a compra alimenta o estoque do produto, na mesma transação
            qtd_base, unidade_base = estoque_service.quantidade_base(
                quantidade, unidade, item.get("embalagem_quantidade"), item.get("embalagem_unidade"))
            cursor.execute("SELECT categoria FROM produtos WHERE id = ?", (produto_id,))
            linha_produto = cursor.fetchone()
            estoque_service.registrar_entrada(cursor, produto_id, produto_nome, linha_produto[0] if linha_produto else categoria,
                                              qtd_base, unidade_base, data_compra)

        return compra_id

    def salvar_compras_da_ia(self, compras: List[Dict[str, Any]], entrada: Optional[Dict[str, Any]] = None) -> List[int]:
        """
        Grava todas as compras em uma única transação: ou todas são salvas, ou nenhuma.
        Com `entrada` (M09), a origem é gravada na mesma transação e ligada a cada compra.

        :param compras: Lista de compras validadas
        :return: IDs das compras geradas, na mesma ordem
        """
        conn = self.get_connection()
        try:
            with custom_logger.etapa("banco", componente=NOME_ASSISTENTE, operacao="gravar_compras", compras=len(compras)):
                cursor = conn.cursor()
                entrada_id = self._inserir_entrada(cursor, entrada, "gravada") if entrada else None
                ids = [self._inserir_compra(cursor, compra, entrada_id) for compra in compras]
                conn.commit()

            total_itens = sum(len(compra.get("itens", [])) for compra in compras)
            msg_gravar = f"Procedimentos feitos: Compras {ids} e {total_itens} itens gravados no banco de dados SQLite."
            logging_logger.info(msg_gravar)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_gravar)
            return ids

        except (sqlite3.Error, ValueError, TypeError) as e:
            conn.rollback()
            msg_rollback = f"Erro durante inserção da compra. Transação desfeita (Rollback): {e}"
            logging_logger.error(msg_rollback)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_rollback)
            raise
        finally:
            conn.close()

    def salvar_compra_da_ia(self, dados_ia: Dict[str, Any]) -> int:
        """
        Recebe o JSON extraído pela IA e faz a inserção relacional da compra e dos itens.

        :param dados_ia: Dicionário retornado pelo serviço de IA
        :return: ID da compra gerada
        """
        return self.salvar_compras_da_ia([dados_ia])[0]

    def remover_compras(self, compra_ids: List[int]) -> List[int]:
        """
        Remove as compras informadas e seus itens em uma única transação.

        :return: IDs dos itens removidos
        """
        if not compra_ids:
            return []

        marcadores = ", ".join("?" for _ in compra_ids)
        conn = self.get_connection()
        try:
            with custom_logger.etapa("banco", componente=NOME_ASSISTENTE, operacao="remover_compras", compras=len(compra_ids)):
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT id, produto_id, quantidade, unidade, embalagem_quantidade, embalagem_unidade "
                    f"FROM itens_compra WHERE compra_id IN ({marcadores})", tuple(compra_ids))
                itens = cursor.fetchall()
                itens_ids = [linha[0] for linha in itens]
                # M06: o estoque perde o que estas compras tinham somado
                for _, produto_id, quantidade, unidade, emb_qtd, emb_unid in itens:
                    estoque_service.reverter_entrada(cursor, produto_id,
                                                     estoque_service.quantidade_base(quantidade, unidade, emb_qtd, emb_unid)[0])
                # A origem fica, marcada como desfeita (M09): o histórico do que foi pedido não se perde
                cursor.execute(
                    f"UPDATE entradas SET situacao = 'desfeita' WHERE id IN "
                    f"(SELECT entrada_id FROM compras WHERE id IN ({marcadores}) AND entrada_id IS NOT NULL)",
                    tuple(compra_ids),
                )
                cursor.execute(f"DELETE FROM compras WHERE id IN ({marcadores})", tuple(compra_ids))
                conn.commit()
            custom_logger.log_assistente(NOME_ASSISTENTE, f"Compras {compra_ids} removidas ({len(itens_ids)} itens).")
            return itens_ids

        except sqlite3.Error as e:
            conn.rollback()
            msg_erro = f"Erro ao remover compras. Transação desfeita (Rollback): {e}"
            logging_logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)
            raise
        finally:
            conn.close()

    def obter_compra(self, compra_id: int) -> Optional[Dict[str, Any]]:
        """Compra com itens, no formato usado no resumo (valores em reais)."""
        cabecalho = self.executar_consulta_uma_linha(
            "SELECT id, data_compra, nome_comercio, COALESCE(total_centavos, CAST(ROUND(total_gasto * 100) AS INTEGER)), "
            "observacao FROM compras WHERE id = ?", (compra_id,))
        if not cabecalho:
            return None
        itens = self.executar_consulta(
            "SELECT id, produto, marca, quantidade, unidade, "
            "COALESCE(valor_unitario_centavos, CAST(ROUND(valor_unitario * 100) AS INTEGER)), "
            "COALESCE(valor_total_centavos, CAST(ROUND(valor_total * 100) AS INTEGER)), categoria, "
            "embalagem_quantidade, embalagem_unidade, observacao FROM itens_compra WHERE compra_id = ? ORDER BY id", (compra_id,))
        return {
            "id": cabecalho[0], "data_compra": cabecalho[1], "estabelecimento": cabecalho[2],
            "valor_total_compra": para_reais(cabecalho[3]), "observacao": cabecalho[4],
            "itens": [{"id": i[0], "produto": i[1], "marca": i[2], "quantidade": i[3], "unidade": i[4],
                       "valor_unitario": para_reais(i[5]), "valor_total": para_reais(i[6]), "categoria": i[7],
                       "embalagem_quantidade": i[8], "embalagem_unidade": i[9], "observacao": i[10]} for i in itens],
        }

    def editar_compra(self, compra_id: int, nova: Dict[str, Any], entrada: Optional[Dict[str, Any]] = None) -> None:
        """M10: grava a versão corrigida de uma compra (cabeçalho e itens) numa transação.

        `nova` vem de obter_compra() com as alterações aplicadas; item com "remover": True é apagado.
        O estoque perde o que os itens antigos tinham somado e recebe os novos; o total é refeito pela soma dos itens.
        A entrada (M09) registra o pedido de correção, com a compra antes e depois.
        """
        conn = self.get_connection()
        try:
            with custom_logger.etapa("banco", componente=NOME_ASSISTENTE, operacao="editar_compra", compra=compra_id):
                cursor = conn.cursor()
                cursor.execute("SELECT id, produto_id, quantidade, unidade, embalagem_quantidade, embalagem_unidade "
                               "FROM itens_compra WHERE compra_id = ?", (compra_id,))
                antigos = {linha[0]: linha for linha in cursor.fetchall()}
                data = nova["data_compra"]
                total = 0
                for item in nova["itens"]:
                    antigo = antigos.get(item.get("id"))
                    if antigo is None:
                        raise ValueError(f"Item {item.get('id')} não pertence à compra {compra_id}.")
                    _, produto_antigo, qtd, un, emb_qtd, emb_un = antigo
                    estoque_service.reverter_entrada(cursor, produto_antigo,
                                                     estoque_service.quantidade_base(qtd, un, emb_qtd, emb_un)[0])
                    if item.get("remover"):
                        cursor.execute("DELETE FROM itens_compra WHERE id = ?", (item["id"],))
                        continue
                    produto_id = resolver_produto(cursor, item["produto"], item.get("categoria") or "outros", item.get("unidade"))
                    cursor.execute("SELECT categoria FROM produtos WHERE id = ?", (produto_id,))
                    linha = cursor.fetchone()
                    categoria = linha[0] if linha else (item.get("categoria") or "outros")
                    unitario_c, total_c = para_centavos(item["valor_unitario"]), para_centavos(item["valor_total"])
                    cursor.execute(
                        "UPDATE itens_compra SET produto = ?, quantidade = ?, unidade = ?, valor_unitario = ?, valor_total = ?, "
                        "categoria = ?, produto_id = ?, valor_unitario_centavos = ?, valor_total_centavos = ?, observacao = ? "
                        "WHERE id = ?",
                        (item["produto"], item["quantidade"], item.get("unidade") or "un", para_reais(unitario_c),
                         para_reais(total_c), categoria, produto_id, unitario_c, total_c, item.get("observacao") or None, item["id"]))
                    total += total_c
                    qtd_base, un_base = estoque_service.quantidade_base(item["quantidade"], item.get("unidade"),
                                                                        item.get("embalagem_quantidade"), item.get("embalagem_unidade"))
                    estoque_service.registrar_entrada(cursor, produto_id, item["produto"], categoria, qtd_base, un_base, data)
                cursor.execute("UPDATE compras SET data_compra = ?, nome_comercio = ?, total_gasto = ?, total_centavos = ?, "
                               "observacao = ? WHERE id = ?",
                               (data, nova["estabelecimento"], para_reais(total), total, nova.get("observacao") or None, compra_id))
                if entrada:
                    self._inserir_entrada(cursor, entrada, "gravada")
                conn.commit()
            custom_logger.log_assistente(NOME_ASSISTENTE, f"Compra {compra_id} corrigida.")
        except (sqlite3.Error, ValueError, KeyError) as e:
            conn.rollback()
            logging_logger.error(f"Erro ao corrigir a compra {compra_id}. Transação desfeita (Rollback): {e}")
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