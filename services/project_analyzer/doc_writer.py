"""
Geração da documentação Markdown.

- Escrita restrita à pasta de saída (EscritorSeguro bloqueia qualquer outro caminho).
- Atualização por seções entre marcadores: o texto fora dos marcadores (anotações
  manuais) é preservado quando a documentação é regenerada.
- Todo conteúdo passa pelo ocultador de segredos antes de ir para o disco.
- Cada informação recebe a classificação CONFIRMADO / INFERIDO / NÃO IDENTIFICADO
  e as evidências (arquivo:linha).
"""
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.project_analyzer.consistency_checker import CONFIRMADO, INFERIDO, NAO_IDENTIFICADO
from services.project_analyzer.redactor import ocultar_segredos


class EscritaNaoPermitidaError(Exception):
    """Tentativa de escrita fora da pasta de saída definida."""


class EscritorSeguro:
    def __init__(self, pasta_saida: str):
        self.raiz = Path(pasta_saida).resolve()

    def resolver(self, relativo: str) -> Path:
        destino = (self.raiz / relativo).resolve()
        if destino != self.raiz and self.raiz not in destino.parents:
            raise EscritaNaoPermitidaError(f"Escrita bloqueada fora da pasta de saída: {destino}")
        return destino

    def escrever(self, relativo: str, conteudo: str) -> Path:
        destino = self.resolver(relativo)
        destino.parent.mkdir(parents=True, exist_ok=True)
        conteudo, _ = ocultar_segredos(conteudo)
        with open(destino, "w", encoding="utf-8", newline="\n") as f:
            f.write(conteudo)
        return destino

    def ler(self, relativo: str) -> Optional[str]:
        destino = self.resolver(relativo)
        if not destino.exists():
            return None
        with open(destino, "r", encoding="utf-8") as f:
            return f.read()

    def escrever_documento(self, relativo: str, titulo: str, secoes: List[Tuple[str, str]]) -> Path:
        """
        Cria ou atualiza um documento por seções. Seções existentes são substituídas
        no lugar; o restante do arquivo (anotações manuais) é mantido.
        """
        existente = self.ler(relativo)
        if existente is None:
            partes = [f"# {titulo}\n",
                      "> Documento gerado pelo ProjectAnalyzer. Texto fora dos blocos marcados é preservado nas próximas análises.\n"]
            for chave, corpo in secoes:
                partes.append(_bloco(chave, corpo))
            return self.escrever(relativo, "\n".join(partes))

        texto = existente
        for chave, corpo in secoes:
            padrao = re.compile(rf"<!-- PA:INICIO {re.escape(chave)} -->.*?<!-- PA:FIM {re.escape(chave)} -->", re.DOTALL)
            novo = _bloco(chave, corpo).strip("\n")
            if padrao.search(texto):
                texto = padrao.sub(lambda _m: novo, texto, count=1)
            else:
                texto = texto.rstrip("\n") + "\n\n" + novo + "\n"
        return self.escrever(relativo, texto)


def _bloco(chave: str, corpo: str) -> str:
    return f"<!-- PA:INICIO {chave} -->\n{corpo.strip()}\n<!-- PA:FIM {chave} -->\n"


def _tag(conf: str) -> str:
    return f"`{conf}`"


def _evid(lista: List[str], limite: int = 4) -> str:
    if not lista:
        return "—"
    itens = ", ".join(f"`{e}`" for e in lista[:limite])
    return itens + (f" (+{len(lista) - limite})" if len(lista) > limite else "")


def _celula(texto: Any) -> str:
    return str(texto).replace("|", "\\|").replace("\n", " ")


# =============================================================================
# DOCUMENTOS
# =============================================================================

