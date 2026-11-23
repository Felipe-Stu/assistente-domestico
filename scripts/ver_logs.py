"""
Lê o registro de eventos (Logs/eventos-AAAA-MM-DD.jsonl) em formato legível (M26).

Exemplos:
    python scripts/ver_logs.py                      # eventos de hoje
    python scripts/ver_logs.py --dia 2026-11-22     # eventos de um dia
    python scripts/ver_logs.py --req 3f9a1c2b       # uma requisição do início ao fim
    python scripts/ver_logs.py --nivel ERROR        # só erros
    python scripts/ver_logs.py --etapas             # tempo por etapa (mediana, p95, máximo)
"""
import argparse
import json
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from core.config import LOGS_DIR  # noqa: E402
from services.logger_service import nome_arquivo_do_dia  # noqa: E402

NIVEIS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
CAMPOS_FIXOS = {"ts", "nivel", "req", "componente", "evento", "mensagem"}


def ler_eventos(caminho: Path):
    if not caminho.exists():
        return []
    eventos = []
    with open(caminho, encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue
            try:
                eventos.append(json.loads(linha))
            except json.JSONDecodeError:
                continue  # Linha cortada (ex.: app encerrado no meio da escrita)
    return eventos


def filtrar(eventos, req=None, componente=None, nivel_minimo=None):
    minimo = NIVEIS.index(nivel_minimo) if nivel_minimo else 0
    for evento in eventos:
        if req and evento.get("req") != req:
            continue
        if componente and evento.get("componente") != componente:
            continue
        nivel = evento.get("nivel")
        if nivel in NIVEIS and NIVEIS.index(nivel) < minimo:
            continue
        yield evento


def formatar(evento) -> str:
    hora = evento.get("ts", "")[11:23]
    req = evento.get("req") or "-"
    extras = " ".join(f"{k}={v}" for k, v in evento.items() if k not in CAMPOS_FIXOS and k != "erro")
    texto = f"{hora} {evento.get('nivel', ''):<7} {req:<8} {evento.get('componente', ''):<20} {evento.get('evento', '')}"
    if evento.get("mensagem"):
        texto += f" | {evento['mensagem']}"
    if extras:
        texto += f" [{extras}]"
    return texto


def percentil(valores, p):
    ordenados = sorted(valores)
    indice = max(0, min(len(ordenados) - 1, round(p / 100 * (len(ordenados) - 1))))
    return ordenados[indice]


def resumo_etapas(eventos):
    duracoes = {}
    for evento in eventos:
        if evento.get("evento") == "etapa" and "duracao_ms" in evento:
            duracoes.setdefault(evento.get("etapa", "?"), []).append(evento["duracao_ms"])
        elif evento.get("evento") == "requisicao_fim" and "duracao_ms" in evento:
            duracoes.setdefault("(requisição inteira)", []).append(evento["duracao_ms"])
    linhas = [f"{'etapa':<22} {'n':>5} {'mediana':>9} {'p95':>9} {'máximo':>9}"]
    for nome, valores in sorted(duracoes.items()):
        linhas.append(
            f"{nome:<22} {len(valores):>5} {statistics.median(valores):>7.0f}ms "
            f"{percentil(valores, 95):>7.0f}ms {max(valores):>7.0f}ms"
        )
    return "\n".join(linhas) if duracoes else "Nenhuma etapa registrada."


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mostra o registro de eventos do assistente.")
    parser.add_argument("--dia", default=date.today().isoformat(), help="AAAA-MM-DD (padrão: hoje)")
    parser.add_argument("--req", help="identificador da requisição")
    parser.add_argument("--componente", help="ex.: main, db_service, shopping_assistant")
    parser.add_argument("--nivel", choices=NIVEIS, help="nível mínimo")
    parser.add_argument("--etapas", action="store_true", help="resumo do tempo por etapa")
    parser.add_argument("--pasta", default=str(LOGS_DIR), help="pasta dos logs")
    args = parser.parse_args(argv)

    caminho = Path(args.pasta) / nome_arquivo_do_dia(date.fromisoformat(args.dia))
    eventos = list(filtrar(ler_eventos(caminho), args.req, args.componente, args.nivel))
    if not eventos:
        print(f"Nenhum evento em {caminho} com esses filtros.")
        return 0
    if args.etapas:
        print(resumo_etapas(eventos))
    else:
        for evento in eventos:
            print(formatar(evento))
    return 0


if __name__ == "__main__":
    sys.exit(main())
