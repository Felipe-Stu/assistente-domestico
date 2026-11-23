"""
Medições da V4.1 contra o Ollama real:
  - M04: tempo até o chat aceitar texto, tempo da primeira resposta e tempo até a memória semântica ficar pronta.
  - M03: orquestrador e extração de compras com e sem JSON Schema (validade, acerto e latência).

Não grava no banco: a medição de início só envia uma consulta de estoque (somente leitura) e a
extração usa ShoppingAssistant.preparar_compra, que não grava. Os logs em Logs/ recebem linhas normalmente.

Uso (na raiz do assistente, com o Ollama em execução):
    python scripts/medir_v41.py
    python scripts/medir_v41.py --so-inicio
    python scripts/medir_v41.py --so-extracao --repeticoes 1
    python scripts/medir_v41.py --so-orquestrador --modelo gemma --raciocinio nao --modos esquema

--modelo escolhe o orquestrador (gemma = gemma4:e4b, qwen = qwen2.5-coder:7b) e --raciocinio liga ou
desliga o "think" do Ollama. Cada chamada registra tokens e tempos informados pelo próprio Ollama.
"""
import argparse
import json
import queue
import subprocess
import sys
import threading
import time
import unicodedata
from datetime import datetime
from importlib import metadata
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASTA_SAIDA_PADRAO = ROOT.parent / "Planejamento" / "medicoes"


def normalizar(texto):
    sem = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in sem if not unicodedata.combining(c)).lower().strip()


# =============================================================================
# M04 — início do sistema
# =============================================================================

def medir_inicio(rodadas, pasta, limite=150.0):
    resultados = []
    for rodada in range(1, rodadas + 1):
        print(f"\n[M04] Rodada {rodada}/{rodadas}: iniciando app/main.py ...", flush=True)
        log_erro = open(pasta / f"inicio-stderr-{rodada}.txt", "w", encoding="utf-8")
        t0 = time.perf_counter()
        proc = subprocess.Popen(
            [sys.executable, "-u", "app/main.py"], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log_erro,
            encoding="utf-8", errors="replace",
        )
        eventos = queue.Queue()

        def ler():
            for linha in proc.stdout:
                eventos.put((time.perf_counter() - t0, linha.strip()))
            eventos.put((time.perf_counter() - t0, None))

        threading.Thread(target=ler, daemon=True).start()
        r = {"rodada": rodada, "pronto_s": None, "resposta_s": None, "memoria_s": None,
             "memoria_ok": None, "resposta": None, "erro": None}
        enviado = False
        while time.perf_counter() - t0 < limite:
            try:
                t, linha = eventos.get(timeout=1.0)
            except queue.Empty:
                continue
            if linha is None:
                r["erro"] = "processo encerrou antes do fim da medição"
                break
            try:
                msg = json.loads(linha)
            except json.JSONDecodeError:
                continue
            tipo, carga = msg.get("type"), msg.get("payload") or {}
            texto = carga.get("message") or carga.get("text") or ""
            if tipo == "system_ready" and r["pronto_s"] is None:
                r["pronto_s"] = round(t, 2)
                print(f"[M04]   chat pronto em {t:.1f} s; enviando consulta de estoque", flush=True)
                proc.stdin.write(json.dumps({"type": "send_text", "payload": {"text": "Ainda tenho leite em casa?"}}) + "\n")
                proc.stdin.flush()
                enviado = True
            elif tipo == "assistant_message" and enviado and r["resposta_s"] is None:
                r["resposta_s"] = round(t, 2)
                r["resposta"] = texto[:120]
                print(f"[M04]   primeira resposta em {t:.1f} s", flush=True)
            elif tipo == "debug_log" and "Memória semântica" in texto and r["memoria_s"] is None:
                r["memoria_s"] = round(t, 2)
                r["memoria_ok"] = "pronta" in texto
                print(f"[M04]   memória semântica {'pronta' if r['memoria_ok'] else 'FALHOU'} em {t:.1f} s", flush=True)
            elif tipo == "error":
                r["erro"] = texto
            if r["pronto_s"] and r["resposta_s"] and r["memoria_s"]:
                break
        else:
            r["erro"] = r["erro"] or f"limite de {limite:.0f} s atingido"

        try:
            proc.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        log_erro.close()
        resultados.append(r)
    return resultados


# =============================================================================
# M03 — saída estruturada
# =============================================================================

