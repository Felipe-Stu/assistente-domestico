"""
Biblioteca de contexto da skill de programação (SKP).

Indexa a documentação do projeto no ChromaDB (coleção própria, separada das memórias) e devolve
os trechos mais próximos de uma pergunta. Só os trechos relevantes vão ao modelo, nunca a
biblioteca inteira: um prompt grande deixa o modelo local lento e menos preciso.

Fontes: documentação que já é pública no repositório, a documentação gerada a partir do código e,
como pasta extra, as análises de ideias (Ideias/*.md, que já vieram do Claude).
A pasta de planejamento fica de fora (tem informação pessoal, e os trechos podem ir ao Claude).
"""
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from services.logger_service import logger as custom_logger

COLECAO = "biblioteca_projeto"
TAMANHO_MAXIMO = 1500
_RE_TITULO = re.compile(r"^#{1,4} ", re.MULTILINE)


def fontes_padrao(raiz: Path) -> List[Path]:
    raiz = Path(raiz)
    arquivos = [raiz / "README.md", raiz / "CHANGELOG.md", raiz / "skills" / "README.md"]
    arquivos += sorted((raiz / "Sobre a Versão").glob("*.md"))
    arquivos += sorted((raiz / "skills").glob("*/SKILL.md"))
    gerada = raiz.parent / "Documentacao_Gerada" / raiz.name
    if gerada.is_dir():
        arquivos += sorted(gerada.glob("*.md"))
    return [a for a in arquivos if a.is_file()]


def dividir(texto: str, tamanho: int = TAMANHO_MAXIMO) -> List[str]:
    """Divide pelos títulos Markdown; seções longas são cortadas em parágrafos."""
    inicios = [m.start() for m in _RE_TITULO.finditer(texto)]
    if not inicios or inicios[0] != 0:
        inicios = [0] + inicios
    secoes = [texto[a:b].strip() for a, b in zip(inicios, inicios[1:] + [len(texto)])]
    trechos: List[str] = []
    for secao in filter(None, secoes):
        atual = ""
        for paragrafo in secao.split("\n\n"):
            if atual and len(atual) + len(paragrafo) + 2 > tamanho:
                trechos.append(atual.strip())
                atual = ""
            atual += paragrafo + "\n\n"
            while len(atual) > tamanho:
                trechos.append(atual[:tamanho].strip())
                atual = atual[tamanho:]
        if atual.strip():
            trechos.append(atual.strip())
    return trechos


class BibliotecaService:
    def __init__(self, vector_store, raiz: Path, arquivo_indice: Path, fontes: Optional[Iterable[Path]] = None,
                 pastas_extras: Iterable[Path] = ()):
        self.vector_store = vector_store
        self.raiz = Path(raiz)
        self.arquivo_indice = Path(arquivo_indice)
        self._fontes = list(fontes) if fontes is not None else None
        self.pastas_extras = [Path(p) for p in pastas_extras]

    def fontes(self) -> List[Path]:
        arquivos = self._fontes if self._fontes is not None else fontes_padrao(self.raiz)
        for pasta in self.pastas_extras:  # lidas a cada indexação: arquivos novos entram sozinhos
            arquivos = arquivos + sorted(pasta.glob("*.md"))
        return arquivos

    def _nome(self, arquivo: Path) -> str:
        try:
            return arquivo.relative_to(self.raiz.parent).as_posix()
        except ValueError:
            return arquivo.name

    def _ler_indice(self) -> Dict[str, Dict]:
        try:
            return json.loads(self.arquivo_indice.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def indexar(self) -> Dict[str, int]:
        """Reindexa só os arquivos que mudaram; remove os trechos de arquivos alterados ou apagados."""
        indice = self._ler_indice()
        novo, contagem = {}, {"arquivos": 0, "atualizados": 0, "trechos": 0, "removidos": 0}
        from services.vector.vector_store_service import VectorDocument
        for arquivo in self.fontes():
            nome = self._nome(arquivo)
            texto = arquivo.read_text(encoding="utf-8", errors="replace")
            resumo = hashlib.sha256(texto.encode("utf-8")).hexdigest()
            contagem["arquivos"] += 1
            anterior = indice.get(nome)
            if anterior and anterior["sha256"] == resumo:
                novo[nome] = anterior
                contagem["trechos"] += len(anterior["ids"])
                continue
            if anterior:
                self.vector_store.delete_documents(anterior["ids"], collection_name=COLECAO)
                contagem["removidos"] += len(anterior["ids"])
            trechos = dividir(texto)
            ids = [f"{nome}#{i}" for i in range(len(trechos))]
            documentos = [VectorDocument(id=i, content=t, metadata={"fonte": nome, "parte": n})
                          for n, (i, t) in enumerate(zip(ids, trechos))]
            if documentos and not self.vector_store.upsert_documents(documentos, collection_name=COLECAO):
                raise RuntimeError(f"Não foi possível indexar {nome} (modelo de embeddings indisponível?)")
            novo[nome] = {"sha256": resumo, "ids": ids}
            contagem["atualizados"] += 1
            contagem["trechos"] += len(ids)
        for nome, anterior in indice.items():
            if nome not in novo:
                self.vector_store.delete_documents(anterior["ids"], collection_name=COLECAO)
                contagem["removidos"] += len(anterior["ids"])
        self.arquivo_indice.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo_indice.write_text(json.dumps(novo, ensure_ascii=False, indent=1), encoding="utf-8")
        custom_logger.evento("biblioteca", "indexada", **contagem)
        return contagem

    def buscar(self, pergunta: str, k: int = 6, score_minimo: float = 0.3) -> List[Dict[str, str]]:
        """Trechos mais próximos da pergunta; lista vazia se a biblioteca não estiver pronta."""
        try:
            resultados = self.vector_store.search_similarity(pergunta, top_k=k, min_score=score_minimo,
                                                             collection_name=COLECAO)
        except Exception as erro:
            custom_logger.evento("biblioteca", "busca_falhou", str(erro)[:200], nivel="WARNING")
            return []
        return [{"fonte": (r.get("metadata") or {}).get("fonte", "?"), "texto": r.get("content", "")} for r in resultados]


def bloco_de_contexto(trechos: List[Dict[str, str]]) -> str:
    if not trechos:
        return ""
    partes = [f"### {t['fonte']}\n{t['texto']}" for t in trechos]
    return "\n\n## Trechos da documentação do projeto (use se forem relevantes)\n\n" + "\n\n".join(partes)
