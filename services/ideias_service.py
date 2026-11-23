"""
Ideias de projetos: captura, fila de análise pelo Claude e conhecimento local.

1. `salvar` grava a ideia no SQLite na hora (funciona sem internet e sem Claude).
2. Um trabalhador em segundo plano manda as ideias pendentes ao Claude (prompt da skill `ideias`).
   Sem Claude disponível (sem login, limite do plano), a ideia continua pendente e é tentada de novo
   a cada IDEIAS_RETESTE_MIN minutos.
3. A análise volta para o banco e para um .md em IDEIAS_DIR (fora do Git), que entra na biblioteca
   local: a IA local passa a responder sobre o projeto sem internet.
"""
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from services.claude_service import ClaudeIndisponivelError
from services.logger_service import logger as custom_logger

COMPONENTE = "ideias"
TABELA = """
CREATE TABLE IF NOT EXISTS ideias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    origem TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    situacao TEXT NOT NULL DEFAULT 'pendente',
    analise TEXT,
    analisado_em TEXT,
    motivo TEXT
)
"""
COLUNAS = ("id", "titulo", "texto", "origem", "criado_em", "situacao", "analise", "analisado_em", "motivo")
SITUACOES = {"pendente": "aguardando análise", "analisando": "em análise", "analisada": "analisada"}
TAMANHO_MAXIMO = 8000


def titulo_provisorio(texto: str) -> str:
    primeira = " ".join(texto.split())
    return primeira if len(primeira) <= 60 else primeira[:57].rstrip() + "..."


def _slug(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:50] or "ideia"


def separar_titulo(analise: str):
    """A análise começa com '# Título'; devolve (título, corpo sem o título)."""
    linhas = analise.strip().splitlines()
    if linhas and linhas[0].startswith("# "):
        return linhas[0][2:].strip()[:100], "\n".join(linhas[1:]).strip()
    return None, analise.strip()