CASOS_ORQUESTRADOR = [
    ("Me dê uma dica rápida para economizar energia elétrica.", {"geral", "outro"}, {"consultar"}),
    ("Qual é a capital da Austrália?", {"geral", "outro"}, {"consultar"}),
    ("Como faço arroz soltinho?", {"geral", "outro"}, {"consultar"}),
    ("Pesquise na internet o preço do frango e compare três mercados", {"compras"}, {"consultar"}),
    ("Corrige a compra de ontem, o leite foi 4,99", {"compras"}, {"corrigir"}),
    ("Tá faltando detergente aqui", {"inventario"}, {"consultar", "corrigir"}),
    ("Marquei dentista pra quinta às 14h", {"agenda"}, {"criar"}),
    ("Eu prefiro café sem açúcar e sempre compro a marca Pilão", {"geral", "outro", "compras"}, {"criar", "consultar"}),
]

# (frase, mercado esperado (trecho) ou None, nº de itens, total esperado, embalagem esperada?)
CASOS_COMPRAS = [
    ("fui ao mercado Moreschi e comprei peito de frango por r$ 16,99 o quilo comprei 3 kg 124 G comprei também "
     "detergente Minuano por r$ 2,69 comprei chiclete Trident por r$ 3,49 comprei também cebola por r$ 7,49 o quilo "
     "comprei 484 g e também comprei alho por r$ 27,99 o quilo comprei 106 gramas", "moreschi", 5, 65.86, False),
    ("Comprei 2 pacotes de café de 500g por R$ 18,90 cada no Mercado Central", "central", 1, 37.80, True),
    ("Dia 18/07/2026 eu comprei no mercado Max Atacadista 1 salgadinho elma chips de 400g por R$14.99, "
     "4 chocolates kitkat por R$2.99 cada, 4 petiscos para gatos whiskas 80g por R$18.49 cada",
     "max", 3, 100.91, True),
    ("Comprei hoje no Engenho Santo Mário dois pastéis e uma coca-cola, por R$39.00 reais. "
     "O valor da coca foi de 6 reais, dos pasteis eu não lembro", "engenho", 2, 39.00, False),
    ("Comprei ontem um pacote de arroz de 5 kg por 27,90", None, 1, 27.90, True),
    ("Anotar que gastei no restaurante costela de chão o valor de 150 reais em um almoço de família",
     "costela", 1, 150.00, False),
]


class VetorNulo:
    def upsert_documents(self, *_a, **_k):
        return True

    def delete_documents(self, *_a, **_k):
        return True


def info_ollama():
    import ollama
    info = {"biblioteca": None, "modelos": [], "erro": None}
    try:
        info["biblioteca"] = metadata.version("ollama")
    except Exception:
        pass
    try:
        lista = ollama.Client(timeout=5).list()
        modelos = lista.get("models", []) if isinstance(lista, dict) else getattr(lista, "models", [])
        for m in modelos:
            nome = m.get("model") or m.get("name") if isinstance(m, dict) else getattr(m, "model", None)
            info["modelos"].append(nome)
    except Exception as e:
        info["erro"] = str(e)
    return info


RACIOCINIO = {"padrao": None, "nao": False, "sim": True}


def patches_modelo(llm_provider, cfg):
    """Fixa o modelo do orquestrador e o raciocínio durante a chamada."""
    return (mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", cfg["modelo"] == "qwen"),
            mock.patch.object(llm_provider, "OLLAMA_RACIOCINIO", RACIOCINIO[cfg["raciocinio"]]))


def metricas(llm_provider):
    return dict(llm_provider.ULTIMA_CHAMADA) if getattr(llm_provider, "ULTIMA_CHAMADA", None) else {}


def texto_metricas(m):
    if not m:
        return "sem LLM"
    return (f"tok={m.get('tokens_gerados')} rac={m.get('chars_raciocinio')}c "
            f"prompt={m.get('s_prompt')}s ger={m.get('s_geracao')}s")


def medir_orquestrador(repeticoes, modos, cfg):
    from services import gemma_service, llm_provider
    from services.intent_router import rotear_por_regras

    resultados = []
    print("\n[M03] Aquecendo o modelo (carga na VRAM, fora da medição)...", flush=True)
    try:
        p1, p2 = patches_modelo(llm_provider, cfg)
        with p1, p2:
            gemma_service.orquestrar_requisicao("Olá, tudo bem com você hoje?")
            print(f"[M03]   aquecido: {texto_metricas(metricas(llm_provider))}", flush=True)
    except Exception as e:
        print(f"[M03]   aquecimento falhou: {e}", flush=True)

    for frase, contextos, acoes in CASOS_ORQUESTRADOR:
        if rotear_por_regras(frase) is not None:
            print(f"[M03]   AVISO: '{frase}' é resolvida por regra; o LLM não será chamado", flush=True)
        for rep in range(repeticoes):
            for modo in modos:
                p1, p2 = patches_modelo(llm_provider, cfg)
                with mock.patch.object(llm_provider, "OLLAMA_SAIDA_ESTRUTURADA", modo == "esquema"), p1, p2:
                    llm_provider.ULTIMA_CHAMADA.clear()
                    t0 = time.perf_counter()
                    try:
                        d = gemma_service.orquestrar_requisicao(frase)
                        erro = None
                    except Exception as e:
                        d, erro = {}, f"{type(e).__name__}: {e}"[:200]
                    dt = time.perf_counter() - t0
                    m = metricas(llm_provider)
                acerto = (not erro) and d.get("contexto") in contextos and d.get("acao") in acoes
                resultados.append({"frase": frase, "modo": modo, "rep": rep + 1, "segundos": round(dt, 2),
                                   "valido": erro is None, "acerto": bool(acerto), "decisao": d, "erro": erro,
                                   "metricas": m})
                print(f"[M03]   {modo:7} {dt:5.1f}s {'ok ' if erro is None else 'ERR'} "
                      f"{'acerto' if acerto else 'errou '} {d.get('contexto')}/{d.get('acao')} "
                      f"[{texto_metricas(m)}] :: {frase[:40]}", flush=True)
    return resultados


