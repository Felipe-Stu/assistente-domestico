"""
Roteador por regras: encaminha frases conhecidas sem chamar o LLM.
Frases ambíguas retornam None e seguem para a classificação do orquestrador.
"""
import re
import unicodedata
from typing import Any, Dict, Optional


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços simples."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acentos).lower().strip()


_RE_DESFAZER_COMPRA = re.compile(
    r"\b(?:desfazer|desfaca|cancelar|cancele|apagar|apague|remover|remova|excluir|exclua)\s+"
    r"(?:a\s+|minha\s+)?(?:ultima\s+compra|compra\s+anterior)\b"
)

_RE_CONSULTA_COMPRAS = re.compile(
    r"\bquanto\s+(?:eu\s+)?(?:gastei|paguei|gastamos|pagamos)\b"
    r"|\bo que\s+(?:eu\s+)?(?:tenho\s+|ando\s+|andei\s+)?(?:comprei|comprado|comprando)\b"
    r"|\b(?:onde|quando)\s+(?:eu\s+)?comprei\b"
    r"|\bmeus gastos\b|\bgastos\s+(?:de|do|da|com|no|na)\b"
    r"|\bultimas?\s+compras?\b"
    r"|\b(?:o que|quais\b.{0,30})\s*(?:eu\s+)?(?:preciso|tenho que|devo)\s+comprar\b"
    r"|\blista de compras\b"
)
_RE_CONSULTA_PRECO = re.compile(r"\bmais barat[oa]s?\b|\bqual\s+(?:e\s+|foi\s+)?o preco\b")

_RE_REGISTRO_COMPRA = re.compile(
    r"\b(?:comprei|compramos|paguei)\b"
    r"|\b(?:registre|registrar|registra|anote|anotar|anota)\s+(?:uma\s+|a\s+)?compra\b"
)

_RE_CONSULTA_ESTOQUE = re.compile(
    r"\bainda\s+(?:tenho|temos)\b"
    r"|\b(?:tenho|temos)\b.{1,40}\bem casa\b"
    r"|\b(?:meu|nosso|o)\s+estoque\b|\bem estoque\b"
)
_RE_BAIXA_ESTOQUE = re.compile(
    r"^(?:ja\s+)?(?:acabou|acabaram|terminou|terminaram)\s+(?:o|a|os|as|meu|minha|meus|minhas|todo|toda)\b"
    r"|^(?:o|a|os|as|meu|minha|meus|minhas)\s+[\w-]+(?:\s+[\w-]+)?\s+(?:ja\s+)?(?:acabou|acabaram|terminou|terminaram)[.!]?$"
)

_RE_CRIAR_AGENDA = re.compile(
    r"\bme lembr[ae]\b|\blembrete\b|\bagend(?:e|a|ar)\b"
    r"|\bmarc(?:a|ar|e)\s+(?:um\s+|uma\s+)?(?:consulta|reuniao|compromisso|horario)\b"
)
_RE_CONSULTAR_AGENDA = re.compile(r"\bminha agenda\b|\bmeus compromissos\b")

_RE_DOCUMENTACAO = re.compile(
    r"\b(?:escrev\w*|redij\w*|faca|fazer|cri\w*|ger\w*|atualiz\w*|prepar\w*)\b.{0,40}\bdocumentacao\b"
    r"|\b(?:documentar|documente)\b"
)


def _decisao(contexto: str, acao: str, contexto_atual: Optional[str],
             parametros: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    decisao: Dict[str, Any] = {
        "dificuldade": "facil",
        "mudanca_de_contexto": bool(contexto_atual) and contexto_atual != contexto,
        "contexto": contexto,
        "acao": acao,
    }
    if parametros:
        decisao["parametros"] = parametros
    return decisao


def rotear_por_regras(texto: str, contexto_atual: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retorna uma decisão no formato do orquestrador ou None quando a frase é ambígua."""
    t = normalizar_texto(texto)
    if not t:
        return None

    if _RE_DESFAZER_COMPRA.search(t):
        return _decisao("compras", "corrigir", contexto_atual, {"operacao": "desfazer"})
    if _RE_CONSULTA_COMPRAS.search(t):
        return _decisao("compras", "consultar", contexto_atual)
    if _RE_REGISTRO_COMPRA.search(t) and "?" not in t:
        return _decisao("compras", "criar", contexto_atual)
    if _RE_CONSULTA_PRECO.search(t):
        return _decisao("compras", "consultar", contexto_atual)

    if _RE_BAIXA_ESTOQUE.search(t):
        return _decisao("inventario", "corrigir", contexto_atual)
    if _RE_CONSULTA_ESTOQUE.search(t):
        return _decisao("inventario", "consultar", contexto_atual)

    if _RE_CONSULTAR_AGENDA.search(t):
        return _decisao("agenda", "consultar", contexto_atual)
    if _RE_CRIAR_AGENDA.search(t):
        return _decisao("agenda", "criar", contexto_atual)

    if _RE_DOCUMENTACAO.search(t):
        return _decisao("projetos", "consultar", contexto_atual, {"caminho": None})

    return None