class IdeiasService:
    def __init__(self, db, claude, pasta: Path, prompt_analise: Callable[[], str], biblioteca=None,
                 agora: Callable[[], datetime] = datetime.now, intervalo_reteste_s: float = 1800):
        self.db = db
        self.claude = claude
        self.pasta = Path(pasta)
        self._prompt_analise = prompt_analise
        self.biblioteca = biblioteca
        self._agora = agora
        self.intervalo_reteste_s = intervalo_reteste_s
        self._trava = threading.Lock()
        self._acordar = threading.Event()
        self.db.executar_comando(TABELA)

    # ------------------------------------------------------------------
    # Banco
    # ------------------------------------------------------------------

    def _linha(self, linha) -> Dict:
        return dict(zip(COLUNAS, linha))

    def salvar(self, texto: str, origem: str = "chat") -> Dict:
        texto = (texto or "").strip()[:TAMANHO_MAXIMO]
        if not texto:
            raise ValueError("ideia vazia")
        with self._trava:
            self.db.executar_comando(
                "INSERT INTO ideias (titulo, texto, origem, criado_em) VALUES (?, ?, ?, ?)",
                (titulo_provisorio(texto), texto, origem, self._agora().isoformat(timespec="seconds")),
            )
            ideia = self._linha(self.db.executar_consulta(
                f"SELECT {', '.join(COLUNAS)} FROM ideias ORDER BY id DESC LIMIT 1")[0])
        custom_logger.evento(COMPONENTE, "salva", id=ideia["id"], origem=origem.split(":")[0])
        self._acordar.set()
        return ideia

    def obter(self, ident: int) -> Optional[Dict]:
        linhas = self.db.executar_consulta(f"SELECT {', '.join(COLUNAS)} FROM ideias WHERE id = ?", (ident,))
        return self._linha(linhas[0]) if linhas else None

    def listar(self, limite: int = 10) -> List[Dict]:
        return [self._linha(l) for l in self.db.executar_consulta(
            f"SELECT {', '.join(COLUNAS)} FROM ideias ORDER BY id DESC LIMIT ?", (limite,))]

    def buscar(self, texto: str) -> Optional[Dict]:
        """Por número (#3, ideia 3) ou pela palavra mais rara do título; senão, a mais recente."""
        numero = re.search(r"#\s*(\d+)|\bideia\s+(\d+)\b", texto or "", re.IGNORECASE)
        if numero:
            return self.obter(int(numero.group(1) or numero.group(2)))
        ideias = self.listar(limite=200)
        palavras = {p for p in re.findall(r"\w{4,}", _slug(texto or "").replace("-", " "))}
        melhor, pontos = None, 0
        for ideia in ideias:
            alvo = set(_slug(f"{ideia['titulo']} {ideia['texto'][:300]}").split("-"))
            comuns = len(palavras & alvo)
            if comuns > pontos:
                melhor, pontos = ideia, comuns
        return melhor

    def pendentes(self) -> List[Dict]:
        return [self._linha(l) for l in self.db.executar_consulta(
            f"SELECT {', '.join(COLUNAS)} FROM ideias WHERE situacao IN ('pendente', 'analisando') ORDER BY id")]

    def reanalisar(self, ident: int) -> None:
        self.db.executar_comando("UPDATE ideias SET situacao = 'pendente', motivo = NULL WHERE id = ?", (ident,))
        self._acordar.set()

    # ------------------------------------------------------------------
    # Análise
    # ------------------------------------------------------------------

    def claude_pronto(self) -> bool:
        return self.claude is not None and self.claude.configurado()

    def analisar(self, ident: int) -> Dict:
        """Manda a ideia ao Claude. ClaudeIndisponivelError deixa a ideia pendente com o motivo."""
        ideia = self.obter(ident)
        if ideia is None:
            raise KeyError(ident)
        if not self.claude_pronto():
            motivo = self.claude._motivo_nao_configurado() if self.claude else "Claude não configurado"
            self.db.executar_comando("UPDATE ideias SET motivo = ? WHERE id = ?", (motivo, ident))
            raise ClaudeIndisponivelError(motivo)
        self.db.executar_comando("UPDATE ideias SET situacao = 'analisando' WHERE id = ?", (ident,))
        try:
            analise = self.claude.gerar_texto(self._prompt_analise(), ideia["texto"])
        except ClaudeIndisponivelError as erro:
            self.db.executar_comando("UPDATE ideias SET situacao = 'pendente', motivo = ? WHERE id = ?", (erro.motivo, ident))
            raise
        if not analise.strip():
            self.db.executar_comando("UPDATE ideias SET situacao = 'pendente', motivo = ? WHERE id = ?", ("resposta vazia", ident))
            raise ClaudeIndisponivelError("o Claude devolveu uma análise vazia")
        titulo, _ = separar_titulo(analise)
        agora = self._agora().isoformat(timespec="seconds")
        self.db.executar_comando(
            "UPDATE ideias SET titulo = ?, analise = ?, analisado_em = ?, situacao = 'analisada', motivo = NULL WHERE id = ?",
            (titulo or ideia["titulo"], analise.strip(), agora, ident),
        )
        ideia = self.obter(ident)
        ideia["arquivo"] = str(self.gravar_arquivo(ideia))
        custom_logger.evento(COMPONENTE, "analisada", id=ident)
        self._indexar()
        return ideia

    def gravar_arquivo(self, ideia: Dict) -> Path:
        self.pasta.mkdir(parents=True, exist_ok=True)
        for antigo in self.pasta.glob(f"ideia-{ideia['id']:04d}-*.md"):
            antigo.unlink(missing_ok=True)
        _, corpo = separar_titulo(ideia["analise"] or "")
        arquivo = self.pasta / f"ideia-{ideia['id']:04d}-{_slug(ideia['titulo'])}.md"
        arquivo.write_text(
            f"# {ideia['titulo']}\n\n"
            f"Ideia #{ideia['id']}, registrada em {ideia['criado_em'][:16].replace('T', ' ')}; "
            f"análise do Claude em {(ideia['analisado_em'] or '')[:16].replace('T', ' ')}.\n\n"
            f"## Ideia original\n\n{ideia['texto']}\n\n{corpo}\n",
            encoding="utf-8",
        )
        return arquivo

    def _indexar(self) -> None:
        if self.biblioteca is None:
            return
        try:
            self.biblioteca.indexar()
        except Exception as erro:  # a análise já está salva; a biblioteca se atualiza na próxima vez
            custom_logger.evento(COMPONENTE, "biblioteca_falhou", type(erro).__name__, nivel="WARNING")

    def processar_pendentes(self, notificar: Optional[Callable[[Dict], None]] = None) -> int:
        feitas = 0
        for ideia in self.pendentes():
            try:
                analisada = self.analisar(ideia["id"])
            except ClaudeIndisponivelError:
                break  # o mesmo motivo vale para as próximas; tenta de novo mais tarde
            feitas += 1
            if notificar:
                try:
                    notificar(analisada)
                except Exception as erro:
                    custom_logger.evento(COMPONENTE, "aviso_falhou", type(erro).__name__, nivel="WARNING")
        return feitas

    def iniciar_em_segundo_plano(self, deve_parar: Callable[[], bool], notificar: Optional[Callable[[Dict], None]] = None):
        def laco():
            while not deve_parar():
                try:
                    self.processar_pendentes(notificar)
                except Exception as erro:
                    custom_logger.evento(COMPONENTE, "trabalhador_falhou", type(erro).__name__, nivel="ERROR")
                self._acordar.wait(self.intervalo_reteste_s)
                self._acordar.clear()

        linha = threading.Thread(target=laco, name="ideias", daemon=True)
        linha.start()
        return linha

    # ------------------------------------------------------------------
    # Mensagens de texto (chat e Telegram)
    # ------------------------------------------------------------------

    def resumo_lista(self, limite: int = 10) -> str:
        ideias = self.listar(limite)
        if not ideias:
            return "Nenhuma ideia salva ainda."
        return "Suas ideias:\n" + "\n".join(f"#{i['id']} {i['titulo']} ({SITUACOES.get(i['situacao'], i['situacao'])})" for i in ideias)

    def detalhe(self, ideia: Dict) -> str:
        if ideia["situacao"] == "analisada":
            return ideia["analise"]
        motivo = f" Motivo: {ideia['motivo']}." if ideia.get("motivo") else ""
        return f"Ideia #{ideia['id']} ({SITUACOES.get(ideia['situacao'])}).{motivo}\n\n{ideia['texto']}"

    def confirmacao(self, ideia: Dict) -> str:
        if self.claude_pronto():
            return f"Ideia #{ideia['id']} salva. O Claude vai analisar em segundo plano e eu aviso quando terminar."
        return (f"Ideia #{ideia['id']} salva. A análise fica na fila até o Claude estar disponível "
                f"({self.claude._motivo_nao_configurado() if self.claude else 'Claude não configurado'}).")

    def responder_mensagem(self, texto: str, origem: str) -> str:
        """Bot do Telegram: comandos simples; qualquer outro texto é uma ideia nova."""
        comando = (texto or "").strip()
        minusculo = comando.lower()
        if minusculo in ("/start", "/ajuda", "ajuda", "/help"):
            return ("Mande a ideia em texto que eu salvo no assistente e o Claude analisa.\n"
                    "/ideias — últimas ideias\n/ver 3 — análise da ideia 3\n/reanalisar 3 — analisar de novo")
        if minusculo in ("/ideias", "ideias", "/lista"):
            return self.resumo_lista()
        numero = re.match(r"^/?(ver|reanalisar)\s*#?(\d+)$", minusculo)
        if numero:
            ideia = self.obter(int(numero.group(2)))
            if ideia is None:
                return f"Não encontrei a ideia #{numero.group(2)}."
            if numero.group(1) == "reanalisar":
                self.reanalisar(ideia["id"])
                return f"Ideia #{ideia['id']} voltou para a fila de análise."
            return self.detalhe(ideia)
        if minusculo.startswith("/"):
            return "Comando desconhecido. Mande /ajuda."
        return self.confirmacao(self.salvar(comando, origem))
