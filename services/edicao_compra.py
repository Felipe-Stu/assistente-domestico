"""
M10: correção de uma compra já gravada.

O modelo (ou, sem ele, regras) diz o que mudar: [{"campo", "item", "valor"}]. Aqui, sem modelo:
  1. localizar_compra: número citado ("compra 7"), loja, data e item citados; sem pistas, a última registrada.
  2. aplicar: copia a compra, aplica cada mudança e refaz as contas (total = unitário × quantidade).
A gravação (DatabaseService.editar_compra) só acontece depois do "sim".
"""
import copy
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from services.dinheiro import formatar_reais
from services.periodos import encontrar_periodos
from services.produtos_service import _sem_acentos, chave_produto, inferir_categoria

CAMPOS = ("produto", "quantidade", "valor_unitario", "valor_total", "loja", "data", "remover_item", "observacao")
MODOS_OBSERVACAO = ("acrescentar", "substituir", "apagar")
TODOS_OS_ITENS = {"*", "todos", "todos os itens", "cada item", "itens", "todos itens"}
_RE_NUMERO_COMPRA = re.compile(r"\bcompra\s+(?:n(?:umero|º|o|°|\.)?\s*)?(\d{1,6})\b")
_RE_VALOR = re.compile(r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)")


class EdicaoError(ValueError):
    pass


def _norm(texto) -> str:
    return " ".join(_sem_acentos(str(texto or "")).replace("-", " ").split())


def ler_numero(texto) -> Optional[float]:
    """'35' / '35,90' / 'R$ 1.234,50' / '2 litros' → número."""
    achado = _RE_VALOR.search(str(texto or ""))
    if not achado:
        return None
    bruto = achado.group(1)
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    elif bruto.count(".") == 1 and len(bruto.split(".")[1]) == 3 and "R$" in str(texto):
        bruto = bruto.replace(".", "")   # "R$ 1.234" = mil duzentos e trinta e quatro
    try:
        return float(bruto)
    except ValueError:
        return None


def ler_data(texto, hoje: Optional[date] = None) -> Optional[str]:
    texto = str(texto or "").strip()
    try:
        return date.fromisoformat(texto[:10]).isoformat()
    except ValueError:
        pass
    periodos = encontrar_periodos(texto, hoje)
    return periodos[0].inicio_iso if periodos and periodos[0].inicio == periodos[0].fim else None


def item_combina(procurado: str, nome: str) -> bool:
    alvo_norm, nome_norm = _norm(procurado).strip(" ."), _norm(nome).strip(" .")
    if not alvo_norm:
        return False
    if alvo_norm == nome_norm or (len(alvo_norm) > 2 and alvo_norm in nome_norm):
        return True
    palavras = [p for p in chave_produto(procurado).split() if len(p) > 1]
    alvo = set(chave_produto(nome).split())
    alvo |= {p[:-1] for p in alvo if p.endswith("s")}
    return bool(palavras) and all(p in alvo or p.rstrip("s") in alvo for p in palavras)


def localizar_compra(db, texto: str, mudancas: List[Dict], loja: Optional[str] = None,
                     hoje: Optional[date] = None) -> Optional[int]:
    normal = _norm(texto)
    numero = _RE_NUMERO_COMPRA.search(normal)
    if numero:
        linha = db.executar_consulta_uma_linha("SELECT id FROM compras WHERE id = ?", (int(numero.group(1)),))
        return linha[0] if linha else None
    compras = db.executar_consulta("SELECT id, data_compra, COALESCE(nome_comercio, '') FROM compras ORDER BY id DESC")
    if loja and _norm(loja) in normal:
        compras = [c for c in compras if _norm(loja) in _norm(c[2])] or compras
    # Data citada localiza a compra, a não ser que a própria data seja o que se quer corrigir
    if not any(m.get("campo") == "data" for m in mudancas):
        periodos = encontrar_periodos(texto, hoje)
        if periodos:
            p = periodos[0]
            compras = [c for c in compras if p.inicio_iso <= (c[1] or "") <= p.fim_iso]
    nomes = [m["item"] for m in mudancas if m.get("item")]
    if nomes:
        com_item = []
        for c in compras:
            produtos = [r[0] for r in db.executar_consulta("SELECT produto FROM itens_compra WHERE compra_id = ?", (c[0],))]
            if all(any(item_combina(n, p) for p in produtos) for n in nomes):
                com_item.append(c)
        compras = com_item
    return compras[0][0] if compras else None


def _achar_item(compra: Dict, nome: Optional[str]) -> Dict:
    itens = [i for i in compra["itens"] if not i.get("remover")]
    if not nome:
        if len(itens) == 1:
            return itens[0]
        raise EdicaoError("Qual item? A compra tem: " + ", ".join(i["produto"] for i in itens) + ".")
    achados = [i for i in itens if item_combina(nome, i["produto"])]
    if len(achados) == 1:
        return achados[0]
    exatos = [i for i in achados if _norm(i["produto"]) == _norm(nome)]
    if len(exatos) == 1:
        return exatos[0]
    if not achados:
        raise EdicaoError(f"Não achei \"{nome}\" nessa compra. Itens: " + ", ".join(i["produto"] for i in itens) + ".")
    raise EdicaoError(f"Há mais de um item parecido com \"{nome}\": " + ", ".join(i["produto"] for i in achados) + ". Diga qual.")


