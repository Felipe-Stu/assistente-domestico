"""
Roteiro da skill agenda (SK7): compromissos e lembretes guardados no SQLite do assistente.

criar:     o modelo local extrai título, data e hora; o código valida e grava. Sem data, pergunta.
consultar: sem modelo; hoje, amanhã, semana, dia da semana ou data (dd/mm); padrão: próximos 7 dias.
corrigir:  "cancelar último compromisso" apaga o último registro, depois de confirmação.

Feita só com esta pasta, sem alterar o núcleo. O aviso na hora do compromisso (alarme) depende de um
agendador no núcleo e fica para a V7.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta

from core.skills import obter_catalogo
from core.skills.motor import Resposta
from services.logger_service import logger as custom_logger

DIAS = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
DIAS_EXIBICAO = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
NOMES_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
RESPOSTAS_SIM = {"sim", "s", "ok", "confirmo", "pode", "pode apagar", "apaga", "apagar"}
_RE_HORA = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_RE_DATA_CURTA = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_RE_CANCELAR = re.compile(r"\b(?:cancel|apag|desfaz|remov|exclu)\w*\b")

ESQUEMA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "data": {"type": ["string", "null"]},
        "hora": {"type": ["string", "null"]},
    },
    "required": ["titulo", "data", "hora"],
}
TABELA = """
CREATE TABLE IF NOT EXISTS compromissos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    data TEXT NOT NULL,
    hora TEXT,
    criado_em TEXT NOT NULL
)
"""


def _agora() -> datetime:
    return datetime.now()


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def _formatar(data_iso: str, hora) -> str:
    dia = date.fromisoformat(data_iso)
    texto = f"{DIAS_EXIBICAO[dia.weekday()]}, {dia.strftime('%d/%m')}"
    return f"{texto} às {hora}" if hora else texto


def _banco(ctx):
    banco = ctx.servico("db_service")
    banco.executar_comando(TABELA)
    return banco


# ---------------------------------------------------------------------------
# Criar
# ---------------------------------------------------------------------------

def _extrair(ctx, texto):
    hoje = _agora().date()
    prompt = obter_catalogo().skill("agenda").prompt("extracao", hoje=hoje.isoformat(), dia_semana=NOMES_DIAS[hoje.weekday()])
    modelo = ctx.servico("llm_local")
    dados = ctx.repetir(
        custom_logger.cronometrado("extracao_agenda", modelo.gerar_json),
        (prompt, texto),
        mensagem_espera_voz="Estou tentando entender o compromisso novamente.",
        nome_servico="Agenda",
    ) if ctx.repetir else modelo.gerar_json(prompt, texto)
    return dados if isinstance(dados, dict) else {}


def _validar(dados):
    titulo = " ".join(str(dados.get("titulo") or "").split())[:120]
    data_iso = dados.get("data")
    try:
        data_iso = date.fromisoformat(str(data_iso)).isoformat() if data_iso else None
    except ValueError:
        data_iso = None
    hora = dados.get("hora")
    correspondencia = _RE_HORA.match(str(hora or ""))
    hora = f"{int(correspondencia.group(1)):02d}:{correspondencia.group(2)}" if correspondencia else None
    return titulo, data_iso, hora


def _criar(ctx, texto):
    titulo, data_iso, hora = _validar(_extrair(ctx, texto))
    if not titulo:
        return Resposta("Não entendi qual é o compromisso. Pode repetir? Exemplo: \"dentista quinta às 14h\".")
    if not data_iso:
        return Resposta(f"Para quando é \"{titulo}\"? Diga a data, por exemplo \"amanhã às 14h\".",
                        pendencia={"etapa": "data", "titulo": titulo})
    _banco(ctx).executar_comando(
        "INSERT INTO compromissos (titulo, data, hora, criado_em) VALUES (?, ?, ?, ?)",
        (titulo, data_iso, hora, _agora().isoformat(timespec="seconds")),
    )
    aviso = " Atenção: essa data já passou." if date.fromisoformat(data_iso) < _agora().date() else ""
    return Resposta(f"Anotado na agenda: {titulo} — {_formatar(data_iso, hora)}.{aviso}")


# ---------------------------------------------------------------------------
# Consultar
# ---------------------------------------------------------------------------

def periodo(texto: str, hoje: date):
    """(início, fim, descrição) a partir do texto; padrão: próximos 7 dias."""
    t = _normalizar(texto)
    if "amanha" in t:
        dia = hoje + timedelta(days=1)
        return dia, dia, f"amanhã ({dia.strftime('%d/%m')})"
    if "hoje" in t or "pra hoje" in t:
        return hoje, hoje, f"hoje ({hoje.strftime('%d/%m')})"
    data = _RE_DATA_CURTA.search(t)
    if data:
        dia_n, mes_n, ano_n = int(data.group(1)), int(data.group(2)), data.group(3)
        ano = (int(ano_n) + 2000 if len(ano_n) == 2 else int(ano_n)) if ano_n else hoje.year
        try:
            dia = date(ano, mes_n, dia_n)
            return dia, dia, dia.strftime("%d/%m")
        except ValueError:
            pass
    for indice, nome in enumerate(DIAS):
        if re.search(rf"\b{nome}\b", t):
            dia = hoje + timedelta(days=(indice - hoje.weekday()) % 7)
            return dia, dia, f"{NOMES_DIAS[indice]} ({dia.strftime('%d/%m')})"
    if "mes" in t:
        return hoje, hoje + timedelta(days=30), "dos próximos 30 dias"
    return hoje, hoje + timedelta(days=6), "dos próximos 7 dias"


def _consultar(ctx, texto):
    inicio, fim, descricao = periodo(texto, _agora().date())
    linhas = _banco(ctx).executar_consulta(
        "SELECT titulo, data, hora FROM compromissos WHERE data BETWEEN ? AND ? ORDER BY data, hora IS NULL, hora",
        (inicio.isoformat(), fim.isoformat()),
    )
    if not linhas:
        return Resposta(f"Nenhum compromisso {descricao}." if descricao.startswith("dos") else f"Nenhum compromisso para {descricao}.")
    itens = "\n".join(f"- {_formatar(d, h)}: {t}" if inicio != fim else f"- {h or 'dia todo'}: {t}" for t, d, h in linhas)
    titulo = f"Seus compromissos {descricao}:" if descricao.startswith("dos") else f"Seus compromissos para {descricao}:"
    return Resposta(f"{titulo}\n{itens}", fala=f"Você tem {len(linhas)} compromisso{'s' if len(linhas) > 1 else ''}. Veja no chat.")


# ---------------------------------------------------------------------------
# Cancelar o último
# ---------------------------------------------------------------------------

def _cancelar_ultimo(ctx):
    linhas = _banco(ctx).executar_consulta("SELECT id, titulo, data, hora FROM compromissos ORDER BY id DESC LIMIT 1")
    if not linhas:
        return Resposta("Não há compromisso na agenda para cancelar.")
    ident, titulo, data_iso, hora = linhas[0]
    return Resposta(f"Cancelar \"{titulo}\" ({_formatar(data_iso, hora)})? Responda \"sim\" para apagar ou \"não\" para manter.",
                    pendencia={"etapa": "cancelar", "id": ident, "titulo": titulo})


# ---------------------------------------------------------------------------
# Entradas do motor
# ---------------------------------------------------------------------------

def executar(ctx, texto, decisao):
    acao = decisao.get("acao")
    if acao == "corrigir" or (acao != "criar" and _RE_CANCELAR.search(_normalizar(texto)) and "compromisso" in _normalizar(texto)):
        return _cancelar_ultimo(ctx)
    if acao == "criar":
        return _criar(ctx, texto)
    return _consultar(ctx, texto)


def responder_pendencia(ctx, texto, dados):
    if dados.get("etapa") == "cancelar":
        if _normalizar(texto).strip(" .,!") in RESPOSTAS_SIM:
            _banco(ctx).executar_comando("DELETE FROM compromissos WHERE id = ?", (dados["id"],))
            return Resposta(f"Compromisso \"{dados['titulo']}\" cancelado.")
        return Resposta("Mantido na agenda.")
    # etapa "data": a resposta completa o pedido anterior
    return _criar(ctx, f"{dados['titulo']} {texto}")
