"""
Cartão de compra (M28, M38): a compra que espera "sim" ou "não" vai também em forma estruturada, para as telas
desenharem um cartão (loja, data, total, itens e botões Sim / Corrigir / Não) em vez do bloco de texto.

O texto completo continua em "text" (telas antigas, Telegram, voz e histórico usam ele); o cartão leva
em "texto" a mesma mensagem sem o bloco do resumo, que passa a ser o próprio cartão.
"""
import re
from typing import Dict, Optional, Tuple

from services.dinheiro import para_centavos


def _nome_item(item: Dict) -> str:
    # Mesmo nome mostrado no resumo em texto (formatar_resumo)
    nome = item.get("produto") or "Produto"
    marca = item.get("marca") or ""
    if marca and marca.lower() not in nome.lower():
        nome = f"{nome} {marca}"
    if item.get("embalagem_quantidade"):
        q = item["embalagem_quantidade"]
        q = int(q) if float(q).is_integer() else q
        nome = f"{nome} ({q} {item.get('embalagem_unidade') or ''})".replace(" )", ")")
    return nome


def _compra(compra: Dict) -> Dict:
    return {
        "loja": compra.get("estabelecimento") or "Loja não informada",
        "data": compra.get("data_compra"),
        "total_centavos": para_centavos(compra.get("valor_total_compra") or 0),
        "numero_nf": compra.get("numero_nf"),
        "serie_nf": compra.get("serie_nf"),
        "emissao": compra.get("emissao"),
        "obs": compra.get("observacao") or None,
        "desconto_centavos": para_centavos(compra["desconto"]) if compra.get("desconto") else None,
        "itens": [{"produto": _nome_item(i), "quantidade": i.get("quantidade") or 1, "unidade": i.get("unidade") or "un",
                   "unitario_centavos": para_centavos(i.get("valor_unitario") or 0),
                   "total_centavos": para_centavos(i.get("valor_total") or 0), "obs": i.get("observacao") or None}
                  for i in compra.get("itens", [])],
    }


def montar(texto: str, pendencia) -> Optional[Dict]:
    """Cartão da compra pendente, se a mensagem mostra o resumo dela; senão None (a tela usa só o texto)."""
    if not texto or not pendencia or pendencia[0] != "compras":
        return None
    dados = pendencia[1]
    if not isinstance(dados, dict) or "edicao" in dados or not dados.get("compras"):
        return None
    from services.shopping_assistant import ShoppingAssistant
    resumo = ShoppingAssistant.formatar_resumo(dados["compras"])
    if not resumo or resumo not in texto:
        return None
    inicio = texto.index(resumo)
    antes, depois = texto[:inicio].strip(), texto[inicio + len(resumo):].strip()
    return {
        "tipo": "compra",
        "antes": antes,     # ex.: "📄 Nota fiscal recebida (nota.html):" ou "Ficou assim:" (vai acima do cartão)
        "depois": depois,   # ex.: dúvidas e o pedido de confirmação (vai abaixo)
        "texto": re.sub(r"\n{3,}", "\n\n", f"{antes}\n\n{depois}").strip(),
        "confirmar": not dados.get("perguntas"),   # com pergunta pendente (loja, nome cortado) os botões são os da pergunta
        "compras": [_compra(c) for c in dados["compras"]],
    }


def de_compra(compra: Dict, antes: str = "", depois: str = "") -> Dict:
    """M38: cartão só para leitura de uma compra já gravada (detalhe), sem botões de confirmação."""
    return {"tipo": "compra", "antes": antes, "depois": depois, "texto": f"{antes}\n\n{depois}".strip(),
            "confirmar": False, "compras": [_compra(compra)]}


def grafico(titulo: str, ranking, total_centavos: int, periodo=None, rotulos: Optional[Dict] = None, limite: int = 8) -> Dict:
    """Gráfico de barras para a conversa (consultas por categoria ou por loja), com atalho para o painel."""
    rotulos = rotulos or {}
    linhas = [{"rotulo": rotulos.get(chave, chave), "chave": chave, "centavos": int(valor),
               "pct": round(100 * valor / total_centavos, 1) if total_centavos else 0} for chave, valor in ranking[:limite]]
    resto = sum(v for _, v in ranking[limite:])
    if resto:
        linhas.append({"rotulo": f"Outras ({len(ranking) - limite})", "chave": None, "centavos": int(resto),
                       "pct": round(100 * resto / total_centavos, 1) if total_centavos else 0})
    painel = {}
    if periodo is not None:
        # Período de um mês inteiro: o painel abre direto nesse mês
        if periodo.inicio.day == 1 and periodo.inicio.strftime("%Y-%m") == periodo.fim.strftime("%Y-%m"):
            painel["mes"] = periodo.inicio.strftime("%Y-%m")
    return {"tipo": "grafico", "antes": titulo, "depois": "", "texto": titulo, "total_centavos": int(total_centavos),
            "linhas": linhas, "painel": painel}


def payload(texto: str, pendencia, cartao: Optional[Dict] = None) -> Dict:
    """Corpo do assistant_message: o texto e, quando houver, o cartão (dado pela skill ou montado da compra pendente)."""
    corpo = {"text": texto}
    cartao = cartao or montar(texto, pendencia)
    if cartao:
        corpo["cartao"] = cartao
    return corpo