def aplicar(compra: Dict, mudancas: List[Dict], hoje: Optional[date] = None) -> Tuple[Dict, List[str]]:
    """Compra corrigida (cópia) e a descrição de cada mudança, para o resumo."""
    nova = copy.deepcopy(compra)
    linhas = []
    for m in mudancas:
        campo, valor = m.get("campo"), m.get("valor")
        texto_valor = " ".join(str(valor or "").split()).strip(" .,!\"'")
        if campo not in CAMPOS:
            continue
        if campo == "loja":
            if not texto_valor:
                raise EdicaoError("Qual é o nome certo da loja?")
            linhas.append(f"loja: {nova['estabelecimento']} → {texto_valor}")
            nova["estabelecimento"] = texto_valor[:80]
            continue
        if campo == "observacao":
            linhas.extend(_aplicar_observacao(nova, m, texto_valor))
            continue
        if campo == "data":
            nova_data = ler_data(texto_valor, hoje)
            if not nova_data:
                raise EdicaoError("Não entendi a data. Diga no formato dd/mm/aaaa.")
            linhas.append(f"data: {_data_br(nova['data_compra'])} → {_data_br(nova_data)}")
            nova["data_compra"] = nova_data
            continue
        item = _achar_item(nova, m.get("item"))
        if campo == "remover_item":
            if sum(1 for i in nova["itens"] if not i.get("remover")) == 1:
                raise EdicaoError("Esse é o único item da compra. Para apagá-la, diga \"desfazer última compra\".")
            item["remover"] = True
            linhas.append(f"remover: {item['produto']} ({formatar_reais(item['valor_total'])})")
            continue
        if campo == "produto":
            if not texto_valor:
                raise EdicaoError("Qual é o nome certo do produto?")
            linhas.append(f"nome: {item['produto']} → {texto_valor.lower()}")
            item["produto"] = texto_valor.lower()[:80]
            item["categoria"] = inferir_categoria(item["produto"], "outros")
            continue
        numero = ler_numero(texto_valor)
        if numero is None or numero <= 0:
            raise EdicaoError(f"Não entendi o novo valor ({texto_valor or 'vazio'}).")
        qtd = float(item["quantidade"] or 1)
        if campo == "quantidade":
            linhas.append(f"{item['produto']}: quantidade {_qtd(qtd)} → {_qtd(numero)}")
            item["quantidade"] = numero
            item["valor_total"] = round(numero * float(item["valor_unitario"]), 2)
        elif campo == "valor_unitario":
            linhas.append(f"{item['produto']}: preço unitário {formatar_reais(item['valor_unitario'])} → {formatar_reais(numero)}")
            item["valor_unitario"] = numero
            item["valor_total"] = round(numero * qtd, 2)
        else:   # valor_total
            linhas.append(f"{item['produto']}: valor {formatar_reais(item['valor_total'])} → {formatar_reais(numero)}")
            item["valor_total"] = numero
            item["valor_unitario"] = round(numero / qtd, 4) if qtd else numero
    if not linhas:
        raise EdicaoError("Não entendi o que corrigir. Ex.: \"o vinho custou 35\", \"renomeie c... para moto\", "
                          "\"a compra do Muffato foi dia 13/11\".")
    nova["valor_total_compra"] = round(sum(float(i["valor_total"]) for i in nova["itens"] if not i.get("remover")), 2)
    return nova, linhas


def _juntar_observacao(atual: Optional[str], texto: str, modo: str) -> Optional[str]:
    if modo == "apagar":
        return None
    if modo == "substituir" or not atual:
        return texto[:300]
    return f"{atual}; {texto}"[:300]


def _aplicar_observacao(compra: Dict, m: Dict, texto: str) -> List[str]:
    """Observação na compra (sem item) ou em itens: acrescenta (padrão), substitui ou apaga."""
    modo = m.get("modo") if m.get("modo") in MODOS_OBSERVACAO else "acrescentar"
    if modo != "apagar" and not texto:
        raise EdicaoError("Qual é o texto da observação?")
    nome = (m.get("item") or "").strip()
    if not nome:
        compra["observacao"] = _juntar_observacao(compra.get("observacao"), texto, modo)
        return [f"observação da compra: {compra['observacao'] or '(apagada)'}"]
    alvos = ([i for i in compra["itens"] if not i.get("remover")] if _norm(nome) in TODOS_OS_ITENS
             else [_achar_item(compra, nome)])
    linhas = []
    for item in alvos:
        item["observacao"] = _juntar_observacao(item.get("observacao"), texto, modo)
        linhas.append(f"observação de {item['produto']}: {item['observacao'] or '(apagada)'}")
    return linhas


def _data_br(iso: Optional[str]) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" if iso and len(iso) >= 10 else (iso or "?")


def _qtd(valor: float) -> str:
    return str(int(valor)) if float(valor).is_integer() else f"{valor:.3f}".rstrip("0").rstrip(".").replace(".", ",")


