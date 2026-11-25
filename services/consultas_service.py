"""
M19: consultas de gastos e preços sem SQL livre.

O modelo só preenche um formulário (tipo, categoria, loja, produto); os períodos vêm de services/periodos.py.
Aqui ficam as consultas prontas, parametrizadas e em centavos. Nome de loja e de produto é comparado sem
acentos e sem maiúsculas, em Python (o volume de uma casa é pequeno).
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from services.dinheiro import formatar
from services.periodos import Periodo
from services.produtos_service import CATEGORIAS, _sem_acentos, chave_produto, normalizar_categoria

TIPOS = ("listar", "total", "por_categoria", "por_loja", "preco_produto", "comparar")
LIMITE_LISTA = 10


@dataclass
class Filtro:
    periodo: Optional[Periodo] = None
    categoria: Optional[str] = None
    loja: Optional[str] = None
    produto: Optional[str] = None

    def descricao(self) -> str:
        partes = []
        if self.categoria:
            partes.append(f"com {CATEGORIAS.get(self.categoria, self.categoria).lower()}")
        if self.produto:
            partes.append(f"com {self.produto}")
        if self.loja:
            partes.append(f"em {self.loja}")
        partes.append(self.periodo.rotulo if self.periodo else "em todo o histórico")
        return " ".join(partes)


@dataclass
class Item:
    compra_id: int
    data: str
    loja: str
    produto: str
    categoria: str
    quantidade: float
    unidade: str
    unitario_centavos: int
    total_centavos: int
    obs_compra: Optional[str] = None
    obs_item: Optional[str] = None


@dataclass
class Resultado:
    texto: str
    dados: Dict = field(default_factory=dict)


def _norm(texto: str) -> str:
    return " ".join(_sem_acentos(str(texto or "")).replace("-", " ").split())


def _data_br(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" if iso and len(iso) >= 10 else (iso or "?")


def _pct(parte: int, total: int) -> str:
    pct = 100 * parte / total if total else 0
    return "<1%" if 0 < pct < 1 else f"{round(pct)}%"


def _qtd(valor: float) -> str:
    return str(int(valor)) if float(valor).is_integer() else f"{valor:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class ConsultasGastos:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ dados

    def _itens(self, filtro: Filtro) -> List[Item]:
        # A categoria vem do catálogo (M07, lista fechada); itens antigos sem produto usam a do item, normalizada
        sql = ("SELECT c.id, c.data_compra, COALESCE(c.nome_comercio, 'Não informado'), i.produto, "
               "COALESCE(p.categoria, i.categoria, 'outros'), "
               "i.quantidade, COALESCE(i.unidade, 'un'), "
               "COALESCE(i.valor_unitario_centavos, CAST(ROUND(i.valor_unitario * 100) AS INTEGER)), "
               "COALESCE(i.valor_total_centavos, CAST(ROUND(i.valor_total * 100) AS INTEGER)), "
               "c.observacao, i.observacao "
               "FROM itens_compra i JOIN compras c ON c.id = i.compra_id LEFT JOIN produtos p ON p.id = i.produto_id")
        params = []
        if filtro.periodo:
            sql += " WHERE c.data_compra BETWEEN ? AND ?"
            params += [filtro.periodo.inicio_iso, filtro.periodo.fim_iso]
        sql += " ORDER BY c.data_compra, c.id, i.id"
        itens = [Item(*linha) for linha in self.db.executar_consulta(sql, tuple(params))]
        for item in itens:
            item.categoria = normalizar_categoria(item.categoria)
        if filtro.categoria:
            itens = [i for i in itens if i.categoria == filtro.categoria]
        if filtro.loja:
            alvo = _norm(filtro.loja)
            itens = [i for i in itens if alvo in _norm(i.loja)]
        if filtro.produto:
            itens = [i for i in itens if self._mesmo_produto(filtro.produto, i.produto)]
        return itens

    @staticmethod
    def _mesmo_produto(procurado: str, nome: str) -> bool:
        """Todas as palavras procuradas aparecem no nome (com ou sem 's' no fim)."""
        palavras = [p for p in chave_produto(procurado).split() if len(p) > 1]
        alvo = set(chave_produto(nome).split())
        alvo |= {p[:-1] for p in alvo if p.endswith("s")}
        return bool(palavras) and all(p in alvo or p.rstrip("s") in alvo for p in palavras)

    def _compras(self, itens: List[Item]) -> List[Dict]:
        """Agrupa os itens por compra (o total é a soma dos itens que passaram no filtro)."""
        compras: Dict[int, Dict] = {}
        for i in itens:
            c = compras.setdefault(i.compra_id, {"id": i.compra_id, "data": i.data, "loja": i.loja, "centavos": 0, "itens": 0,
                                                 "obs": i.obs_compra})
            c["centavos"] += i.total_centavos
            c["itens"] += 1
        return list(compras.values())

    # ------------------------------------------------------------------ consultas

    def listar(self, filtro: Filtro) -> Resultado:
        compras = self._compras(self._itens(filtro))
        if not compras:
            return Resultado(f"Não encontrei compras {filtro.descricao()}.", {"compras": []})
        total = sum(c["centavos"] for c in compras)
        recentes = sorted(compras, key=lambda c: (c["data"], c["id"]), reverse=True)
        linhas = [f"{len(compras)} compra(s) {filtro.descricao()}, total {formatar(total)}:"]
        for c in recentes[:LIMITE_LISTA]:
            linhas.append(f"- {_data_br(c['data'])} · {c['loja']}: {formatar(c['centavos'])} ({c['itens']} item(ns))"
                          + (f" 📝 {c['obs']}" if c.get("obs") else ""))
        if len(compras) > LIMITE_LISTA:
            linhas.append(f"… e mais {len(compras) - LIMITE_LISTA} compra(s) mais antigas.")
        return Resultado("\n".join(linhas), {"compras": compras, "total_centavos": total})

    def total(self, filtro: Filtro) -> Resultado:
        itens = self._itens(filtro)
        compras = self._compras(itens)
        total = sum(i.total_centavos for i in itens)
        if not itens:
            return Resultado(f"Não encontrei gastos {filtro.descricao()}.", {"total_centavos": 0})
        return Resultado(f"Você gastou {formatar(total)} {filtro.descricao()}, em {len(compras)} compra(s).",
                         {"total_centavos": total, "compras": len(compras)})

    def _ranking(self, filtro: Filtro, chave) -> List[tuple]:
        soma: Dict[str, int] = {}
        for i in self._itens(filtro):
            soma[chave(i)] = soma.get(chave(i), 0) + i.total_centavos
        return sorted(soma.items(), key=lambda x: x[1], reverse=True)

    def por_categoria(self, filtro: Filtro) -> Resultado:
        ranking = self._ranking(filtro, lambda i: i.categoria)
        if not ranking:
            return Resultado(f"Não encontrei gastos {filtro.descricao()}.", {"ranking": []})
        total = sum(v for _, v in ranking)
        linhas = [f"Gastos por categoria {filtro.descricao()} (total {formatar(total)}):"]
        for cat, valor in ranking:
            linhas.append(f"- {CATEGORIAS.get(cat, cat)}: {formatar(valor)} ({_pct(valor, total)})")
        return Resultado("\n".join(linhas), {"ranking": ranking, "total_centavos": total})

    def por_loja(self, filtro: Filtro) -> Resultado:
        ranking = self._ranking(filtro, lambda i: i.loja)
        if not ranking:
            return Resultado(f"Não encontrei gastos {filtro.descricao()}.", {"ranking": []})
        total = sum(v for _, v in ranking)
        linhas = [f"Gastos por loja {filtro.descricao()} (total {formatar(total)}):"]
        for loja, valor in ranking[:LIMITE_LISTA]:
            linhas.append(f"- {loja}: {formatar(valor)} ({_pct(valor, total)})")
        return Resultado("\n".join(linhas), {"ranking": ranking, "total_centavos": total})

    def preco_produto(self, filtro: Filtro) -> Resultado:
        if not filtro.produto:
            return Resultado("De qual produto você quer saber o preço?", {})
        itens = self._itens(filtro)
        if not itens:
            return Resultado(f"Não encontrei compras de {filtro.produto} "
                             f"{filtro.periodo.rotulo if filtro.periodo else 'no histórico'}.", {"itens": []})
        ultimo = itens[-1]
        menor = min(itens, key=lambda i: i.unitario_centavos)
        media = round(sum(i.unitario_centavos for i in itens) / len(itens))
        un = ultimo.unidade if ultimo.unidade in ("kg", "litro") else "un"
        linhas = [f"{filtro.produto.capitalize()} — {len(itens)} compra(s):",
                  f"- Última: {formatar(ultimo.unitario_centavos)}/{un} em {ultimo.loja}, {_data_br(ultimo.data)} "
                  f"({_qtd(ultimo.quantidade)} {ultimo.unidade}, {formatar(ultimo.total_centavos)})"]
        if len(itens) > 1:
            linhas.append(f"- Menor: {formatar(menor.unitario_centavos)}/{un} em {menor.loja}, {_data_br(menor.data)}")
            linhas.append(f"- Média: {formatar(media)}/{un}")
        nomes = sorted({i.produto for i in itens})
        if len(nomes) > 1:
            linhas.append(f"(inclui: {', '.join(nomes[:5])}{'…' if len(nomes) > 5 else ''})")
        return Resultado("\n".join(linhas), {"itens": len(itens), "ultimo_centavos": ultimo.unitario_centavos,
                                             "menor_centavos": menor.unitario_centavos, "media_centavos": media})

    def comparar(self, filtro: Filtro, periodos: List[Periodo]) -> Resultado:
        if len(periodos) < 2:
            return Resultado("Para comparar, diga os dois períodos (ex.: \"outubro ou novembro\").", {})
        totais = []
        for p in periodos[:4]:
            f = Filtro(periodo=p, categoria=filtro.categoria, loja=filtro.loja, produto=filtro.produto)
            totais.append((p, sum(i.total_centavos for i in self._itens(f))))
        assunto = Filtro(categoria=filtro.categoria, loja=filtro.loja, produto=filtro.produto).descricao()
        assunto = assunto.replace("em todo o histórico", "").strip()
        linhas = ["Comparação" + (f" dos gastos {assunto}" if assunto else " dos gastos") + ":"]
        for p, v in totais:
            linhas.append(f"- {p.rotulo[0].upper() + p.rotulo[1:]}: {formatar(v)}")
        (p1, v1), (p2, v2) = totais[0], totais[1]
        if v1 == v2:
            linhas.append("Os dois períodos ficaram iguais.")
        else:
            maior, menor_v = (p1, v1) if v1 > v2 else (p2, v2), min(v1, v2)
            diferenca = abs(v1 - v2)
            pct = f" ({round(100 * diferenca / menor_v)}% a mais)" if menor_v else ""
            linhas.append(f"Gastou mais {maior[0].rotulo}: {formatar(diferenca)} de diferença{pct}.")
        return Resultado("\n".join(linhas), {"totais": [(p.rotulo, v) for p, v in totais]})


def resumo_para_painel(db, meses: int = 12, hoje=None) -> Dict:
    """I06: números do painel web, em centavos. Por mês (os últimos `meses`), por categoria, por loja e as últimas compras."""
    from datetime import date
    hoje = hoje or date.today()
    ano, mes = hoje.year, hoje.month
    rotulos = []
    for _ in range(max(1, min(int(meses), 36))):
        rotulos.append(f"{ano:04d}-{mes:02d}")
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    rotulos.reverse()
    consultas = ConsultasGastos(db)
    inicio = date.fromisoformat(rotulos[0] + "-01")
    periodo = Periodo(inicio, hoje, f"desde {inicio:%m/%Y}")
    itens = consultas._itens(Filtro(periodo=periodo))
    por_mes = {r: 0 for r in rotulos}
    por_categoria: Dict[str, int] = {}
    por_loja: Dict[str, int] = {}
    for i in itens:
        chave = i.data[:7]
        if chave in por_mes:
            por_mes[chave] += i.total_centavos
        por_categoria[i.categoria] = por_categoria.get(i.categoria, 0) + i.total_centavos
        por_loja[i.loja] = por_loja.get(i.loja, 0) + i.total_centavos
    compras = sorted(consultas._compras(itens), key=lambda c: (c["data"], c["id"]), reverse=True)
    return {
        "periodo": {"inicio": periodo.inicio_iso, "fim": periodo.fim_iso},
        "total_centavos": sum(por_mes.values()),
        "compras": len(compras),
        "por_mes": [{"mes": r, "centavos": v} for r, v in por_mes.items()],
        "por_categoria": [{"categoria": CATEGORIAS.get(c, c), "centavos": v}
                          for c, v in sorted(por_categoria.items(), key=lambda x: x[1], reverse=True)],
        "por_loja": [{"loja": l, "centavos": v} for l, v in sorted(por_loja.items(), key=lambda x: x[1], reverse=True)[:10]],
        "ultimas": [{"data": c["data"], "loja": c["loja"], "centavos": c["centavos"], "itens": c["itens"], "obs": c.get("obs")}
                    for c in compras[:10]],
    }


# Painel: subgrupos dentro de algumas categorias ("Carnes e peixes" > Frango, Bovina...). Palavras do nome do produto,
# sem acento; vale o primeiro grupo que casar. Produto que não casa fica pelo próprio nome.
SUBGRUPOS = {
    "carnes": [("Frango", ["frango", "galinha", "peito", "coxa", "sobrecoxa", "asa", "chester", "peru"]),
               ("Suína", ["suino", "suina", "porco", "lombo", "pernil", "costelinha", "bacon", "toucinho", "linguica", "calabresa"]),
               ("Peixes e frutos do mar", ["peixe", "tilapia", "salmao", "sardinha", "atum", "merluza", "camarao", "bacalhau"]),
               ("Bovina", ["bovino", "bovina", "boi", "patinho", "alcatra", "picanha", "contra", "file", "acem", "costela", "maminha",
                           "fraldinha", "cupim", "musculo", "moida", "moido", "carne"])],
    "hortifruti": [("Frutas", ["banana", "maca", "laranja", "limao", "mamao", "manga", "uva", "abacaxi", "melancia", "melao", "morango",
                               "pera", "abacate", "goiaba", "maracuja", "kiwi"]),
                   ("Verduras", ["alface", "couve", "rucula", "agriao", "espinafre", "repolho", "cheiro", "salsinha", "cebolinha"]),
                   ("Legumes", ["tomate", "batata", "cebola", "alho", "cenoura", "abobrinha", "abobora", "pepino", "pimentao",
                                "beterraba", "chuchu", "mandioca", "berinjela", "milho", "quiabo"])],
    "bebidas": [("Refrigerantes", ["refrigerante", "coca", "guarana", "fanta", "pepsi", "sprite", "soda"]),
                ("Cervejas", ["cerveja", "chopp"]), ("Sucos", ["suco", "nectar"]), ("Águas", ["agua"]),
                ("Vinhos e destilados", ["vinho", "espumante", "cachaca", "vodka", "whisky"])],
    "laticinios": [("Leite", ["leite"]), ("Queijos", ["queijo", "mucarela", "mussarela", "requeijao", "parmesao", "ricota"]),
                   ("Iogurtes", ["iogurte", "coalhada"]), ("Manteiga e margarina", ["manteiga", "margarina"]),
                   ("Frios", ["presunto", "mortadela", "salame", "peito de peru", "apresuntado"])],
}


def subgrupo(produto: str, categoria: str) -> str:
    """Grupo do produto dentro da categoria (para o painel); sem regra, o nome do produto."""
    nome = _norm(produto).lower()
    palavras = set(nome.split())
    for rotulo, chaves in SUBGRUPOS.get(categoria, []):
        for chave in chaves:
            if (" " in chave and chave in nome) or chave in palavras or any(p.startswith(chave) for p in palavras):
                return rotulo
    return (produto or "Sem nome").strip()[:1].upper() + (produto or "Sem nome").strip()[1:]


NOMES_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
               "novembro", "dezembro"]


def detalhe_gastos(db, meses: int = 12, mes: Optional[str] = None, categoria: Optional[str] = None,
                   grupo: Optional[str] = None, hoje=None) -> Dict:
    """
    Painel: gastos em níveis — categorias > grupos (ex.: Carnes > Frango) > itens.
    `mes` (AAAA-MM) restringe a um mês; sem ele, vale o período dos últimos `meses`.
    """
    import calendar
    from datetime import date
    hoje = hoje or date.today()
    if mes:
        ano, m = int(mes[:4]), int(mes[5:7])
        inicio, fim = date(ano, m, 1), date(ano, m, calendar.monthrange(ano, m)[1])
        rotulo_periodo = f"{NOMES_MESES[m - 1].capitalize()} de {ano}"
    else:
        meses = max(1, min(int(meses), 36))
        ano, m = hoje.year, hoje.month - (meses - 1)
        while m <= 0:
            ano, m = ano - 1, m + 12
        inicio, fim = date(ano, m, 1), hoje
        rotulo_periodo = f"Últimos {meses} meses" if meses > 1 else "Este mês"
    itens = ConsultasGastos(db)._itens(Filtro(periodo=Periodo(inicio, fim, rotulo_periodo)))
    trilha = [{"nivel": "periodo", "rotulo": rotulo_periodo}]
    if categoria:
        itens = [i for i in itens if i.categoria == categoria]
        trilha.append({"nivel": "categoria", "chave": categoria, "rotulo": CATEGORIAS.get(categoria, categoria)})
    if categoria and grupo:
        itens = [i for i in itens if subgrupo(i.produto, i.categoria) == grupo]
        trilha.append({"nivel": "grupo", "chave": grupo, "rotulo": grupo})
    total = sum(i.total_centavos for i in itens)
    resposta = {"periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat(), "mes": mes}, "trilha": trilha,
                "total_centavos": total, "compras": len({i.compra_id for i in itens})}
    if categoria and grupo:
        resposta["nivel"] = "itens"
        resposta["itens"] = [{"data": i.data, "loja": i.loja, "produto": i.produto, "quantidade": i.quantidade,
                              "unidade": i.unidade, "unitario_centavos": i.unitario_centavos, "centavos": i.total_centavos,
                              "obs": i.obs_item} for i in sorted(itens, key=lambda i: (i.data, i.compra_id), reverse=True)]
        return resposta
    grupos: Dict[str, Dict] = {}
    for i in itens:
        chave = subgrupo(i.produto, i.categoria) if categoria else i.categoria
        g = grupos.setdefault(chave, {"chave": chave, "rotulo": chave if categoria else CATEGORIAS.get(chave, chave),
                                      "centavos": 0, "itens": 0})
        g["centavos"] += i.total_centavos
        g["itens"] += 1
    resposta["nivel"] = "grupos" if categoria else "categorias"
    resposta["linhas"] = sorted(grupos.values(), key=lambda g: g["centavos"], reverse=True)
    return resposta
