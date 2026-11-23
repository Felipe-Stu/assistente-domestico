"""
SK0 do roadmap das skills — medir antes de mudar.

Roda no PC com o Ollama aberto. Não grava no banco (a extração usa preparar_compra, que só lê).

Mede:
  1. Escolha da skill para as frases de evals/casos.jsonl, em três modos:
       atual    — orquestrador do app (desde o SK2, escolha pelo catálogo)
       catalogo — saída estruturada com o nome das skills como enum (proposta do SK2)
       nativo   — chamada de ferramentas do Ollama, uma ferramenta por skill
  2. Extração de compras (evals/compras.jsonl) com o raciocínio desligado e ligado.
  3. Tempo de troca de modelo na VRAM.

Uso (na raiz do assistente):
    python scripts/avaliar.py                                   # tudo, com os modelos padrão
    python scripts/avaliar.py --modelos gemma4:e4b --modos atual,catalogo
    python scripts/avaliar.py --so-roteamento --sem-regras      # força o modelo em todas as frases
    python scripts/avaliar.py --so-extracao --raciocinio nao,sim
    python scripts/avaliar.py --so-troca

Modelos que não estiverem instalados são pulados com aviso (instale com `ollama pull <modelo>`).
Relatório em JSON e Markdown na pasta de medições do planejamento (ou --saida).
"""
import argparse
import json
import statistics
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ARQUIVO_CASOS = ROOT / "evals" / "casos.jsonl"
ARQUIVO_COMPRAS = ROOT / "evals" / "compras.jsonl"
PASTA_SAIDA_PADRAO = ROOT.parent / "Planejamento" / "medicoes"
MODELOS_PADRAO = ["gemma4:e4b", "qwen2.5:7b", "qwen2.5-coder:7b"]
MODOS = ["atual", "catalogo", "nativo"]
RACIOCINIO = {"padrao": None, "nao": False, "sim": True}


# =============================================================================
# Casos
# =============================================================================

