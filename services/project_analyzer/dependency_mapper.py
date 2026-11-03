"""
Mapeamento de dependências internas (grafo de imports) e externas (bibliotecas).
Processamento 100% determinístico sobre os fatos extraídos.
"""
import posixpath
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

# Nome importado -> nome do pacote no pip (quando diferentes)
IMPORT_PARA_PIP = {
    "google.genai": "google-genai",
    "google.generativeai": "google-generativeai",
    "googleapiclient": "google-api-python-client",
    "dotenv": "python-dotenv",
    "speech_recognition": "speechrecognition",
    "sentence_transformers": "sentence-transformers",
    "edge_tts": "edge-tts",
    "pyaudio": "pyaudio",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "win32api": "pywin32",
}

# Pacotes declarados que normalmente não são importados diretamente
DEPENDENCIAS_INDIRETAS_CONHECIDAS = {
    "pyaudio": "usado internamente pelo SpeechRecognition (sr.Microphone)",
    "uvicorn": "servidor ASGI, executado via linha de comando",
    "gunicorn": "servidor WSGI, executado via linha de comando",
    "pytest": "ferramenta de testes",
}

_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}

# Módulos nativos do Node.js / Electron (não são dependências npm)
_NODE_NATIVOS = {
    "fs", "path", "os", "child_process", "http", "https", "url", "util", "events", "stream",
    "crypto", "net", "zlib", "readline", "process", "buffer", "assert", "worker_threads",
}


def normalizar_pacote(nome: str) -> str:
    return nome.lower().replace("_", "-").replace(".", "-")


def nome_modulo(caminho: str) -> str:
    """'services/vector/memory_service.py' -> 'services.vector.memory_service'."""
    sem_ext = caminho[:-3] if caminho.endswith(".py") else caminho
    partes = sem_ext.split("/")
    if partes[-1] == "__init__":
        partes = partes[:-1]
    return ".".join(partes)


