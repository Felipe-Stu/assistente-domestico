"""
Períodos ditos em português → intervalos de datas, por regra fixa (sem modelo).

encontrar_periodos("gastei mais em outubro ou novembro?", hoje) → [Periodo(out), Periodo(nov)]
Cada período tem início e fim inclusivos e um rótulo para a resposta ("em outubro de 2026").
"""
import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
         "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10,
         "nov": 11, "dez": 12}
NOMES_MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
               "outubro", "novembro", "dezembro"]
NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
           "oito": 8, "nove": 9, "dez": 10, "doze": 12, "quinze": 15, "trinta": 30, "sessenta": 60, "noventa": 90}


@dataclass(frozen=True)
class Periodo:
    inicio: date
    fim: date
    rotulo: str

    @property
    def inicio_iso(self) -> str:
        return self.inicio.isoformat()

    @property
    def fim_iso(self) -> str:
        return self.fim.isoformat()


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).lower().split())


def _fim_do_mes(ano: int, mes: int) -> date:
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def _mes(ano: int, mes: int, hoje: date, ano_explicito: bool) -> Periodo:
    rotulo = f"em {NOMES_MESES[mes]}" + (f" de {ano}" if ano_explicito or ano != hoje.year else "")
    return Periodo(date(ano, mes, 1), _fim_do_mes(ano, mes), rotulo)


def _data(dia: str, mes: str, ano: Optional[str], hoje: date) -> Optional[date]:
    a = int(ano) if ano else hoje.year
    if a < 100:
        a += 2000
    try:
        return date(a, int(mes), int(dia))
    except ValueError:
        return None


def _numero(palavra: str) -> Optional[int]:
    return int(palavra) if palavra.isdigit() else NUMEROS.get(palavra)