def ler_jsonl(caminho: Path) -> list:
    with open(caminho, encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def carregar_casos(caminho: Path = ARQUIVO_CASOS, catalogo=None) -> list:
    """Lê e confere os casos: ids únicos e skills que existem no catálogo."""
    from core.skills import obter_catalogo
    catalogo = catalogo or obter_catalogo()
    casos = ler_jsonl(caminho)
    nomes = {s.nome for s in catalogo}
    ids = [c["id"] for c in casos]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{caminho}: ids repetidos")
    for caso in casos:
        for skill in [caso["skill"], *caso.get("aceita", [])]:
            if skill not in nomes:
                raise ValueError(f"{caminho}: caso {caso['id']} cita a skill '{skill}', que não existe")
    return casos


def normalizar(texto) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def acertou(caso: dict, skill, acao=None) -> bool:
    if skill not in [caso["skill"], *caso.get("aceita", [])]:
        return False
    if acao is not None and caso.get("acoes") and skill == caso["skill"]:
        return acao in caso["acoes"]
    return True


# =============================================================================
# Modos de escolha
# =============================================================================

class Avaliador:
    """Chama o modelo em cada modo. Os métodos `_escolher_*` podem ser trocados nos testes."""

    def __init__(self, catalogo=None, usar_regras: bool = True):
        from core.skills import obter_catalogo
        self.catalogo = catalogo or obter_catalogo()
        self.usar_regras = usar_regras

    # --- cada modo devolve (skill, acao, caminho, metricas) ---

    def _por_regra(self, frase):
        from services.intent_router import rotear_por_regras
        if not self.usar_regras:
            return None
        decisao = rotear_por_regras(frase)
        if decisao is None:
            return None
        return self.catalogo.por_contexto(decisao["contexto"]).nome, decisao["acao"], "regra", {}

    def _escolher_atual(self, frase, modelo):
        from services import gemma_service, llm_provider
        trocas = [mock.patch.object(llm_provider, "obter_modelo_ativo", lambda: modelo),
                  mock.patch.object(gemma_service, "obter_modelo_ativo", lambda: modelo)]
        if not self.usar_regras:
            trocas.append(mock.patch.object(gemma_service, "rotear_por_regras", lambda *_a, **_k: None))
        for t in trocas:
            t.start()
        try:
            llm_provider.ULTIMA_CHAMADA.clear()
            decisao = gemma_service.orquestrar_requisicao(frase)
            metricas = dict(llm_provider.ULTIMA_CHAMADA)
        finally:
            for t in reversed(trocas):
                t.stop()
        skill = self.catalogo.por_contexto(decisao.get("contexto"))
        return (skill.nome if skill else None), decisao.get("acao"), ("modelo" if metricas else "regra"), metricas

    def _escolher_catalogo(self, frase, modelo):
        regra = self._por_regra(frase)
        if regra:
            return regra
        from core.skills import seletor
        from services import llm_provider
        llm_provider.ULTIMA_CHAMADA.clear()
        dados = llm_provider.LocalLLMProvider(modelo=modelo, temperatura=0.1).gerar_json(
            seletor.prompt_catalogo(self.catalogo), frase, esquema=seletor.esquema_catalogo(self.catalogo), raciocinio=False
        )
        return dados.get("skill"), None, "modelo", dict(llm_provider.ULTIMA_CHAMADA)

    def _escolher_nativo(self, frase, modelo):
        regra = self._por_regra(frase)
        if regra:
            return regra
        import ollama
        from core.skills import seletor
        from services.llm_provider import _metricas_resposta
        parametros = {
            "model": modelo,
            "messages": [
                {"role": "system", "content": "Escolha a ferramenta (skill) que deve atender a mensagem do usuário. "
                                              "Chame exatamente uma ferramenta e não responda à mensagem."},
                {"role": "user", "content": frase},
            ],
            "tools": seletor.ferramentas_nativas(self.catalogo),
            "options": {"temperature": 0.1},
            "keep_alive": "30m",
            "think": False,
        }
        cliente = ollama.Client(timeout=120)
        try:
            resposta = cliente.chat(**parametros)
        except ollama.ResponseError as erro:
            if "think" not in str(erro).lower():
                raise
            parametros.pop("think")
            resposta = cliente.chat(**parametros)
        skill = seletor.skill_da_chamada_nativa(resposta, self.catalogo)
        metricas = _metricas_resposta(resposta, modelo, parametros.get("think"))
        metricas["sem_chamada"] = skill is None
        return (skill or seletor.SKILL_PADRAO), None, "modelo", metricas

    def escolher(self, modo, frase, modelo):
        return getattr(self, f"_escolher_{modo}")(frase, modelo)


def avaliar_roteamento(casos, modos, modelos, repeticoes=1, avaliador=None, log=print):
    avaliador = avaliador or Avaliador()
    resultados = []
    for modelo in modelos:
        for modo in modos:
            log(f"\n[escolha] modo={modo} modelo={modelo}")
            for caso in casos:
                for rep in range(repeticoes):
                    t0 = time.perf_counter()
                    try:
                        skill, acao, caminho, metricas = avaliador.escolher(modo, caso["frase"], modelo)
                        erro = None
                    except Exception as e:
                        skill, acao, caminho, metricas, erro = None, None, "erro", {}, f"{type(e).__name__}: {e}"[:200]
                    segundos = round(time.perf_counter() - t0, 3)
                    ok = erro is None and acertou(caso, skill, acao if modo == "atual" else None)
                    resultados.append({
                        "modo": modo, "modelo": modelo, "rep": rep + 1, "id": caso["id"], "grupo": caso.get("grupo", "atual"),
                        "frase": caso["frase"], "esperado": caso["skill"], "skill": skill, "acao": acao, "caminho": caminho,
                        "acerto": ok, "segundos": segundos, "erro": erro, "metricas": metricas,
                    })
                    log(f"  {'ok ' if ok else 'ERR'} {segundos:6.2f}s {caminho:6} {str(skill):18} "
                        f"(esperado {caso['skill']}) :: {caso['frase'][:48]}")
    return resultados


# =============================================================================
# Extração de compras
# =============================================================================

class _VetorNulo:
    def upsert_documents(self, *_a, **_k):
        return True

    def delete_documents(self, *_a, **_k):
        return True


def conferir_extracao(caso: dict, preparada: dict) -> dict:
    compras = preparada.get("compras", [])
    itens = [i for c in compras for i in c.get("itens", [])]
    soma = round(sum(float(i.get("valor_total") or 0) for i in itens), 2)
    mercados = " ".join(normalizar(c.get("estabelecimento")) for c in compras)
    return {
        "itens": len(itens) == caso["itens"],
        "total": abs(soma - caso["total"]) <= 0.05,
        "mercado": (caso["mercado"] in mercados) if caso["mercado"] else ("Mercado não informado." in preparada.get("duvidas", [])),
        "embalagem": any(i.get("embalagem_quantidade") for i in itens) if caso["embalagem"] else True,
        "_soma": soma,
        "_n_itens": len(itens),
    }


def avaliar_extracao(casos, modelos, raciocinios, repeticoes=1, log=print):
    from services import llm_provider
    from services.shopping_assistant import ShoppingAssistant
    resultados = []
    for modelo in modelos:
        assistente = ShoppingAssistant(db_service=None, llm_provider=llm_provider.LocalLLMProvider(modelo=modelo),
                                       vector_store=_VetorNulo())
        for raciocinio in raciocinios:
            log(f"\n[extração] modelo={modelo} raciocínio={raciocinio}")
            for caso in casos:
                for rep in range(repeticoes):
                    with mock.patch.object(llm_provider, "OLLAMA_RACIOCINIO", RACIOCINIO[raciocinio]):
                        llm_provider.ULTIMA_CHAMADA.clear()
                        t0 = time.perf_counter()
                        try:
                            preparada, erro = assistente.preparar_compra(caso["frase"]), None
                        except Exception as e:
                            preparada, erro = {"compras": [], "duvidas": []}, f"{type(e).__name__}: {e}"[:200]
                        segundos = round(time.perf_counter() - t0, 3)
                    checagens = conferir_extracao(caso, preparada)
                    ok = erro is None and all(v for k, v in checagens.items() if not k.startswith("_"))
                    resultados.append({"modelo": modelo, "raciocinio": raciocinio, "rep": rep + 1, "id": caso["id"],
                                       "acerto": ok, "segundos": segundos, "erro": erro, "checagens": checagens,
                                       "duvidas": preparada.get("duvidas", []), "metricas": dict(llm_provider.ULTIMA_CHAMADA)})
                    falhas = [k for k, v in checagens.items() if not k.startswith("_") and not v]
                    log(f"  {'ok ' if ok else 'ERR'} {segundos:6.2f}s itens={checagens['_n_itens']}/{caso['itens']} "
                        f"soma={checagens['_soma']:.2f}/{caso['total']:.2f} {', '.join(falhas or ([erro] if erro else []))}")
    return resultados


# =============================================================================
# Troca de modelo na VRAM
# =============================================================================

def _carregados(cliente) -> list:
    try:
        lista = cliente.ps()
        modelos = lista.get("models", []) if isinstance(lista, dict) else getattr(lista, "models", [])
        return [(m.get("model") if isinstance(m, dict) else getattr(m, "model", None)) for m in modelos]
    except Exception:
        return []


def medir_troca(modelos, log=print):
    """Descarrega tudo e chama os modelos em sequência (A, B, A, B): mede a carga e se eles convivem na VRAM."""
    import ollama
    from services.llm_provider import _metricas_resposta
    cliente = ollama.Client(timeout=300)
    for carregado in _carregados(cliente):
        try:
            cliente.generate(model=carregado, prompt="", keep_alive=0)
        except Exception:
            pass
    sequencia = (modelos * 2) if len(modelos) > 1 else modelos
    resultados = []
    log("\n[troca] sequência: " + " → ".join(sequencia))
    for modelo in sequencia:
        t0 = time.perf_counter()
        try:
            resposta = cliente.chat(model=modelo, messages=[{"role": "user", "content": "Responda só: ok"}],
                                    options={"num_predict": 4}, keep_alive="30m")
            m, erro = _metricas_resposta(resposta, modelo, None), None
        except Exception as e:
            m, erro = {}, f"{type(e).__name__}: {e}"[:200]
        segundos = round(time.perf_counter() - t0, 3)
        resultados.append({"modelo": modelo, "segundos": segundos, "s_carga": m.get("s_carga"),
                           "na_vram": _carregados(cliente), "erro": erro})
        log(f"  {modelo:20} {segundos:6.2f}s carga={m.get('s_carga')}s na VRAM: {resultados[-1]['na_vram']}")
    return resultados


# =============================================================================
# Relatório
# =============================================================================

def percentil(valores, p):
    v = sorted(x for x in valores if x is not None)
    if not v:
        return None
    return v[max(0, min(len(v) - 1, round(p / 100 * (len(v) - 1))))]


def resumir_roteamento(resultados):
    grupos = {}
    for r in resultados:
        grupos.setdefault((r["modo"], r["modelo"]), []).append(r)
    linhas = []
    for (modo, modelo), rs in grupos.items():
        do_modelo = [r for r in rs if r["caminho"] == "modelo"]
        tempos = [r["segundos"] for r in do_modelo]
        linhas.append({
            "modo": modo, "modelo": modelo,
            "acerto": f"{sum(r['acerto'] for r in rs)}/{len(rs)}",
            "acerto_atuais": f"{sum(r['acerto'] for r in rs if r['grupo'] == 'atual')}/{sum(r['grupo'] == 'atual' for r in rs)}",
            "acerto_futuras": f"{sum(r['acerto'] for r in rs if r['grupo'] == 'futuro')}/{sum(r['grupo'] == 'futuro' for r in rs)}",
            "acerto_pelo_modelo": f"{sum(r['acerto'] for r in do_modelo)}/{len(do_modelo)}",
            "p50_s": percentil(tempos, 50), "p95_s": percentil(tempos, 95),
            "tokens_p50": percentil([r["metricas"].get("tokens_gerados") for r in do_modelo], 50),
            "erros": sum(1 for r in rs if r["erro"]),
            "sem_chamada": sum(1 for r in do_modelo if r["metricas"].get("sem_chamada")),
        })
    return linhas


def resumir_extracao(resultados):
    grupos = {}
    for r in resultados:
        grupos.setdefault((r["modelo"], r["raciocinio"]), []).append(r)
    return [{"modelo": m, "raciocinio": rac, "acerto": f"{sum(r['acerto'] for r in rs)}/{len(rs)}",
             "p50_s": percentil([r["segundos"] for r in rs], 50), "p95_s": percentil([r["segundos"] for r in rs], 95),
             "tokens_p50": percentil([r["metricas"].get("tokens_gerados") for r in rs], 50)}
            for (m, rac), rs in grupos.items()]


def tabela_md(linhas, colunas):
    if not linhas:
        return "_sem dados_\n"
    texto = "| " + " | ".join(colunas) + " |\n|" + "---|" * len(colunas) + "\n"
    for linha in linhas:
        texto += "| " + " | ".join("" if linha.get(c) is None else str(linha.get(c)) for c in colunas) + " |\n"
    return texto


def relatorio_md(dados) -> str:
    md = [f"# SK0 — medição de {dados['data']}", "", f"Modelos: {', '.join(dados['modelos'])}. "
          f"Regras ligadas: {'sim' if dados['usar_regras'] else 'não'}. Repetições: {dados['repeticoes']}. "
          f"Modo \"atual\" = orquestrador do app ({dados.get('orquestrador', 'contextos')}).", ""]
    if dados.get("roteamento") is not None:
        md += ["## Escolha da skill", "",
               "`acerto_pelo_modelo` conta só as frases que chegaram ao modelo (as demais foram resolvidas por regra). "
               "p50/p95 também são só das chamadas ao modelo.", "",
               tabela_md(resumir_roteamento(dados["roteamento"]),
                         ["modo", "modelo", "acerto", "acerto_atuais", "acerto_futuras", "acerto_pelo_modelo",
                          "p50_s", "p95_s", "tokens_p50", "erros", "sem_chamada"])]
        erros = [r for r in dados["roteamento"] if not r["acerto"]]
        if erros:
            md += ["### Erros de escolha", "",
                   tabela_md([{**r, "frase": r["frase"][:60]} for r in erros],
                             ["modo", "modelo", "id", "frase", "esperado", "skill", "acao", "caminho"])]
    if dados.get("extracao") is not None:
        md += ["## Extração de compras", "", tabela_md(resumir_extracao(dados["extracao"]),
                                                       ["modelo", "raciocinio", "acerto", "p50_s", "p95_s", "tokens_p50"])]
    if dados.get("troca") is not None:
        md += ["## Troca de modelo", "", tabela_md(dados["troca"], ["modelo", "segundos", "s_carga", "na_vram", "erro"])]
    return "\n".join(md) + "\n"


def gravar_relatorio(dados, pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    base = pasta / f"sk0-{datetime.now().strftime('%Y%m%d-%H%M')}"
    base.with_suffix(".json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    base.with_suffix(".md").write_text(relatorio_md(dados), encoding="utf-8")
    return base


# =============================================================================
# Execução
# =============================================================================

def modelos_instalados():
    import ollama
    try:
        lista = ollama.Client(timeout=5).list()
        modelos = lista.get("models", []) if isinstance(lista, dict) else getattr(lista, "models", [])
        return {(m.get("model") or m.get("name")) if isinstance(m, dict) else getattr(m, "model", None) for m in modelos}
    except Exception as e:
        raise SystemExit(f"Ollama não respondeu ({e}). Abra o Ollama e rode de novo.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="SK0: escolha da skill, extração de compras e troca de modelo.")
    parser.add_argument("--modelos", default=",".join(MODELOS_PADRAO))
    parser.add_argument("--modos", default=",".join(MODOS))
    parser.add_argument("--repeticoes", type=int, default=1)
    parser.add_argument("--raciocinio", default="nao,sim", help="para a extração: padrao, nao, sim")
    parser.add_argument("--sem-regras", action="store_true", help="manda todas as frases ao modelo")
    parser.add_argument("--so-roteamento", action="store_true")
    parser.add_argument("--so-extracao", action="store_true")
    parser.add_argument("--so-troca", action="store_true")
    parser.add_argument("--saida", default=str(PASTA_SAIDA_PADRAO))
    args = parser.parse_args(argv)

    instalados = modelos_instalados()
    modelos = []
    for modelo in [m.strip() for m in args.modelos.split(",") if m.strip()]:
        if modelo in instalados or f"{modelo}:latest" in instalados:
            modelos.append(modelo)
        else:
            print(f"AVISO: {modelo} não está instalado; pulando (instale com: ollama pull {modelo})")
    if not modelos:
        raise SystemExit("Nenhum dos modelos pedidos está instalado.")

    so = [args.so_roteamento, args.so_extracao, args.so_troca]
    fazer = (lambda i: so[i] or not any(so))
    dados = {"data": datetime.now().strftime("%d/%m/%Y %H:%M"), "modelos": modelos, "usar_regras": not args.sem_regras,
             "orquestrador": "catalogo",
             "repeticoes": args.repeticoes, "roteamento": None, "extracao": None, "troca": None}
    if fazer(2):
        dados["troca"] = medir_troca(modelos)
    if fazer(0):
        modos = [m for m in args.modos.split(",") if m in MODOS]
        dados["roteamento"] = avaliar_roteamento(carregar_casos(), modos, modelos, args.repeticoes,
                                                 Avaliador(usar_regras=not args.sem_regras))
    if fazer(1):
        raciocinios = [r for r in args.raciocinio.split(",") if r in RACIOCINIO]
        dados["extracao"] = avaliar_extracao(ler_jsonl(ARQUIVO_COMPRAS), modelos, raciocinios, args.repeticoes)

    base = gravar_relatorio(dados, Path(args.saida))
    print("\n" + relatorio_md(dados))
    print(f"Relatório: {base.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