# Plano B sem modelo: frases comuns de correção
_REGRAS = [
    ("produto", re.compile(r"\b(?:renome\w*|troqu\w* o nome d[eoa]s?|mud\w* o nome d[eoa]s?)\s+(?:o\s+|a\s+)?(?P<item>.+?)\s+(?:para|por|pra)\s+(?P<valor>.+)$")),
    ("remover_item", re.compile(r"\b(?:tire|tira|remova|remove|apague|apaga|exclua|exclui)\s+(?:o\s+|a\s+|os\s+|as\s+)?(?P<item>.+?)\s+d(?:a|essa|esta|aquela)\s+(?:ultima\s+)?compra\b")),
    ("loja", re.compile(r"\b(?:a\s+)?(?:loja|mercado)\s+(?:certa\s+|correta\s+)?(?:era|e|foi|eh)\s+(?:o\s+|a\s+)?(?P<valor>.+)$")),
    ("data", re.compile(r"\b(?:foi|era)\s+(?:no\s+|em\s+)?(?:dia\s+)?(?P<valor>\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b")),
    ("quantidade", re.compile(r"\b(?:eram|foram|era|foi)\s+(?P<valor>\d+(?:[.,]\d+)?)\s*(?:un\w*|kg|quilos?|litros?|l|g|gramas?|pacotes?|caixas?)?\s+(?:de\s+)?(?P<item>[a-z].+?)(?:\s+e\s+nao\b.*)?$")),
    ("valor_total", re.compile(r"(?:\bo\s+|\ba\s+|\bos\s+|\bas\s+)?(?P<item>[a-z][a-z0-9 ]*?)\s+(?:custou|custaram|era|foi|saiu|sairam|ficou|ficaram)\s+(?:por\s+|de\s+)?(?:r\$\s*)?(?P<valor>\d+(?:[.,]\d+)?)\b")),
]


_RE_OBS_ASPAS = re.compile(r"observa\w*.*?[\"“”«](?P<valor>[^\"“”»]+)[\"“”»]", re.I | re.S)
_RE_OBS_DOIS_PONTOS = re.compile(r"\b(?:obs|observa\w*)\s*[:\-]\s*(?P<valor>.+)$", re.I | re.S)
_RE_OBS_APAGAR = re.compile(r"\b(?:apague|apaga|remova|remove|tire|tira|limpe|limpa)\s+(?:a\s+)?observa", re.I)
_RE_OBS_ITEM = re.compile(r"\b(?:no|na|ao|do|da)\s+item\s+(?P<item>.+?)(?=\s*(?:[,:\"“]|\ba\s+observa|\bobserva|"
                          r"\b(?:d[aoe]s?|n[ao]s?|para)\s+(?:ultima\s+)?compra\b|$))", re.I)


def observacao_por_regra(texto: str) -> List[Dict]:
    """Pedidos de observação, lidos no texto original (o texto da observação mantém maiúsculas e acentos)."""
    if not re.search(r"\b(?:obs|observa\w*)\b", _norm(texto)):
        return []
    item = _RE_OBS_ITEM.search(texto)
    nome_item = item.group("item").strip() if item else None
    if _RE_OBS_APAGAR.search(texto):
        return [{"campo": "observacao", "item": nome_item, "valor": None, "modo": "apagar"}]
    achado = _RE_OBS_ASPAS.search(texto) or _RE_OBS_DOIS_PONTOS.search(texto)
    if not achado:
        return []
    modo = "substituir" if re.search(r"\b(?:troque|troca|substitua|mude|altere)\b", _norm(texto)) else "acrescentar"
    return [{"campo": "observacao", "item": nome_item, "valor": achado.group("valor").strip(), "modo": modo}]


def mudancas_por_regra(texto: str) -> List[Dict]:
    observacao = observacao_por_regra(texto)
    if observacao:
        return observacao
    normal = _norm(texto).strip(" .!?")
    normal = re.sub(r"^(?:na verdade|corrija|corrigir|corrige|edite|editar|altere|alterar)[,:]?\s+", "", normal)
    normal = re.sub(r"^(?:na|da|nessa|dessa|nesta|desta)\s+(?:ultima\s+)?compra(?:\s+(?:n(?:umero|o)?\s*)?\d+|\s+d[oa]\s+\S+)?[,:]?\s+", "", normal)
    normal = re.sub(r"\s+(?:n|d)(?:essa|esta|aquela)\s+compra\b", "", normal) if not re.search(r"\b(?:tire|tira|remova|remove|apague|apaga|exclua|exclui)\b", normal) else normal
    for campo, padrao in _REGRAS:
        m = padrao.search(normal)
        if m:
            grupos = m.groupdict()
            valor = grupos.get("valor")
            if campo == "loja" and valor:
                # Nome da loja como foi escrito (maiúsculas e acentos): as últimas palavras da frase original
                valor = " ".join(str(texto).strip(" .!?").split()[-len(valor.split()):])
            return [{"campo": campo, "item": (grupos.get("item") or "").strip() or None, "valor": valor}]
    return []
