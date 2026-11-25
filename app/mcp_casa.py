"""
I05: servidor MCP somente leitura com as consultas da casa, para o Claude (Claude Code ou Claude Desktop) usar.

DESLIGADO POR PADRÃO. Ele só funciona se você o registrar no Claude, por exemplo:
    claude mcp add assistente-casa -- python "E:\\Agente IA\\assistente-domestico\\app\\mcp_casa.py"

Atenção: o que estas ferramentas devolvem vai para o Claude (nuvem da Anthropic). A regra do projeto é que
compras e estoque não saem do PC; registrar este servidor é abrir uma exceção consciente, só para as
respostas das consultas (totais, listas, preços). Nada é gravado nem alterado por aqui.

As funções de consulta são comuns (testáveis sem o pacote mcp); criar_servidor() só as registra.
"""
import sys
from pathlib import Path
from typing import Optional

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

_db = None


def _banco():
    global _db
    if _db is None:
        from services.db_service import DatabaseService
        _db = DatabaseService()
    return _db


def _filtro(periodo: str = "", categoria: str = "", loja: str = "", produto: str = ""):
    from services.consultas_service import Filtro
    from services.periodos import primeiro_periodo
    from services.produtos_service import normalizar_categoria
    cat = normalizar_categoria(categoria) if categoria else None
    return Filtro(periodo=primeiro_periodo(periodo) if periodo else None,
                  categoria=None if cat == "outros" and categoria.lower() != "outros" else cat,
                  loja=loja or None, produto=produto or None)


def _consultas():
    from services.consultas_service import ConsultasGastos
    return ConsultasGastos(_banco())


def total_de_gastos(periodo: str = "", categoria: str = "", loja: str = "") -> str:
    """Quanto foi gasto. periodo em português ("novembro", "mês passado", "2026", "de 01/10 a 15/11"); vazio = tudo."""
    return _consultas().total(_filtro(periodo, categoria, loja)).texto


def listar_compras(periodo: str = "", loja: str = "", categoria: str = "") -> str:
    """As compras mais recentes do período (até 10), com data, loja, valor e observação."""
    return _consultas().listar(_filtro(periodo, categoria, loja)).texto


def gastos_por_categoria(periodo: str = "", loja: str = "") -> str:
    """Gastos divididos por categoria no período."""
    return _consultas().por_categoria(_filtro(periodo, loja=loja)).texto


def gastos_por_loja(periodo: str = "", categoria: str = "") -> str:
    """Gastos divididos por loja no período."""
    return _consultas().por_loja(_filtro(periodo, categoria)).texto


def preco_de_produto(produto: str, periodo: str = "") -> str:
    """Último preço, menor preço, média e onde um produto foi comprado."""
    return _consultas().preco_produto(_filtro(periodo, produto=produto)).texto


def comparar_periodos(periodo1: str, periodo2: str, categoria: str = "", loja: str = "") -> str:
    """Compara o gasto de dois períodos (ex.: "outubro" e "novembro")."""
    from services.periodos import primeiro_periodo
    periodos = [p for p in (primeiro_periodo(periodo1), primeiro_periodo(periodo2)) if p]
    return _consultas().comparar(_filtro(categoria=categoria, loja=loja), periodos).texto


FERRAMENTAS = (total_de_gastos, listar_compras, gastos_por_categoria, gastos_por_loja, preco_de_produto, comparar_periodos)


def criar_servidor(nome: str = "assistente-casa"):
    try:   # mcp 2.x
        from mcp.server.mcpserver import MCPServer as Servidor
    except ImportError:   # mcp 1.x
        from mcp.server.fastmcp import FastMCP as Servidor
    servidor = Servidor(nome, instructions="Consultas somente leitura das compras da casa (valores em reais).")
    for funcao in FERRAMENTAS:
        servidor.tool()(funcao)
    return servidor


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)   # a saída padrão é do protocolo MCP
    criar_servidor().run("stdio")
