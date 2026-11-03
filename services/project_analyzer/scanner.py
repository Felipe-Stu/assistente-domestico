"""
Varredura somente-leitura do diretório do projeto.

Nenhum arquivo é aberto em modo de escrita. Links simbólicos de diretório
não são seguidos. Binários e arquivos grandes são listados, mas não lidos.
"""
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

DIRETORIOS_IGNORADOS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv", "env", "ENV",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode", "dist", "build", "site-packages",
    "chroma_db", ".tox", ".next", ".cache",
}

LINGUAGEM_POR_EXTENSAO = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".html": "HTML",
    ".htm": "HTML", ".css": "CSS", ".json": "JSON", ".md": "Markdown", ".txt": "Texto",
    ".rtf": "Texto", ".sql": "SQL", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML",
    ".ini": "INI", ".cfg": "INI", ".sh": "Shell", ".ps1": "PowerShell", ".bat": "Batch",
    ".java": "Java", ".cs": "C#", ".cpp": "C++", ".c": "C", ".h": "C/C++", ".go": "Go",
    ".rs": "Rust", ".php": "PHP", ".rb": "Ruby", ".kt": "Kotlin", ".lua": "Lua",
    ".gd": "GDScript", ".xml": "XML",
}

EXTENSOES_BINARIAS = {
    ".db", ".sqlite", ".sqlite3", ".bin", ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg", ".mp3", ".wav", ".ogg",
    ".mp4", ".avi", ".mov", ".zip", ".rar", ".7z", ".tar", ".gz", ".pdf", ".ods", ".odt",
    ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ttf", ".otf", ".woff", ".woff2", ".onnx",
    ".pt", ".pth", ".safetensors", ".gguf", ".npy",
}

TAMANHO_MAXIMO_LEITURA = 1_000_000  # 1 MB


@dataclass
class ArquivoProjeto:
    caminho_relativo: str          # sempre com "/" (independente do SO)
    caminho_absoluto: str
    tamanho: int
    extensao: str
    linguagem: Optional[str]
    sha256: str
    texto: bool
    motivo_ignorado: Optional[str] = None


@dataclass
class ResultadoVarredura:
    raiz: str
    arquivos: List[ArquivoProjeto] = field(default_factory=list)
    diretorios_ignorados: List[str] = field(default_factory=list)
    truncado: bool = False

    @property
    def arquivos_texto(self) -> List[ArquivoProjeto]:
        return [a for a in self.arquivos if a.texto and not a.motivo_ignorado]


def _sha256(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def _parece_binario(caminho: str) -> bool:
    with open(caminho, "rb") as f:
        return b"\x00" in f.read(8192)


def varrer_projeto(raiz: str, excluir: Optional[List[str]] = None, max_arquivos: int = 20000) -> ResultadoVarredura:
    """
    Percorre o projeto e devolve a lista de arquivos com hash e linguagem.
    `excluir`: caminhos absolutos a ignorar (ex.: a própria pasta de saída da documentação).
    """
    raiz_path = Path(raiz).resolve()
    excluidos = {str(Path(e).resolve()) for e in (excluir or [])}
    resultado = ResultadoVarredura(raiz=str(raiz_path))

    for pasta_atual, subpastas, arquivos in os.walk(raiz_path, followlinks=False):
        mantidas = []
        for d in sorted(subpastas):
            caminho_d = os.path.join(pasta_atual, d)
            if d in DIRETORIOS_IGNORADOS or str(Path(caminho_d).resolve()) in excluidos:
                resultado.diretorios_ignorados.append(Path(caminho_d).relative_to(raiz_path).as_posix())
            else:
                mantidas.append(d)
        subpastas[:] = mantidas

        for nome in sorted(arquivos):
            if len(resultado.arquivos) >= max_arquivos:
                resultado.truncado = True
                return resultado

            caminho = os.path.join(pasta_atual, nome)
            if os.path.islink(caminho) or not os.path.isfile(caminho):
                continue

            ext = os.path.splitext(nome)[1].lower()
            rel = Path(caminho).relative_to(raiz_path).as_posix()
            try:
                tamanho = os.path.getsize(caminho)
                sha = _sha256(caminho)
            except OSError as e:
                resultado.arquivos.append(ArquivoProjeto(rel, caminho, 0, ext, None, "", False, f"erro de leitura: {e}"))
                continue

            motivo = None
            texto = True
            if ext in EXTENSOES_BINARIAS:
                texto, motivo = False, "binário"
            elif tamanho > TAMANHO_MAXIMO_LEITURA:
                texto, motivo = False, "arquivo maior que 1 MB"
            else:
                try:
                    if _parece_binario(caminho):
                        texto, motivo = False, "binário"
                except OSError as e:
                    texto, motivo = False, f"erro de leitura: {e}"

            linguagem = LINGUAGEM_POR_EXTENSAO.get(ext)
            if nome == "package-lock.json":
                motivo = "lockfile (não analisado)"
            resultado.arquivos.append(ArquivoProjeto(rel, caminho, tamanho, ext, linguagem, sha, texto, motivo))

    return resultado


def ler_texto(arquivo: ArquivoProjeto) -> str:
    """Leitura somente-leitura com tolerância a codificações (UTF-8, depois Latin-1)."""
    with open(arquivo.caminho_absoluto, "rb") as f:
        dados = f.read()
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dados.decode("latin-1")
