"""
Perguntas antes de gravar uma compra: o que a nota não trouxe (loja) ou trouxe cortado (nome do produto).

Fluxo: o resumo mostra a compra e faz a 1ª pergunta; cada resposta preenche um campo e puxa a próxima;
sem perguntas restantes, pede "sim" ou "não". "pular" mantém o valor da nota; "sim" grava como está;
"não" descarta a compra.
"""
from typing import Dict, List, Optional

from services.dinheiro import formatar as _formatar_centavos, para_centavos
from services.produtos_service import inferir_categoria

PEDIR_CONFIRMACAO = 'Responda "sim" para gravar ou "não" para descartar.'
RESPOSTAS_PULAR = {"pular", "pula", "manter", "mantem", "deixa", "deixa assim", "tanto faz", "nao sei"}
def formatar(valor) -> str:
    return _formatar_centavos(para_centavos(valor or 0))


LOJA_AUSENTE = {None, "", "Não informado", "Nao informado"}
DUVIDAS_RESOLVIDAS_POR_PERGUNTA = {"Loja não informada.", "A loja não veio no texto colado."}


def nome_cortado(item: Dict) -> bool:
    nome = str(item.get("produto") or "").strip()
    return bool(item.get("nome_cortado")) or nome.endswith("...") or nome.endswith("…")


def perguntas_faltando(compras: List[Dict]) -> List[Dict]:
    perguntas = []
    for c, compra in enumerate(compras):
        if compra.get("estabelecimento") in LOJA_AUSENTE:
            perguntas.append({"campo": "loja", "compra": c})
        for i, item in enumerate(compra.get("itens", [])):
            if nome_cortado(item):
                perguntas.append({"campo": "produto", "compra": c, "item": i})
    return perguntas


def texto_pergunta(pergunta: Dict, compras: List[Dict]) -> str:
    compra = compras[pergunta["compra"]]
    if pergunta["campo"] == "loja":
        return (f"❓ Em qual loja foi essa compra (total {formatar(compra.get('valor_total_compra') or 0)})? "
                'Responda com o nome, "pular" para deixar sem loja ou "não" para descartar.')
    item = compra["itens"][pergunta["item"]]
    return (f"❓ Qual produto você comprou? A nota mostra só \"{item.get('nome_cupom') or item['produto']}\" "
            f"({formatar(item.get('valor_total') or 0)}) em {compra.get('estabelecimento') or 'loja não informada'}. "
            'Responda com o nome do produto (ex.: "moto honda cg 160"), "pular" para manter assim ou "não" para descartar.')


def aplicar_resposta(compras: List[Dict], pergunta: Dict, texto: str) -> None:
    valor = " ".join(str(texto or "").split()).strip(" .,!\"'")[:80]
    if not valor:
        return
    compra = compras[pergunta["compra"]]
    if pergunta["campo"] == "loja":
        compra["estabelecimento"] = valor
        return
    item = compra["itens"][pergunta["item"]]
    item["produto"] = valor.lower()
    item["nome_cortado"] = False
    item["categoria"] = inferir_categoria(item["produto"], "outros")


def abrir(cabecalho: str, resumo: str, compras: List[Dict], origem: Optional[Dict],
          duvidas: Optional[List[str]] = None) -> Dict:
    """Monta a primeira mensagem de confirmação e a pendência (com as perguntas que faltam)."""
    perguntas = perguntas_faltando(compras)
    duvidas = [d for d in (duvidas or []) if not (perguntas and d in DUVIDAS_RESOLVIDAS_POR_PERGUNTA)]
    partes = [p for p in (cabecalho, resumo) if p]
    if duvidas:
        partes.append("Pontos de dúvida:\n" + "\n".join(f"- {d}" for d in duvidas))
    partes.append(texto_pergunta(perguntas[0], compras) if perguntas else PEDIR_CONFIRMACAO)
    return {"texto": "\n".join(partes[:-1]) + "\n\n" + partes[-1],
            "pendencia": {"compras": compras, "origem": origem, "perguntas": perguntas}}