def medir_compras(repeticoes, modos, cfg):
    from services import llm_provider
    from services.llm_provider import LocalLLMProvider, MODELO_AVANCADO, MODELO_PADRAO
    from services.shopping_assistant import ShoppingAssistant

    modelo = MODELO_AVANCADO if cfg["modelo"] == "qwen" else MODELO_PADRAO
    assistente = ShoppingAssistant(db_service=None, llm_provider=LocalLLMProvider(modelo=modelo),
                                   vector_store=VetorNulo())
    resultados = []
    for frase, mercado, n_itens, total, embalagem in CASOS_COMPRAS:
        for rep in range(repeticoes):
            for modo in modos:
                with mock.patch.object(llm_provider, "OLLAMA_SAIDA_ESTRUTURADA", modo == "esquema"), \
                        mock.patch.object(llm_provider, "OLLAMA_RACIOCINIO", RACIOCINIO[cfg["raciocinio"]]):
                    llm_provider.ULTIMA_CHAMADA.clear()
                    t0 = time.perf_counter()
                    try:
                        prep = assistente.preparar_compra(frase)
                        erro = None
                    except Exception as e:
                        prep, erro = {"compras": [], "duvidas": []}, f"{type(e).__name__}: {e}"[:200]
                    dt = time.perf_counter() - t0
                compras = prep["compras"]
                itens = [i for c in compras for i in c.get("itens", [])]
                soma = round(sum(i.get("valor_total", 0) for i in itens), 2)
                mercados = " ".join(normalizar(c.get("estabelecimento")) for c in compras)
                checagens = {
                    "itens": len(itens) == n_itens,
                    "total": abs(soma - total) <= 0.05,
                    "mercado": (mercado in mercados) if mercado else ("Mercado não informado." in prep["duvidas"]),
                    "embalagem": (any(i.get("embalagem_quantidade") for i in itens) if embalagem else True),
                }
                resultados.append({
                    "frase": frase, "modo": modo, "rep": rep + 1, "segundos": round(dt, 2), "erro": erro,
                    "checagens": checagens, "acerto": erro is None and all(checagens.values()),
                    "n_itens": len(itens), "soma": soma, "duvidas": prep["duvidas"], "metricas": metricas(llm_provider),
                    "itens": [{k: i.get(k) for k in ("produto", "quantidade", "unidade", "valor_unitario",
                                                     "valor_total", "embalagem_quantidade", "embalagem_unidade")}
                              for i in itens],
                })
                falhas = [k for k, v in checagens.items() if not v]
                print(f"[M03]   {modo:7} {dt:5.1f}s itens={len(itens)}/{n_itens} soma={soma:.2f}/{total:.2f} "
                      f"{'OK' if not falhas and not erro else 'falhou: ' + ', '.join(falhas or [erro])} :: {frase[:40]}",
                      flush=True)
    return resultados


# =============================================================================
# Relatório
# =============================================================================