class MapaDependencias:
    def __init__(self, fatos_por_arquivo: Dict[str, Dict[str, Any]],
                 requirements: Optional[List[Dict[str, Any]]] = None,
                 package_json: Optional[Dict[str, Any]] = None):
        self.fatos = fatos_por_arquivo
        self.requirements = requirements
        self.package_json = package_json
        self.modulos_python = {nome_modulo(p): p for p, f in fatos_por_arquivo.items() if f.get("linguagem") == "Python"}
        self.arquivos = set(fatos_por_arquivo.keys())

        self.arestas: Dict[str, Set[str]] = defaultdict(set)        # arquivo -> arquivos dos quais depende
        self.usado_por: Dict[str, Set[str]] = defaultdict(set)      # arquivo -> arquivos que o importam
        self.externas: Dict[str, List[Dict[str, Any]]] = defaultdict(list)  # pacote raiz -> usos
        self.internos_nao_resolvidos: List[Dict[str, Any]] = []
        self.imports_windows: List[Dict[str, Any]] = []
        self._construir()

    # ------------------------------------------------------------------
    def _resolver_python(self, origem: str, imp: Dict[str, Any]) -> Optional[str]:
        modulo, nivel = imp["modulo"], imp["nivel"]
        if nivel > 0:
            pacote = nome_modulo(origem).split(".")
            if not origem.endswith("__init__.py"):
                pacote = pacote[:-1]
            base = pacote[: len(pacote) - (nivel - 1)] if nivel > 1 else pacote
            modulo = ".".join([p for p in base + ([modulo] if modulo else []) if p])
        # Tenta "pacote.nome" (from services import ai_service) antes de "pacote"
        for nome in imp.get("nomes", []):
            candidato = f"{modulo}.{nome}" if modulo else nome
            if candidato in self.modulos_python:
                return self.modulos_python[candidato]
        partes = modulo.split(".")
        for i in range(len(partes), 0, -1):
            candidato = ".".join(partes[:i])
            if candidato in self.modulos_python:
                return self.modulos_python[candidato]
        return None

    def _resolver_relativo(self, origem: str, alvo: str) -> Optional[str]:
        if not alvo.startswith("."):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(origem), alvo))
        for candidato in (base, base + ".js", base + ".ts", base + ".mjs", base + "/index.js"):
            if candidato in self.arquivos:
                return candidato
        return None

    def _construir(self) -> None:
        raizes_internas = {m.split(".")[0] for m in self.modulos_python}
        for origem, fatos in self.fatos.items():
            ling = fatos.get("linguagem")
            for imp in fatos.get("imports", []):
                if ling == "Python":
                    destino = self._resolver_python(origem, imp)
                    if destino:
                        if destino != origem:
                            self.arestas[origem].add(destino)
                            self.usado_por[destino].add(origem)
                        continue
                    if imp["nivel"] > 0:
                        self.internos_nao_resolvidos.append({"arquivo": origem, "modulo": "." * imp["nivel"] + imp["modulo"], "linha": imp["linha"]})
                        continue
                    modulo = imp["modulo"]
                    if modulo in ("asyncio.windows_events",) or modulo.split(".")[0] in ("winreg", "msvcrt", "_winapi", "win32api", "win32con"):
                        self.imports_windows.append({"arquivo": origem, "modulo": modulo, "linha": imp["linha"]})
                    raiz = modulo.split(".")[0]
                    if raiz in raizes_internas:
                        self.internos_nao_resolvidos.append({"arquivo": origem, "modulo": modulo, "linha": imp["linha"]})
                        continue
                    if raiz in _STDLIB or not raiz:
                        continue
                    chave = modulo if modulo in IMPORT_PARA_PIP else raiz
                    if raiz == "google":
                        nomes = imp.get("nomes", [])
                        chave = f"google.{nomes[0]}" if nomes and not modulo.count(".") else ".".join(modulo.split(".")[:2])
                    self.externas[chave].append({"arquivo": origem, "linha": imp["linha"]})
                elif ling in ("JavaScript", "TypeScript", "HTML"):
                    alvo = imp["modulo"]
                    if alvo.startswith("."):
                        destino = self._resolver_relativo(origem, alvo)
                    elif ling == "HTML":
                        destino = self._resolver_relativo(origem, "./" + alvo)
                    else:
                        destino = None
                    partes_npm = alvo.replace("node:", "").split("/")
                    nome_npm = "/".join(partes_npm[:2]) if alvo.startswith("@") else partes_npm[0]
                    if destino:
                        self.arestas[origem].add(destino)
                        self.usado_por[destino].add(origem)
                    elif ling != "HTML" and not alvo.startswith("."):
                        if nome_npm not in _NODE_NATIVOS:
                            self.externas[f"npm:{nome_npm}"].append({"arquivo": origem, "linha": imp["linha"]})
                    elif alvo.startswith("."):
                        self.internos_nao_resolvidos.append({"arquivo": origem, "modulo": alvo, "linha": imp["linha"]})

    # ------------------------------------------------------------------
    def pacote_pip(self, chave_import: str) -> str:
        return normalizar_pacote(IMPORT_PARA_PIP.get(chave_import, chave_import))

    def dependencias_declaradas(self) -> Dict[str, Dict[str, Any]]:
        declaradas = {}
        for dep in self.requirements or []:
            declaradas[normalizar_pacote(dep["nome"])] = {"origem": "requirements.txt", **dep}
        if self.package_json and "erro" not in self.package_json:
            for secao in ("dependencias", "dependencias_dev"):
                for nome, versao in self.package_json.get(secao, {}).items():
                    declaradas[f"npm:{nome}"] = {"origem": "package.json", "nome": nome, "especificacao": versao, "secao": secao}
        return declaradas

    def nao_declaradas(self) -> List[Dict[str, Any]]:
        """Bibliotecas importadas no código e ausentes do manifesto correspondente."""
        declaradas = self.dependencias_declaradas()
        resultado = []
        for chave, usos in sorted(self.externas.items()):
            if chave.startswith("npm:"):
                if self.package_json is None or chave in declaradas:
                    continue
                resultado.append({"pacote": chave[4:], "manifesto": "package.json", "usos": usos})
            else:
                if self.requirements is None:
                    continue
                pip = self.pacote_pip(chave)
                if pip not in declaradas:
                    resultado.append({"pacote": pip, "import": chave, "manifesto": "requirements.txt", "usos": usos})
        return resultado

    def declaradas_sem_uso(self) -> List[Dict[str, Any]]:
        usados = {self.pacote_pip(c) for c in self.externas if not c.startswith("npm:")}
        usados |= {c for c in self.externas if c.startswith("npm:")}
        resultado = []
        for chave, dep in sorted(self.dependencias_declaradas().items()):
            if chave in usados:
                continue
            if chave.startswith("npm:") and dep.get("secao") == "dependencias_dev":
                continue  # devDependencies (ex.: electron) costumam ser usadas por scripts/CLI
            resultado.append({"pacote": dep.get("nome", chave), "origem": dep["origem"],
                              "linha": dep.get("linha"), "nota": DEPENDENCIAS_INDIRETAS_CONHECIDAS.get(chave.replace("npm:", ""))})
        return resultado

    def pontos_de_entrada(self) -> List[str]:
        entradas = [p for p, f in self.fatos.items() if f.get("ponto_de_entrada")]
        if self.package_json and self.package_json.get("main"):
            entradas.append(self.package_json["main"])
        return sorted(set(entradas))

    def centrais(self, limite: int = 8) -> List[Dict[str, Any]]:
        ranking = sorted(self.usado_por.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        return [{"arquivo": a, "usado_por": len(u)} for a, u in ranking[:limite] if u]

    def mermaid(self, limite_arestas: int = 70) -> str:
        """Diagrama Mermaid das dependências internas, agrupado por pasta."""
        arestas = sorted((o, d) for o, ds in self.arestas.items() for d in ds)
        if not arestas:
            return ""
        nos = sorted({n for a in arestas[:limite_arestas] for n in a})
        ids = {n: f"N{i}" for i, n in enumerate(nos)}
        grupos: Dict[str, List[str]] = defaultdict(list)
        for n in nos:
            grupos[posixpath.dirname(n) or "(raiz)"].append(n)
        linhas = ["graph LR"]
        for i, (grupo, membros) in enumerate(sorted(grupos.items())):
            linhas.append(f'    subgraph G{i}["{grupo}"]')
            for n in membros:
                linhas.append(f'        {ids[n]}["{posixpath.basename(n)}"]')
            linhas.append("    end")
        for o, d in arestas[:limite_arestas]:
            linhas.append(f"    {ids[o]} --> {ids[d]}")
        return "\n".join(linhas)

    @property
    def arestas_omitidas(self) -> int:
        total = sum(len(v) for v in self.arestas.values())
        return max(0, total - 70)
