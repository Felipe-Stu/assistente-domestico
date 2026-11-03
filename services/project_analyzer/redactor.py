"""
Ocultação de segredos (tokens, chaves de API, senhas).

Aplicado a todo texto que sai da análise: prompts enviados ao LLM local
e documentação escrita em disco. O valor do segredo nunca é registrado.
"""
import re
from typing import Tuple

MARCADOR = "[SEGREDO_OCULTADO]"

# Padrões de credenciais conhecidas (o valor inteiro é substituído)
_PADROES_DIRETOS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),                 # GitHub token
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),               # GitHub fine-grained
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),                     # Google API key
    re.compile(r"AQ\.[A-Za-z0-9_\-]{20,}"),                    # Google AI Studio key
    re.compile(r"sk-[A-Za-z0-9\-_]{20,}"),                     # OpenAI / Anthropic
    re.compile(r"AKIA[0-9A-Z]{16}"),                           # AWS access key
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),              # Slack
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]

# Atribuições do tipo api_key = "valor" / senha: valor (apenas o valor é substituído)
_PADRAO_ATRIBUICAO = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|senha|access[_-]?key)\b(\s*[:=]\s*['\"]?)([^\s'\"]{8,})"
)

# Valores que não são segredos (leitura de variável de ambiente, placeholders)
_VALORES_PERMITIDOS = re.compile(r"(?i)^(os\.getenv|os\.environ|getenv|sua_chave|your_|<|\$\{|process\.env|none|null|true|false)")


def ocultar_segredos(texto: str) -> Tuple[str, int]:
    """Retorna (texto_sem_segredos, quantidade_de_ocorrências_ocultadas)."""
    if not texto:
        return texto, 0

    total = 0
    for padrao in _PADROES_DIRETOS:
        texto, n = padrao.subn(MARCADOR, texto)
        total += n

    def _substituir(m: re.Match) -> str:
        nonlocal total
        valor = m.group(3)
        if valor == MARCADOR or _VALORES_PERMITIDOS.match(valor):
            return m.group(0)
        total += 1
        return f"{m.group(1)}{m.group(2)}{MARCADOR}"

    texto = _PADRAO_ATRIBUICAO.sub(_substituir, texto)
    return texto, total


def contem_segredo(texto: str) -> int:
    """Quantidade de possíveis segredos encontrados (sem retornar os valores)."""
    return ocultar_segredos(texto)[1]
