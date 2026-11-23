"""
Roteador por regras: encaminha frases conhecidas sem chamar o LLM.
Frases ambíguas retornam None e seguem para a classificação do orquestrador.

As expressões regulares ficam nos gatilhos de cada skill (skills/<nome>/SKILL.md);
este módulo só normaliza o texto e aplica o primeiro gatilho que casar.
"""
import re
import unicodedata
from typing import Any, Dict, Optional

from core.skills import obter_catalogo


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços simples."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acentos).lower().strip()


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

    # Gatilhos declarados nos cabeçalhos das skills (skills/<nome>/SKILL.md), em ordem de prioridade
    gatilho = obter_catalogo().primeiro_gatilho(t)
    if gatilho is None:
        return None
    skill = obter_catalogo().skill(gatilho.skill)
    return _decisao(skill.contexto, gatilho.acao, contexto_atual, dict(gatilho.parametros) or None)