class GeradorDocumentacao:
    def __init__(self, escritor: EscritorSeguro, contexto: Dict[str, Any]):
        """
        contexto: nome, raiz, data, modelo, llm_disponivel, varredura, fatos, mapa,
        achados, divergencias, resumos, arquitetura, historico, alteracoes.
        """
        self.e = escritor
        self.c = contexto

    def gerar_todos(self) -> List[str]:
        docs = [
            ("README.md", "Índice da análise", self._indice()),
            ("01-visao-geral.md", f"Visão geral — {self.c['nome']}", self._visao_geral()),
            ("02-modulos.md", f"Módulos e responsabilidades — {self.c['nome']}", self._modulos()),
            ("03-dependencias-e-integracoes.md", f"Dependências e integrações — {self.c['nome']}", self._dependencias()),
            ("04-problemas-encontrados.md", f"Problemas encontrados — {self.c['nome']}", self._problemas()),
            ("05-divergencias-documentacao.md", f"Divergências entre documentação e código — {self.c['nome']}", self._divergencias()),
            ("06-historico-de-alteracoes.md", f"Histórico de alterações — {self.c['nome']}", self._historico()),
        ]
        return [str(self.e.escrever_documento(nome, titulo, secoes)) for nome, titulo, secoes in docs]

    # ------------------------------------------------------------------
    def _indice(self) -> List[Tuple[str, str]]:
        c = self.c
        corpo = f"""**Projeto:** {c['nome']}
**Última análise:** {c['data']}
**Modelo local:** {c['modelo'] if c['llm_disponivel'] else f"{c['modelo']} (indisponível nesta análise — apenas dados determinísticos)"}

| Documento | Conteúdo |
|---|---|
| [01-visao-geral.md](01-visao-geral.md) | Tecnologias, pontos de entrada, arquitetura e limitações |
| [02-modulos.md](02-modulos.md) | Responsabilidades, classes, funções e relações de cada arquivo |
| [03-dependencias-e-integracoes.md](03-dependencias-e-integracoes.md) | Bibliotecas, integrações, banco de dados, IPC e diagrama |
| [04-problemas-encontrados.md](04-problemas-encontrados.md) | Inconsistências, duplicações e riscos |
| [05-divergencias-documentacao.md](05-divergencias-documentacao.md) | Documentação existente x implementação |
| [06-historico-de-alteracoes.md](06-historico-de-alteracoes.md) | Evolução entre análises |

### Classificação das informações
- {_tag(CONFIRMADO)} — identificado diretamente no código ou na configuração (com arquivo:linha).
- {_tag(INFERIDO)} — conclusão baseada em evidências, sem declaração explícita (inclui todo texto produzido pelo LLM local).
- {_tag(NAO_IDENTIFICADO)} — não foi possível determinar."""
        return [("indice", corpo)]

    def _visao_geral(self) -> List[Tuple[str, str]]:
        c, var, fatos, mapa = self.c, self.c["varredura"], self.c["fatos"], self.c["mapa"]
        analisados = len(fatos)
        ignorados = [a for a in var.arquivos if a.motivo_ignorado]

        ident = f"""| Item | Valor |
|---|---|
| Projeto | {c['nome']} |
| Raiz | `{c['raiz']}` |
| Data da análise | {c['data']} |
| Arquivos encontrados | {len(var.arquivos)} |
| Arquivos analisados | {analisados} |
| Arquivos não lidos (binários, grandes, lockfiles) | {len(ignorados)} |
| Modelo local | {c['modelo']} ({'utilizado' if c['llm_disponivel'] else 'indisponível'}) |"""

        por_ling = defaultdict(lambda: [0, 0])
        for f in fatos.values():
            por_ling[f.get("linguagem") or "Desconhecida"][0] += 1
            por_ling[f.get("linguagem") or "Desconhecida"][1] += f.get("linhas", 0)
        linhas = [f"Classificação: {_tag(CONFIRMADO)} (contagem por extensão de arquivo).\n",
                  "| Linguagem | Arquivos | Linhas |", "|---|---|---|"]
        for ling, (n, l) in sorted(por_ling.items(), key=lambda kv: -kv[1][1]):
            linhas.append(f"| {ling} | {n} | {l} |")
        linguagens = "\n".join(linhas)

        tecs = defaultdict(list)
        for caminho, f in sorted(fatos.items()):
            for i in f.get("integracoes", []):
                tecs[i["tipo"]].append(f"{caminho}:{i['linha']}")
        pj = mapa.package_json
        if pj and "erro" not in pj:
            for secao in ("dependencias", "dependencias_dev"):
                for nome in pj.get(secao, {}):
                    if nome == "electron":
                        tecs["Interface desktop: Electron"].append("package.json")
        tec_linhas = [f"| Tecnologia / integração | Evidências | Classificação |", "|---|---|---|"]
        for tipo, evid in sorted(tecs.items()):
            tec_linhas.append(f"| {_celula(tipo)} | {_evid(evid, 3)} | {_tag(CONFIRMADO)} |")
        tecnologias = "\n".join(tec_linhas) if tecs else f"Nenhuma tecnologia identificada por imports. {_tag(NAO_IDENTIFICADO)}"

        entradas = mapa.pontos_de_entrada()
        txt_entradas = "\n".join(f"- `{e}` {_tag(CONFIRMADO)}" for e in entradas) if entradas else \
            f"- Nenhum ponto de entrada explícito encontrado. {_tag(NAO_IDENTIFICADO)}"
        scripts = (pj or {}).get("scripts") if pj and "erro" not in pj else None
        if scripts:
            txt_entradas += "\n\nScripts do package.json " + _tag(CONFIRMADO) + ":\n" + "\n".join(f"- `{k}`: `{v}`" for k, v in scripts.items())
        processos = [(p, proc) for p, f in sorted(fatos.items()) for proc in f.get("processos", [])]
        if processos:
            txt_entradas += "\n\nProcessos iniciados pelo código " + _tag(CONFIRMADO) + ":\n" + \
                "\n".join(f"- `{proc['chamada']}` em `{p}:{proc['linha']}`" for p, proc in processos[:10])

        centrais = mapa.centrais()
        txt_centrais = "\n".join(f"- `{x['arquivo']}` — importado por {x['usado_por']} arquivo(s) {_tag(CONFIRMADO)}" for x in centrais) \
            if centrais else f"- Nenhuma dependência interna identificada. {_tag(NAO_IDENTIFICADO)}"

        arq = c.get("arquitetura")
        if arq:
            partes = [f"Gerado pelo modelo local a partir dos dados extraídos. Classificação: {_tag(INFERIDO)}.\n",
                      f"**Visão geral:** {arq.get('visao_geral') or NAO_IDENTIFICADO}\n",
                      f"**Fluxo principal:** {arq.get('fluxo_principal') or NAO_IDENTIFICADO}\n"]
            if arq.get("padroes"):
                partes.append("**Padrões observados:**\n" + "\n".join(f"- {p}" for p in arq["padroes"]))
            if arq.get("decisoes"):
                partes.append("\n**Decisões arquiteturais identificadas:**\n" + "\n".join(f"- {d}" for d in arq["decisoes"]))
            txt_arq = "\n".join(partes)
        else:
            txt_arq = f"{_tag(NAO_IDENTIFICADO)} — o modelo local não estava disponível ou não produziu uma resposta válida. " \
                      "As seções determinísticas (tecnologias, módulos, dependências) continuam válidas."

        lim = []
        if var.diretorios_ignorados:
            lim.append("- Diretórios não analisados (dependências, caches, controle de versão): " +
                       ", ".join(f"`{d}`" for d in var.diretorios_ignorados[:15]) +
                       (f" (+{len(var.diretorios_ignorados) - 15})" if len(var.diretorios_ignorados) > 15 else ""))
        motivos = Counter(a.motivo_ignorado for a in ignorados)
        for motivo, n in motivos.most_common():
            lim.append(f"- {n} arquivo(s) não lido(s): {motivo}.")
        parciais = sorted({f.get('linguagem') for f in fatos.values() if "parcial" in str(f.get("metodo"))})
        if parciais:
            lim.append(f"- Análise parcial (expressões regulares, sem árvore sintática) para: {', '.join(parciais)}. "
                       "Funções, imports e canais podem não ter sido todos identificados.")
        erros = [p for p, f in fatos.items() if f.get("erro_sintaxe")]
        if erros:
            lim.append(f"- {len(erros)} arquivo(s) Python com erro de sintaxe não tiveram a estrutura extraída.")
        if var.truncado:
            lim.append("- A varredura atingiu o limite máximo de arquivos; parte do projeto não foi analisada.")
        lim.append("- Comportamento em tempo de execução (valores de configuração, dados no banco, chamadas dinâmicas) não é avaliado.")

        return [("identificacao", ident), ("linguagens", "## Linguagens\n\n" + linguagens),
                ("tecnologias", "## Tecnologias e integrações\n\n" + tecnologias),
                ("entrada", "## Pontos de entrada\n\n" + txt_entradas),
                ("centrais", "## Componentes centrais\n\n" + txt_centrais),
                ("arquitetura", "## Arquitetura (interpretação)\n\n" + txt_arq),
                ("limitacoes", "## Limitações desta análise\n\n" + "\n".join(lim))]

    def _modulos(self) -> List[Tuple[str, str]]:
        c, fatos, mapa, resumos = self.c, self.c["fatos"], self.c["mapa"], self.c["resumos"]
        blocos = []
        codigo = [p for p, f in sorted(fatos.items()) if f.get("linguagem") in ("Python", "JavaScript", "TypeScript", "HTML")]
        for caminho in codigo:
            f = fatos[caminho]
            linhas = [f"### `{caminho}`", "",
                      f"{f.get('linguagem')} · {f.get('linhas', 0)} linhas · extração: {f.get('metodo')}", ""]
            if f.get("erro_sintaxe"):
                linhas.append(f"- **Erro de sintaxe** na linha {f['erro_sintaxe']['linha']}: estrutura não extraída. {_tag(CONFIRMADO)}")
            if f.get("doc_modulo"):
                linhas.append(f"- **Docstring do módulo:** {f['doc_modulo']} {_tag(CONFIRMADO)}")
            r = resumos.get(caminho)
            if r:
                linhas.append(f"- **Responsabilidade:** {r['responsabilidade']} {_tag(INFERIDO)}")
                for o in r.get("observacoes", []):
                    linhas.append(f"  - Observação: {o} {_tag(INFERIDO)}")
            elif not f.get("doc_modulo"):
                linhas.append(f"- **Responsabilidade:** {_tag(NAO_IDENTIFICADO)}")

            if f.get("classes"):
                linhas.append(f"- **Classes** {_tag(CONFIRMADO)}:")
                for cl in f["classes"]:
                    bases = f"({', '.join(cl['bases'])})" if cl.get("bases") else ""
                    metodos = ", ".join(f"`{m}`" for m in cl.get("metodos", [])[:30])
                    linhas.append(f"  - `{cl['nome']}{bases}` (linha {cl['linha']})" + (f": {metodos}" if metodos else ""))
            if f.get("funcoes"):
                nomes = ", ".join(f"`{fn['nome']}` (l.{fn['linha']})" for fn in f["funcoes"][:40])
                linhas.append(f"- **Funções** {_tag(CONFIRMADO)}: {nomes}")
            dep = sorted(mapa.arestas.get(caminho, []))
            usado = sorted(mapa.usado_por.get(caminho, []))
            if dep:
                linhas.append(f"- **Depende de** {_tag(CONFIRMADO)}: " + ", ".join(f"`{d}`" for d in dep))
            if usado:
                linhas.append(f"- **Usado por** {_tag(CONFIRMADO)}: " + ", ".join(f"`{u}`" for u in usado))
            if f.get("integracoes"):
                linhas.append(f"- **Integrações** {_tag(CONFIRMADO)}: " +
                              "; ".join(f"{i['tipo']} (l.{i['linha']})" for i in f["integracoes"]))
            if f.get("ipc"):
                canais = sorted({f"{i['objeto']}.{i['operacao']}('{i['canal']}')" for i in f["ipc"]})
                linhas.append(f"- **IPC** {_tag(CONFIRMADO)}: " + ", ".join(f"`{x}`" for x in canais[:20]))
            blocos.append("\n".join(linhas))
        corpo = "\n\n".join(blocos) if blocos else f"Nenhum arquivo de código identificado. {_tag(NAO_IDENTIFICADO)}"
        return [("modulos", corpo)]

    def _dependencias(self) -> List[Tuple[str, str]]:
        fatos, mapa = self.c["fatos"], self.c["mapa"]
        declaradas = mapa.dependencias_declaradas()

        linhas = [f"Classificação: {_tag(CONFIRMADO)}.\n", "| Pacote | Declarado | Usado em |", "|---|---|---|"]
        for chave, usos in sorted(mapa.externas.items()):
            if chave.startswith("npm:"):
                nome, dec = chave[4:], ("package.json" if chave in declaradas else ("não" if mapa.package_json is not None else "sem manifesto"))
            else:
                nome = mapa.pacote_pip(chave)
                dec = "requirements.txt" if nome in declaradas else ("não" if mapa.requirements is not None else "sem manifesto")
            locais = ["%s:%s" % (u["arquivo"], u["linha"]) for u in usos]
            linhas.append(f"| `{nome}` | {dec} | {_evid(locais, 3)} |")
        externas = "\n".join(linhas) if mapa.externas else f"Nenhuma biblioteca externa importada. {_tag(NAO_IDENTIFICADO)}"

        integ = defaultdict(list)
        for p, f in sorted(fatos.items()):
            for i in f.get("integracoes", []):
                integ[i["tipo"]].append(f"{p}:{i['linha']}")
        t_integ = "\n".join([f"| Integração | Evidências |", "|---|---|"] +
                            [f"| {_celula(t)} | {_evid(e, 5)} |" for t, e in sorted(integ.items())]) if integ else \
            f"Nenhuma integração identificada. {_tag(NAO_IDENTIFICADO)}"

        tabelas = defaultdict(list)
        for p, f in sorted(fatos.items()):
            for t in f.get("tabelas_sql", []):
                tabelas[t["nome"]].append(f"{p}:{t['linha']}")
        t_tab = "\n".join(f"- `{t}` — definida em {_evid(e)} {_tag(CONFIRMADO)}" for t, e in sorted(tabelas.items())) if tabelas else \
            f"- Nenhuma instrução CREATE TABLE encontrada. {_tag(NAO_IDENTIFICADO)}"

        canais = defaultdict(list)
        for p, f in sorted(fatos.items()):
            for i in f.get("ipc", []):
                canais[i["canal"]].append(f"{i['objeto']}.{i['operacao']} `{p}:{i['linha']}`")
        t_ipc = "\n".join(f"- `{canal}`: " + "; ".join(usos[:4]) for canal, usos in sorted(canais.items())) if canais else \
            f"- Nenhum canal IPC identificado. {_tag(NAO_IDENTIFICADO)}"

        urls = sorted({(u["url"], f"{p}:{u['linha']}") for p, f in fatos.items() if f.get("linguagem") != "Markdown" for u in f.get("urls", [])})
        t_urls = "\n".join(f"- `{u}` em `{e}`" for u, e in urls[:30]) if urls else "- Nenhuma URL no código."

        diagrama = mapa.mermaid()
        t_diag = f"Classificação: {_tag(CONFIRMADO)} (arestas = imports entre arquivos do projeto).\n\n```mermaid\n{diagrama}\n```" if diagrama else \
            f"Sem dependências internas para diagramar. {_tag(NAO_IDENTIFICADO)}"
        if diagrama and mapa.arestas_omitidas:
            t_diag += f"\n\n{mapa.arestas_omitidas} relação(ões) omitida(s) para manter o diagrama legível; ver 02-modulos.md."

        return [("externas", "## Bibliotecas externas\n\n" + externas),
                ("integracoes", "## Integrações e serviços\n\n" + t_integ),
                ("banco", "## Banco de dados (tabelas definidas no código)\n\n" + t_tab),
                ("ipc", "## Comunicação entre processos (IPC)\n\n" + t_ipc),
                ("urls", "## Endpoints e URLs no código\n\n" + t_urls),
                ("diagrama", "## Diagrama de dependências internas\n\n" + t_diag)]

    def _problemas(self) -> List[Tuple[str, str]]:
        achados = self.c["achados"]
        if not achados:
            return [("problemas", "Nenhum problema identificado pelas verificações automáticas.")]
        nomes = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}
        partes = [f"Total: {len(achados)} achado(s). Verificações determinísticas; não substituem revisão humana.\n"]
        for g in ("alta", "media", "baixa"):
            grupo = [a for a in achados if a["gravidade"] == g]
            if not grupo:
                continue
            partes.append(f"## Gravidade {nomes[g]} ({len(grupo)})\n")
            partes.append("| Categoria | Descrição | Classificação | Evidências |")
            partes.append("|---|---|---|---|")
            for a in grupo:
                partes.append(f"| {a['categoria']} | {_celula(a['mensagem'])} | {_tag(a['confiabilidade'])} | {_evid(a['evidencias'])} |")
            partes.append("")
        return [("problemas", "\n".join(partes))]

    def _divergencias(self) -> List[Tuple[str, str]]:
        d = self.c["divergencias"]
        if not d["documentos"]:
            return [("divergencias", f"O projeto não possui documentação Markdown para comparar. {_tag(NAO_IDENTIFICADO)}")]
        partes = ["Comparação por referências a arquivos. Descrições textuais de comportamento não são verificadas automaticamente.\n",
                  f"**Documentos encontrados ({len(d['documentos'])}):** " + ", ".join(f"`{x}`" for x in d["documentos"]), ""]
        partes.append("## Arquivos citados na documentação que não existem\n")
        if d["referencias_quebradas"]:
            partes.append("| Documento | Arquivo citado | Linha | Classificação |")
            partes.append("|---|---|---|---|")
            for r in d["referencias_quebradas"]:
                partes.append(f"| `{r['documento']}` | `{r['arquivo']}` | {r['linha']} | {_tag(CONFIRMADO)} |")
        else:
            partes.append("Nenhuma referência quebrada.")
        partes.append("\n## Arquivos de código não citados em nenhum documento\n")
        if d["nao_documentados"]:
            partes.append(f"Classificação: {_tag(CONFIRMADO)} (o nome do arquivo não aparece em nenhum `.md`).\n")
            partes.extend(f"- `{x}`" for x in d["nao_documentados"])
        else:
            partes.append("Todos os arquivos de código são citados na documentação.")
        return [("divergencias", "\n".join(partes))]

    def _historico(self) -> List[Tuple[str, str]]:
        hist = self.c["historico"]
        alt = self.c["alteracoes"]
        resumo_atual = ("Primeira análise registrada." if alt["primeira_analise"] else
                        f"Desde a análise anterior: {len(alt['adicionados'])} arquivo(s) novo(s), "
                        f"{len(alt['modificados'])} modificado(s), {len(alt['removidos'])} removido(s).")
        if not alt["primeira_analise"] and not any(alt[k] for k in ("adicionados", "modificados", "removidos")):
            resumo_atual = "Nenhuma alteração desde a análise anterior."
        partes = [f"**Análise atual ({self.c['data']}):** {resumo_atual}\n"]
        for entrada in reversed(hist[-30:]):
            partes.append(f"## {entrada['data']}" + (" — primeira análise" if entrada.get("primeira_analise") else ""))
            est = entrada.get("estatisticas", {})
            partes.append(f"Arquivos analisados: {est.get('arquivos_analisados', '?')} · linhas: {est.get('linhas', '?')} · "
                          f"achados: {est.get('achados', '?')}\n")
            if not entrada.get("primeira_analise"):
                for rotulo, chave in (("Adicionados", "adicionados"), ("Modificados", "modificados"), ("Removidos", "removidos")):
                    if entrada.get(chave):
                        partes.append(f"- **{rotulo}:** " + ", ".join(f"`{x}`" for x in entrada[chave][:30]))
                for arq, sim in entrada.get("simbolos", {}).items():
                    if sim.get("adicionados"):
                        partes.append(f"  - `{arq}` + " + ", ".join(sim["adicionados"][:15]))
                    if sim.get("removidos"):
                        partes.append(f"  - `{arq}` − " + ", ".join(sim["removidos"][:15]))
            partes.append("")
        return [("historico", "\n".join(partes))]
