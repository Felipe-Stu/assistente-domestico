"""
Extração determinística de fatos do código-fonte.

- Python: módulo `ast` (análise completa; nada é executado).
- JavaScript/TypeScript/HTML: expressões regulares (análise parcial).
- Manifestos: requirements.txt e package.json.
- Markdown: referências a arquivos citados na documentação.

Toda informação extraída aqui é CONFIRMADA (veio do código), com o número da linha.
"""
import ast
import hashlib
import json
import re
import warnings
from typing import Any, Dict, List

# Módulo importado -> integração identificada
INTEGRACOES_POR_IMPORT = {
    "sqlite3": "Banco de dados relacional: SQLite",
    "sqlalchemy": "ORM: SQLAlchemy",
    "psycopg2": "Banco de dados: PostgreSQL",
    "pymysql": "Banco de dados: MySQL",
    "pymongo": "Banco de dados: MongoDB",
    "redis": "Cache/Fila: Redis",
    "chromadb": "Banco vetorial: ChromaDB",
    "sentence_transformers": "Embeddings locais: SentenceTransformers",
    "ollama": "LLM local: Ollama",
    "google.genai": "LLM em nuvem: Google Gemini (google-genai)",
    "google.generativeai": "LLM em nuvem: Google Gemini (google-generativeai)",
    "openai": "LLM em nuvem: OpenAI",
    "anthropic": "LLM em nuvem: Anthropic",
    "requests": "HTTP: requests",
    "httpx": "HTTP: httpx",
    "aiohttp": "HTTP: aiohttp",
    "urllib.request": "HTTP: urllib",
    "socket": "Rede: sockets",
    "speech_recognition": "Reconhecimento de voz: SpeechRecognition",
    "pyaudio": "Captura de áudio: PyAudio",
    "edge_tts": "Síntese de voz: Edge TTS",
    "pygame": "Reprodução de áudio: pygame",
    "pyttsx3": "Síntese de voz: pyttsx3",
    "vosk": "Reconhecimento de voz offline: Vosk",
    "flask": "Framework web: Flask",
    "fastapi": "Framework web: FastAPI",
    "django": "Framework web: Django",
    "subprocess": "Execução de processos externos",
    "smtplib": "E-mail: SMTP",
    "dotenv": "Configuração: variáveis de ambiente (.env)",
    "googleapiclient": "API Google (google-api-python-client)",
}

IMPORTS_EXCLUSIVOS_WINDOWS = {"asyncio.windows_events", "winreg", "msvcrt", "_winapi", "win32api", "win32con"}

_RE_TABELA_SQL = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?(\w+)[\"'`]?\s*\(", re.IGNORECASE)
_RE_URL = re.compile(r"https?://[^\s\"'<>`)]+")


def _linhas(texto: str) -> int:
    return texto.count("\n") + (1 if texto and not texto.endswith("\n") else 0)


def _num_linha(texto: str, pos: int) -> int:
    return texto.count("\n", 0, pos) + 1


def _doc_curta(doc: str, limite: int = 200) -> str:
    if not doc:
        return ""
    doc = " ".join(doc.strip().split())
    return doc if len(doc) <= limite else doc[: limite - 3] + "..."


def _fatos_base(caminho: str, linguagem: str, texto: str) -> Dict[str, Any]:
    return {
        "caminho": caminho,
        "linguagem": linguagem,
        "linhas": _linhas(texto),
        "metodo": "nenhum",
        "doc_modulo": "",
        "classes": [],
        "funcoes": [],
        "imports": [],
        "integracoes": [],
        "tabelas_sql": [],
        "urls": [],
        "ipc": [],
        "processos": [],
        "ponto_de_entrada": False,
        "erro_sintaxe": None,
        "hashes_corpo": [],
    }


