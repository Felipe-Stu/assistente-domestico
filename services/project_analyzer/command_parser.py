"""
Detecção determinística do comando de análise (sem LLM), no mesmo padrão
dos comandos de chaveamento do Qwen em gemma_service.orquestrar_requisicao.

Exemplos aceitos:
  analisar projeto E:\\MOBA
  analise o projeto "E:\\Agente IA\\assistente-domestico"
  documentar o projeto /home/user/app
  gerar documentação do projeto E:\\MOBA
"""
import re
from typing import Dict, Optional

_RE_GATILHO = re.compile(
    r"\b(?:analis[ae]r?|analise|documentar|documente|ger[ae]r?\s+(?:a\s+)?documenta[çc][ãa]o)\s+"
    r"(?:d?[oa]s?\s+)?(?:projeto|pasta|diret[óo]rio|sistema)\b",
    re.IGNORECASE,
)
_RE_INICIO = re.compile(r"^\s*(?:(?:por\s+favor|assistente|augusto)[,:]?\s+)*", re.IGNORECASE)
_RE_ASPAS = re.compile(r"[\"“']([^\"”']+)[\"”']")
_RE_WINDOWS = re.compile(r"([A-Za-z]:[\\/][^\n\"'<>|?*]*)")
_RE_POSIX = re.compile(r"(?:^|\s)((?:/|~/)[^\s\"'<>|?*]+)")


def _extrair_caminho(trecho: str) -> Optional[str]:
    for rx in (_RE_ASPAS, _RE_WINDOWS, _RE_POSIX):
        m = rx.search(trecho)
        if m:
            caminho = m.group(1).strip().rstrip(".,;:!")
            if caminho:
                return caminho
    return None


def detectar_comando_projeto(texto: str) -> Optional[Dict[str, Optional[str]]]:
    """
    Retorna {"caminho": <str ou None>} quando o texto é um comando de análise de projeto.
    caminho None = comando reconhecido, mas sem diretório informado.
    Retorna None quando o texto não é um comando de análise.
    """
    if not texto:
        return None
    m = _RE_GATILHO.search(texto)
    if not m:
        return None
    caminho = _extrair_caminho(texto[m.end():])
    if caminho:
        return {"caminho": caminho}
    # Sem caminho: só considera comando se a frase começa com o gatilho (evita falsos positivos em conversa)
    inicio = _RE_INICIO.match(texto).end()
    if m.start() == inicio:
        return {"caminho": None}
    return None
