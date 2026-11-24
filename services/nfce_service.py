"""
Leitor da NFC-e (página "Consulta Resumida" da Sefaz salva em HTML).

Lê direto dos campos da página, sem IA: estabelecimento, CNPJ, data de emissão, itens (código, nome,
quantidade, unidade, unitário, total), valor total, desconto, valor pago, forma de pagamento e chave
de acesso. Os dados do consumidor (CPF, nome) NUNCA são lidos.

O desconto é distribuído entre os itens, proporcionalmente, em centavos: a soma dos itens fica igual
ao valor pago.
"""
import html
import re
from datetime import datetime
from typing import Dict, List, Optional

from services.dinheiro import para_centavos, para_reais


class NotaInvalidaError(ValueError):
    """O arquivo não é uma NFC-e reconhecida."""


_RE_ITEM = re.compile(r'<tr id="Item \+ \d+">(.*?)</tr>', re.S)
_RE_TAMANHO = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ML|L|LT|G|GR|KG)\b", re.I)


def _texto(fragmento: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragmento or "")).split())


def _span(bloco: str, classe: str) -> str:
    achado = re.search(rf'<span class="{classe}"[^>]*>(.*?)</span>', bloco, re.S)
    return _texto(achado.group(1)) if achado else ""


def _depois_do_rotulo(texto: str) -> str:
    return texto.split(":", 1)[-1].strip() if ":" in texto else texto


def _numero(texto: str) -> float:
    return float(para_centavos(texto)) / 100 if "," in str(texto) else float(str(texto or 0).replace(" ", "") or 0)


def _total(html_nota: str, rotulo: str) -> Optional[str]:
    achado = re.search(rf"<label[^>]*>\s*{re.escape(rotulo)}\s*</label>\s*<span[^>]*>(.*?)</span>", html_nota, re.S)
    return _texto(achado.group(1)) if achado else None


def nome_estabelecimento(razao_social: str) -> str:
    """'IRMAOS MUFFATO E CIA LTDA' → 'Irmaos Muffato' (sem 'Ltda', 'S/A', 'E Cia', 'ME'...)."""
    nome = re.sub(r"\b(e\s+cia|ltda|s\s*/?\s*a|me|epp|eireli|comercio\s+de|com\.?)\b\.?", " ", razao_social or "", flags=re.I)
    nome = " ".join(nome.replace(" - ", " ").split()).strip(" -.,")
    return nome.title() if nome else "Não informado"


def eh_nfce(conteudo: str) -> bool:
    return "Consulta Resumida NFC-e" in conteudo or ('id="tabResult"' in conteudo and 'id="totalNota"' in conteudo)


def embalagem_pelo_nome(nome: str):
    """'LIMP TRIEX 500ML' → (0.5, 'litro'); 'ARROZ 5KG' → (5.0, 'kg'); sem tamanho → (None, None)."""
    achado = _RE_TAMANHO.search(nome or "")
    if not achado:
        return None, None
    valor, unidade = float(achado.group(1).replace(",", ".")), achado.group(2).upper()
    if unidade == "ML":
        return round(valor / 1000, 3), "litro"
    if unidade in ("L", "LT"):
        return valor, "litro"
    if unidade in ("G", "GR"):
        return round(valor / 1000, 3), "kg"
    return valor, "kg"


def distribuir_desconto(totais_centavos: List[int], desconto_centavos: int) -> List[int]:
    """Desconto proporcional ao total de cada item, em centavos, com a sobra para os maiores restos."""
    soma = sum(totais_centavos)
    if not soma or desconto_centavos <= 0:
        return list(totais_centavos)
    partes = [desconto_centavos * t / soma for t in totais_centavos]
    inteiros = [int(p) for p in partes]
    sobra = desconto_centavos - sum(inteiros)
    for i in sorted(range(len(partes)), key=lambda k: partes[k] - inteiros[k], reverse=True)[:sobra]:
        inteiros[i] += 1
    return [t - d for t, d in zip(totais_centavos, inteiros)]


def ler_nfce(conteudo: str) -> Dict:
    """HTML da NFC-e → {"estabelecimento", "cnpj", "data_compra", "itens", "valor_total_compra", ...}."""
    if not eh_nfce(conteudo):
        raise NotaInvalidaError("O arquivo não parece uma NFC-e (página de consulta da Sefaz).")
    estabelecimento = _texto((re.search(r'<div id="u20"[^>]*>(.*?)</div>', conteudo, re.S) or [None, ""])[1])
    cnpj = (re.search(r"CNPJ:\s*([\d./-]+)", _texto(conteudo)) or [None, None])[1]
    emissao = re.search(r"Emiss[ãa]o:\s*</strong>\s*(\d{2}/\d{2}/\d{4})", conteudo)
    data_compra = datetime.strptime(emissao.group(1), "%d/%m/%Y").date().isoformat() if emissao else None
    chave = re.sub(r"\D", "", _span(conteudo, "chave")) or None

    itens = []
    for bloco in _RE_ITEM.findall(conteudo):
        nome = _span(bloco, "txtTit")
        codigo = re.sub(r"\D", "", _span(bloco, "RCod")) or None
        quantidade = _numero(_depois_do_rotulo(_span(bloco, "Rqtd")))
        unidade = _depois_do_rotulo(_span(bloco, "RUN")).lower() or "un"
        unitario = _numero(_depois_do_rotulo(_span(bloco, "RvlUnit")))
        total = _numero(_span(bloco, "valor"))
        emb_qtd, emb_unid = embalagem_pelo_nome(nome) if unidade in ("un", "und", "pc", "pct", "cx") else (None, None)
        itens.append({"produto": nome, "codigo": codigo, "marca": None, "quantidade": quantidade,
                      "unidade": "kg" if unidade == "kg" else ("litro" if unidade in ("l", "lt") else "un"),
                      "valor_unitario": unitario, "valor_total": total, "categoria": "outros",
                      "embalagem_quantidade": emb_qtd, "embalagem_unidade": emb_unid})
    if not itens:
        raise NotaInvalidaError("Nenhum item encontrado na NFC-e.")

    total_nota = para_centavos(_total(conteudo, "Valor total R$:") or sum(i["valor_total"] for i in itens))
    desconto = para_centavos(_total(conteudo, "Descontos R$:") or 0)
    pago = para_centavos(_total(conteudo, "Valor a pagar R$:") or 0) or (total_nota - desconto)
    liquidos = distribuir_desconto([para_centavos(i["valor_total"]) for i in itens], total_nota - pago if pago else desconto)
    for item, liquido in zip(itens, liquidos):
        item["valor_bruto"] = item["valor_total"]
        item["valor_total"] = para_reais(liquido)
        item["valor_unitario"] = round(item["valor_total"] / item["quantidade"], 4) if item["quantidade"] else item["valor_total"]

    pagamento = re.search(r'<label class="tx">\s*(.*?)\s*</label>', conteudo, re.S)
    return {
        "estabelecimento": nome_estabelecimento(estabelecimento),
        "cnpj": cnpj, "data_compra": data_compra, "chave_acesso": chave,
        "itens": itens, "valor_total_compra": para_reais(sum(liquidos)),
        "valor_bruto": para_reais(total_nota), "desconto": para_reais(desconto),
        "forma_pagamento": _texto(pagamento.group(1)) if pagamento else None,
    }