def _detectar_comuns(fatos: Dict[str, Any], texto: str) -> None:
    for m in _RE_TABELA_SQL.finditer(texto):
        fatos["tabelas_sql"].append({"nome": m.group(1), "linha": _num_linha(texto, m.start())})
    vistos = set()
    for m in _RE_URL.finditer(texto):
        url = m.group(0).rstrip(".,;")
        if url not in vistos:
            vistos.add(url)
            fatos["urls"].append({"url": url, "linha": _num_linha(texto, m.start())})


def _registrar_integracao(fatos: Dict[str, Any], modulo: str, linha: int) -> None:
    for chave, descricao in INTEGRACOES_POR_IMPORT.items():
        if modulo == chave or modulo.startswith(chave + "."):
            fatos["integracoes"].append({"tipo": descricao, "origem": modulo, "linha": linha})
            return


# =============================================================================
# PYTHON
# =============================================================================

def _nome_base(no: ast.expr) -> str:
    try:
        return ast.unparse(no)
    except Exception:
        return "?"


def _hash_corpo(no: ast.AST) -> str:
    """Hash da estrutura do corpo (ignora nome e docstring) para detectar duplicação."""
    corpo = list(getattr(no, "body", []))
    if corpo and isinstance(corpo[0], ast.Expr) and isinstance(getattr(corpo[0], "value", None), ast.Constant) \
            and isinstance(corpo[0].value.value, str):
        corpo = corpo[1:]
    dump = "".join(ast.dump(c, annotate_fields=False) for c in corpo)
    return hashlib.sha1(dump.encode("utf-8")).hexdigest()


def extrair_python(caminho: str, texto: str) -> Dict[str, Any]:
    fatos = _fatos_base(caminho, "Python", texto)
    fatos["metodo"] = "ast"
    _detectar_comuns(fatos, texto)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # ex.: escapes inválidos em strings do projeto analisado
            arvore = ast.parse(texto)
    except SyntaxError as e:
        fatos["erro_sintaxe"] = {"linha": e.lineno or 0, "mensagem": str(e.msg)}
        return fatos

    fatos["doc_modulo"] = _doc_curta(ast.get_docstring(arvore) or "")

    for no in arvore.body:
        if isinstance(no, ast.ClassDef):
            metodos = [m.name for m in no.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            fatos["classes"].append({
                "nome": no.name,
                "linha": no.lineno,
                "bases": [_nome_base(b) for b in no.bases],
                "metodos": metodos,
                "doc": _doc_curta(ast.get_docstring(no) or ""),
            })
            for m in no.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(m.body) >= 4:
                    fatos["hashes_corpo"].append({"nome": f"{no.name}.{m.name}", "linha": m.lineno, "hash": _hash_corpo(m)})
        elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fatos["funcoes"].append({
                "nome": no.name,
                "linha": no.lineno,
                "argumentos": [a.arg for a in no.args.args],
                "assincrona": isinstance(no, ast.AsyncFunctionDef),
                "doc": _doc_curta(ast.get_docstring(no) or ""),
            })
            if len(no.body) >= 4:
                fatos["hashes_corpo"].append({"nome": no.name, "linha": no.lineno, "hash": _hash_corpo(no)})
        elif isinstance(no, ast.If):
            # if __name__ == "__main__":
            teste = no.test
            if isinstance(teste, ast.Compare) and isinstance(teste.left, ast.Name) and teste.left.id == "__name__":
                fatos["ponto_de_entrada"] = True

    # Imports em qualquer nível (inclui imports tardios dentro de funções)
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for alias in no.names:
                fatos["imports"].append({"modulo": alias.name, "nomes": [], "nivel": 0, "linha": no.lineno})
                _registrar_integracao(fatos, alias.name, no.lineno)
        elif isinstance(no, ast.ImportFrom):
            modulo = no.module or ""
            nomes = [a.name for a in no.names]
            fatos["imports"].append({"modulo": modulo, "nomes": nomes, "nivel": no.level, "linha": no.lineno})
            if no.level == 0:
                _registrar_integracao(fatos, modulo, no.lineno)
                for n in nomes:
                    # ex.: "from google import genai" -> google.genai
                    if f"{modulo}.{n}" in INTEGRACOES_POR_IMPORT:
                        _registrar_integracao(fatos, f"{modulo}.{n}", no.lineno)
        elif isinstance(no, ast.Call):
            alvo = _nome_base(no.func)
            if alvo in ("subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_output", "os.system"):
                fatos["processos"].append({"chamada": alvo, "linha": no.lineno})

    # Remove integrações duplicadas (mesmo tipo)
    vistos, unicos = set(), []
    for integ in fatos["integracoes"]:
        if integ["tipo"] not in vistos:
            vistos.add(integ["tipo"])
            unicos.append(integ)
    fatos["integracoes"] = unicos
    return fatos


# =============================================================================
# JAVASCRIPT / TYPESCRIPT
# =============================================================================

_RE_JS_REQUIRE = re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)")
_RE_JS_IMPORT = re.compile(r"^\s*import\s+(?:[\s\S]*?\s+from\s+)?['\"]([^'\"]+)['\"]", re.MULTILINE)
_RE_JS_FUNCAO = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", re.MULTILINE)
_RE_JS_ARROW = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>", re.MULTILINE)
_RE_JS_CLASSE = re.compile(r"^\s*(?:export\s+)?class\s+(\w+)", re.MULTILINE)
_RE_JS_IPC = re.compile(r"\b(ipcMain|ipcRenderer|webContents)\.(on|once|handle|send|invoke)\(\s*['\"]([^'\"]+)['\"]")
_RE_JS_PROCESSO = re.compile(r"\b(spawn|exec|execFile|fork)\(\s*['\"]([^'\"]+)['\"]")
_RE_JS_BRIDGE = re.compile(r"contextBridge\.exposeInMainWorld\(\s*['\"]([^'\"]+)['\"]")

