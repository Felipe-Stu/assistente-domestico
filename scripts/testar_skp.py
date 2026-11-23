"""
Teste do SKP no PC: Claude (API), biblioteca e Qwen local como reserva. Nenhuma chave é exibida.

    python scripts/testar_skp.py

1. Chamada mínima ao Claude (fração de centavo): confirma chave, modelo e cota.
2. Indexa a biblioteca (só o que mudou).
3. Faz a mesma pergunta de programação pelo Claude e pelo Qwen local (Ollama aberto).
Relatório em ../Planejamento/medicoes/skp-AAAAMMDD-HHMM.md
"""
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PERGUNTA = "Onde fica o roteador por regras do assistente e como eu adiciono um gatilho novo para uma skill?"
PASTA_SAIDA = ROOT.parent / "Planejamento" / "medicoes"


def criar_claude():
    import core.config as c
    from services.claude_service import ClaudeService
    return ClaudeService(c.ANTHROPIC_API_KEY, c.CLAUDE_MODELO, c.CLAUDE_API_VERSAO, c.CLAUDE_ESTADO_ARQUIVO,
                         limite_mensal_usd=c.CLAUDE_LIMITE_MENSAL_USD, preco_entrada=c.CLAUDE_PRECO_ENTRADA,
                         preco_saida=c.CLAUDE_PRECO_SAIDA, hora_reteste=c.CLAUDE_HORA_RETESTE,
                         max_tokens=c.CLAUDE_MAX_TOKENS)


def perguntar(claude, biblioteca):
    from core.skills import Contexto, motor, obter_catalogo
    from services.llm_provider import MODELO_AVANCADO, LocalLLMProvider
    servicos = {"llm_programacao": LocalLLMProvider(modelo=MODELO_AVANCADO, temperatura=0.2),
                "biblioteca": biblioteca, "historico": []}
    if claude is not None:
        servicos["claude"] = claude
    ctx = Contexto(servicos=servicos, repetir=lambda f, a, **_k: f(*a))
    t0 = time.perf_counter()
    try:
        texto = motor.executar(obter_catalogo().skill("programacao"), ctx, PERGUNTA, {"acao": "consultar"}).texto
    except Exception as e:
        texto = f"ERRO: {type(e).__name__}: {e}"
    return round(time.perf_counter() - t0, 1), texto


def main():
    linhas = [f"# SKP — teste de {datetime.now().strftime('%d/%m/%Y %H:%M')}", ""]
    claude = criar_claude()

    print("1/3 Claude: chamada mínima...")
    if not claude.configurado():
        situacao = "não configurado (sem ANTHROPIC_API_KEY no .env)"
    else:
        t0 = time.perf_counter()
        try:
            claude.gerar_texto("Responda só com a palavra ok.", "ok?", max_tokens=16)
            situacao = f"ok em {time.perf_counter() - t0:.1f} s (modelo {claude.modelo})"
        except Exception as e:
            situacao = f"indisponível: {getattr(e, 'motivo', e)}"
    estado = claude.estado()
    print("   ", situacao)
    linhas += ["## Claude", "", f"- Situação: {situacao}",
               f"- Gasto estimado no mês: US$ {estado.get('gasto_usd', 0):.4f} "
               f"({estado.get('tokens_entrada', 0)} tokens de entrada, {estado.get('tokens_saida', 0)} de saída)", ""]

    print("2/3 Biblioteca: indexando...")
    from scripts.indexar_biblioteca import criar_biblioteca
    biblioteca = None
    try:
        biblioteca = criar_biblioteca()
        contagem = biblioteca.indexar()
        trechos = biblioteca.buscar(PERGUNTA)
        info = f"{contagem['arquivos']} arquivos, {contagem['trechos']} trechos; {len(trechos)} trechos encontrados para a pergunta"
    except Exception as e:
        trechos, info = [], f"falhou: {type(e).__name__}: {e}"
    print("   ", info)
    linhas += ["## Biblioteca", "", f"- {info}"] + [f"  - {t['fonte']}" for t in trechos] + [""]

    linhas += ["## Mesma pergunta pelos dois provedores", "", f"Pergunta: {PERGUNTA}", ""]
    for nome, servico in (("Claude", claude if claude.configurado() else None), ("Qwen local", None)):
        if nome == "Claude" and servico is None:
            continue
        print(f"3/3 Pergunta pelo {nome}...")
        segundos, texto = perguntar(servico, biblioteca)
        print(f"    {segundos} s")
        linhas += [f"### {nome} — {segundos} s", "", texto[:1500] + ("…" if len(texto) > 1500 else ""), ""]

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    arquivo = PASTA_SAIDA / f"skp-{datetime.now().strftime('%Y%m%d-%H%M')}.md"
    arquivo.write_text("\n".join(linhas), encoding="utf-8")
    print(f"\nRelatório: {arquivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