_PADROES = [
    # intervalo de datas: "de 01/10 a 15/11", "entre 01/10/2026 e 15/11/2026"
    ("intervalo", r"\b(?:de|entre|desde)\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(?:a|ate|e)\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"),
    ("desde_data", r"\bdesde\s+(?:o\s+dia\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"),
    ("data", r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"),
    ("ultimos", r"\b(?:nos\s+|nas\s+)?(?:ultim[oa]s|passad[oa]s)\s+(\d+|\w+)\s+(dias?|semanas?|mes(?:es)?|anos?)\b"),
    ("ultimos_inv", r"\b(\d+|\w+)\s+(dias?|semanas?|mes(?:es)?|anos?)\s+(?:atras|passad[oa]s)\b"),
    ("recente", r"\b(?:ultimamente|recentemente)\b"),
    ("hoje", r"\bhoje\b"),
    ("ontem", r"\bontem\b"),
    ("semana_passada", r"\bsemana\s+passada\b|\bultima\s+semana\b"),
    ("esta_semana", r"\b(?:est[ae]|ness[ae]|nest[ae])\s+semana\b"),
    ("mes_passado", r"\bmes\s+passado\b|\bultimo\s+mes\b"),
    ("este_mes", r"\b(?:est[ea]|ess[ea]|nest[ea]|ness[ea])\s+mes\b|\bmes\s+atual\b"),
    ("ano_passado", r"\bano\s+passado\b|\bultimo\s+ano\b"),
    ("este_ano", r"\b(?:est[ea]|ess[ea]|nest[ea]|ness[ea])\s+ano\b|\bano\s+atual\b"),
    ("desde_mes", r"\bdesde\s+(?:o\s+inicio\s+de\s+)?(" + "|".join(sorted(MESES, key=len, reverse=True)) + r")\b(?:\s+(?:de\s+)?(\d{4}))?"),
    ("mes", r"\b(" + "|".join(sorted(MESES, key=len, reverse=True)) + r")\b(?:\s+(?:de\s+)?(\d{4}))?"),
    ("ano", r"\b(20\d{2})\b"),
]


def _ultimos(qtd: Optional[int], unidade: str, hoje: date) -> Optional[Periodo]:
    if not qtd or qtd <= 0:
        return None
    if unidade.startswith("dia"):
        dias = qtd
    elif unidade.startswith("semana"):
        dias = qtd * 7
    elif unidade.startswith("mes"):
        dias = qtd * 30
    else:
        dias = qtd * 365
    nome = {"d": "dias", "s": "semanas", "m": "meses", "a": "anos"}[unidade[0]] if qtd > 1 else unidade.rstrip("s").replace("mese", "mes")
    return Periodo(hoje - timedelta(days=dias - 1), hoje, f"nos últimos {qtd} {nome}" if qtd > 1 else f"no último {nome}")


def _construir(tipo: str, g, hoje: date) -> Optional[Periodo]:
    if tipo == "intervalo":
        inicio, fim = _data(g[0], g[1], g[2], hoje), _data(g[3], g[4], g[5] or g[2], hoje)
        if inicio and fim and inicio <= fim:
            return Periodo(inicio, fim, f"de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}")
        return None
    if tipo == "desde_data":
        inicio = _data(g[0], g[1], g[2], hoje)
        return Periodo(inicio, hoje, f"desde {inicio:%d/%m/%Y}") if inicio and inicio <= hoje else None
    if tipo == "data":
        dia = _data(g[0], g[1], g[2], hoje)
        return Periodo(dia, dia, f"em {dia:%d/%m/%Y}") if dia else None
    if tipo in ("ultimos", "ultimos_inv"):
        return _ultimos(_numero(g[0]), g[1], hoje)
    if tipo == "recente":
        return Periodo(hoje - timedelta(days=29), hoje, "nos últimos 30 dias")
    if tipo == "hoje":
        return Periodo(hoje, hoje, "hoje")
    if tipo == "ontem":
        ontem = hoje - timedelta(days=1)
        return Periodo(ontem, ontem, "ontem")
    if tipo == "esta_semana":
        inicio = hoje - timedelta(days=hoje.weekday())
        return Periodo(inicio, hoje, "nesta semana")
    if tipo == "semana_passada":
        inicio = hoje - timedelta(days=hoje.weekday() + 7)
        return Periodo(inicio, inicio + timedelta(days=6), "na semana passada")
    if tipo == "este_mes":
        return Periodo(hoje.replace(day=1), hoje, "neste mês")
    if tipo == "mes_passado":
        fim = hoje.replace(day=1) - timedelta(days=1)
        return Periodo(fim.replace(day=1), fim, "no mês passado")
    if tipo == "este_ano":
        return Periodo(date(hoje.year, 1, 1), hoje, f"em {hoje.year}")
    if tipo == "ano_passado":
        ano = hoje.year - 1
        return Periodo(date(ano, 1, 1), date(ano, 12, 31), f"em {ano}")
    if tipo in ("mes", "desde_mes"):
        mes = MESES[g[0]]
        ano = int(g[1]) if g[1] else (hoje.year if mes <= hoje.month else hoje.year - 1)
        if tipo == "desde_mes":
            return Periodo(date(ano, mes, 1), hoje, f"desde {NOMES_MESES[mes]}" + (f" de {ano}" if ano != hoje.year else ""))
        return _mes(ano, mes, hoje, bool(g[1]))
    if tipo == "ano":
        ano = int(g[0])
        return Periodo(date(ano, 1, 1), date(ano, 12, 31), f"em {ano}")
    return None


# Abreviações curtas (mar, set...) só contam como mês ao lado de "de/em" ou de um ano, para não confundir palavras comuns
_ABREVIACOES_AMBIGUAS = {"mar", "set", "out", "mai", "jun", "jul", "nov", "dez", "abr", "ago", "fev", "jan"}


def encontrar_periodos(texto: str, hoje: Optional[date] = None) -> List[Periodo]:
    """Todos os períodos citados, na ordem em que aparecem; trechos já usados não são lidos de novo."""
    hoje = hoje or date.today()
    normal = _normalizar(texto)
    ocupado = [False] * len(normal)
    achados = []
    for tipo, padrao in _PADROES:
        for m in re.finditer(padrao, normal):
            if any(ocupado[m.start():m.end()]):
                continue
            if tipo == "mes" and m.group(1) in _ABREVIACOES_AMBIGUAS and not m.group(2):
                antes = normal[max(0, m.start() - 4):m.start()]
                if not re.search(r"\b(de|em|ou|e)\s$", antes):
                    continue
            periodo = _construir(tipo, m.groups(), hoje)
            if periodo is None:
                continue
            for i in range(m.start(), m.end()):
                ocupado[i] = True
            achados.append((m.start(), periodo))
    return [p for _, p in sorted(achados, key=lambda x: x[0])]


def primeiro_periodo(texto: str, hoje: Optional[date] = None) -> Optional[Periodo]:
    periodos = encontrar_periodos(texto, hoje)
    return periodos[0] if periodos else None