_INTEGRACOES_JS = {
    "electron": "Interface desktop: Electron",
    "child_process": "Execução de processos externos (Node.js)",
    "axios": "HTTP: axios",
    "express": "Framework web: Express",
    "sqlite3": "Banco de dados relacional: SQLite (Node.js)",
    "better-sqlite3": "Banco de dados relacional: SQLite (Node.js)",
}


def extrair_javascript(caminho: str, texto: str, linguagem: str = "JavaScript") -> Dict[str, Any]:
    fatos = _fatos_base(caminho, linguagem, texto)
    fatos["metodo"] = "regex (parcial)"
    _detectar_comuns(fatos, texto)

    for rx in (_RE_JS_REQUIRE, _RE_JS_IMPORT):
        for m in rx.finditer(texto):
            linha = _num_linha(texto, m.start(1))
            fatos["imports"].append({"modulo": m.group(1), "nomes": [], "nivel": 0, "linha": linha})
            if m.group(1) in _INTEGRACOES_JS:
                fatos["integracoes"].append({"tipo": _INTEGRACOES_JS[m.group(1)], "origem": m.group(1), "linha": linha})

    for rx in (_RE_JS_FUNCAO, _RE_JS_ARROW):
        for m in rx.finditer(texto):
            fatos["funcoes"].append({"nome": m.group(1), "linha": _num_linha(texto, m.start(1)),
                                     "argumentos": [], "assincrona": False, "doc": ""})
    for m in _RE_JS_CLASSE.finditer(texto):
        fatos["classes"].append({"nome": m.group(1), "linha": _num_linha(texto, m.start(1)),
                                 "bases": [], "metodos": [], "doc": ""})
    for m in _RE_JS_IPC.finditer(texto):
        fatos["ipc"].append({"objeto": m.group(1), "operacao": m.group(2), "canal": m.group(3),
                             "linha": _num_linha(texto, m.start())})
    for m in _RE_JS_BRIDGE.finditer(texto):
        fatos["ipc"].append({"objeto": "contextBridge", "operacao": "exposeInMainWorld", "canal": m.group(1),
                             "linha": _num_linha(texto, m.start())})
    for m in _RE_JS_PROCESSO.finditer(texto):
        fatos["processos"].append({"chamada": f"{m.group(1)}('{m.group(2)}')", "linha": _num_linha(texto, m.start())})

    fatos["funcoes"].sort(key=lambda f: f["linha"])
    return fatos