def mediana(valores):
    v = sorted(x for x in valores if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else round((v[m - 1] + v[m]) / 2, 2)


def resumo_md(dados):
    linhas = [f"# Medição V4.1 — {dados['quando']}", "",
              f"Python {dados['python']} · biblioteca ollama {dados['ollama'].get('biblioteca')} · "
              f"modelos: {', '.join(m for m in dados['ollama'].get('modelos', []) if m) or '?'}", "",
              f"Configuração: orquestrador **{dados['config']['modelo']}**, raciocínio **{dados['config']['raciocinio']}**", ""]
    if dados["ollama"].get("aviso"):
        linhas += [f"> **Atenção:** {dados['ollama']['aviso']}.", ""]
    if dados.get("inicio"):
        linhas += ["## M04 — início", "", "| Rodada | Chat pronto | 1ª resposta | Memória pronta | Erro |", "|---|---|---|---|---|"]
        for r in dados["inicio"]:
            linhas.append(f"| {r['rodada']} | {r['pronto_s']} s | {r['resposta_s']} s | {r['memoria_s']} s "
                          f"({'ok' if r['memoria_ok'] else 'falhou'}) | {r['erro'] or ''} |")
        linhas += ["", "Antes da V4.1 o chat só ficava pronto depois da memória; a coluna \"Memória pronta\" "
                   "é uma estimativa do tempo de início da versão anterior.", ""]
    for chave, titulo in (("orquestrador", "M03 — orquestrador"), ("compras", "M03 — extração de compras")):
        res = dados.get(chave)
        if not res:
            continue
        linhas += [f"## {titulo}", "", "| Modo | Execuções | Válidas | Acertos | Mediana (s) | Tokens gerados | "
                   "Raciocínio (caracteres) | Prompt (s) | Geração (s) |", "|---|---|---|---|---|---|---|---|---|"]
        for modo in sorted({r["modo"] for r in res}):
            rr = [r for r in res if r["modo"] == modo]
            validas = sum(1 for r in rr if not r.get("erro"))

            def med(chave):
                return mediana([(r.get("metricas") or {}).get(chave) for r in rr])
            linhas.append(f"| {modo} | {len(rr)} | {validas} | {sum(r['acerto'] for r in rr)} | "
                          f"{mediana([r['segundos'] for r in rr])} | {med('tokens_gerados')} | "
                          f"{med('chars_raciocinio')} | {med('s_prompt')} | {med('s_geracao')} |")
        erros = [r for r in res if not r["acerto"]]
        if erros:
            linhas += ["", "Casos que falharam:", ""]
            for r in erros:
                det = r.get("erro") or r.get("decisao") or {k: v for k, v in r.get("checagens", {}).items() if not v}
                linhas.append(f"- `{r['modo']}` — {r['frase'][:70]} → {det}")
        linhas.append("")
    return "\n".join(linhas)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--so-inicio", action="store_true")
    ap.add_argument("--so-extracao", action="store_true")
    ap.add_argument("--rodadas", type=int, default=2, help="rodadas da medição de início")
    ap.add_argument("--repeticoes", type=int, default=2, help="repetições por frase no orquestrador")
    ap.add_argument("--so-orquestrador", action="store_true", help="mede só o orquestrador (sem início e extração)")
    ap.add_argument("--modelo", choices=["gemma", "qwen"], default="gemma")
    ap.add_argument("--raciocinio", choices=["padrao", "nao", "sim"], default="padrao",
                    help="'think' do Ollama: padrao (não envia), nao (desliga) ou sim (liga)")
    ap.add_argument("--modos", default="json,esquema", help="lista separada por vírgula: json, esquema")
    ap.add_argument("--saida", type=Path, default=PASTA_SAIDA_PADRAO)
    a = ap.parse_args()
    cfg = {"modelo": a.modelo, "raciocinio": a.raciocinio}

    a.saida.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M") + f"-{a.modelo}-raciocinio-{a.raciocinio}"
    dados = {"quando": datetime.now().strftime("%d/%m/%Y %H:%M"), "python": sys.version.split()[0], "ollama": {},
             "config": cfg}

    if not a.so_extracao and not a.so_orquestrador:
        dados["inicio"] = medir_inicio(a.rodadas, a.saida)

    if not a.so_inicio:
        dados["ollama"] = info_ollama()
        print(f"\n[M03] ollama {dados['ollama']['biblioteca']} · modelos {dados['ollama']['modelos']}", flush=True)
        versao = dados["ollama"]["biblioteca"] or "0"
        try:
            antiga = tuple(int(x) for x in versao.split(".")[:2]) < (0, 4)
        except ValueError:
            antiga = False
        if antiga:
            dados["ollama"]["aviso"] = "biblioteca anterior à 0.4: o modo 'esquema' recai em JSON simples"
            print("[M03] AVISO: biblioteca ollama anterior à 0.4. O modo 'esquema' vai recair em JSON simples;"
                  " rode 'pip install -U ollama' para medir o esquema de verdade.", flush=True)
        if dados["ollama"]["erro"]:
            print(f"[M03] Ollama indisponível: {dados['ollama']['erro']}. Rode 'ollama serve' e tente de novo.")
        else:
            modos = [m.strip() for m in a.modos.split(",") if m.strip() in ("json", "esquema")] or ["esquema"]
            dados["orquestrador"] = medir_orquestrador(a.repeticoes, modos, cfg)
            if not a.so_orquestrador:
                dados["compras"] = medir_compras(1, modos, cfg)

    (a.saida / f"v41-{carimbo}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    md = resumo_md(dados)
    (a.saida / f"v41-{carimbo}.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"\nResultados em {a.saida}")


if __name__ == "__main__":
    main()