# =============================================================================
# HTML / MANIFESTOS / MARKDOWN
# =============================================================================

_RE_HTML_RECURSO = re.compile(r"<(?:script|link)\b[^>]*?(?:src|href)\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)


def extrair_html(caminho: str, texto: str) -> Dict[str, Any]:
    fatos = _fatos_base(caminho, "HTML", texto)
    fatos["metodo"] = "regex (parcial)"
    _detectar_comuns(fatos, texto)
    for m in _RE_HTML_RECURSO.finditer(texto):
        if not m.group(1).startswith(("http://", "https://", "//", "data:")):
            fatos["imports"].append({"modulo": m.group(1), "nomes": [], "nivel": 0, "linha": _num_linha(texto, m.start())})
    return fatos


def extrair_requirements(texto: str) -> List[Dict[str, Any]]:
    deps = []
    for i, linha in enumerate(texto.splitlines(), start=1):
        linha = linha.split("#", 1)[0].strip()
        if not linha or linha.startswith(("-", "git+", "http")):
            continue
        nome = re.split(r"[<>=!~\[;\s]", linha, maxsplit=1)[0].strip()
        if nome:
            deps.append({"nome": nome, "especificacao": linha, "linha": i})
    return deps


def extrair_package_json(texto: str) -> Dict[str, Any]:
    try:
        dados = json.loads(texto)
    except (json.JSONDecodeError, ValueError) as e:
        return {"erro": str(e)}
    return {
        "nome": dados.get("name"),
        "versao": dados.get("version"),
        "main": dados.get("main"),
        "scripts": dados.get("scripts", {}) or {},
        "dependencias": dados.get("dependencies", {}) or {},
        "dependencias_dev": dados.get("devDependencies", {}) or {},
    }


_RE_MD_ARQUIVO = re.compile(r"`([\w./\\ -]*?[\w-]+\.(?:py|js|ts|json|html|css|md|txt|db|sql|yml|yaml|toml))`")
_RE_MD_TITULO = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def extrair_markdown(caminho: str, texto: str) -> Dict[str, Any]:
    fatos = _fatos_base(caminho, "Markdown", texto)
    fatos["metodo"] = "regex"
    fatos["referencias_arquivos"] = []
    vistos = set()
    for m in _RE_MD_ARQUIVO.finditer(texto):
        ref = m.group(1).strip().replace("\\", "/")
        if ref not in vistos:
            vistos.add(ref)
            fatos["referencias_arquivos"].append({"arquivo": ref, "linha": _num_linha(texto, m.start())})
    fatos["titulos"] = [t.group(2).strip() for t in _RE_MD_TITULO.finditer(texto)][:40]
    return fatos


def extrair_fatos(caminho: str, linguagem: str, texto: str) -> Dict[str, Any]:
    """Despacha para o extrator adequado. Linguagens sem extrator recebem apenas métricas."""
    if linguagem == "Python":
        return extrair_python(caminho, texto)
    if linguagem in ("JavaScript", "TypeScript"):
        return extrair_javascript(caminho, texto, linguagem)
    if linguagem == "HTML":
        return extrair_html(caminho, texto)
    if linguagem == "Markdown":
        return extrair_markdown(caminho, texto)
    fatos = _fatos_base(caminho, linguagem or "Desconhecida", texto)
    _detectar_comuns(fatos, texto)
    return fatos
