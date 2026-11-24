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
    nome = " ".join(p for p in nome.replace(" - ", " ").split() if p.strip(".,-")).strip(" -.,")
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
        itens.append(_item(_span(bloco, "txtTit"), re.sub(r"\D", "", _span(bloco, "RCod")) or None,
                           _numero(_depois_do_rotulo(_span(bloco, "Rqtd"))), _depois_do_rotulo(_span(bloco, "RUN")) or "un",
                           _numero(_depois_do_rotulo(_span(bloco, "RvlUnit"))), _numero(_span(bloco, "valor"))))
    pagamento = re.search(r'<label class="tx">\s*(.*?)\s*</label>', conteudo, re.S)
    return _com_identificacao(_fechar_nota(itens, estabelecimento, cnpj, data_compra, chave,
                                           _total(conteudo, "Valor total R$:"), _total(conteudo, "Descontos R$:"),
                                           _total(conteudo, "Valor a pagar R$:"), _texto(pagamento.group(1)) if pagamento else None),
                              _texto(conteudo))


def _item(nome, codigo, quantidade, unidade, unitario, total) -> Dict:
    unidade = (unidade or "un").lower()
    emb_qtd, emb_unid = embalagem_pelo_nome(nome) if unidade in ("un", "und", "pc", "pct", "cx") else (None, None)
    return {"produto": nome, "codigo": codigo, "marca": None, "quantidade": quantidade,
            "unidade": "kg" if unidade == "kg" else ("litro" if unidade in ("l", "lt") else "un"),
            "valor_unitario": unitario, "valor_total": total, "categoria": "outros",
            "embalagem_quantidade": emb_qtd, "embalagem_unidade": emb_unid}


def _fechar_nota(itens, estabelecimento, cnpj, data_compra, chave, total_txt, desconto_txt, pago_txt, pagamento) -> Dict:
    """Distribui o desconto nos itens (em centavos) e monta o resultado comum ao HTML e ao texto copiado."""
    if not itens:
        raise NotaInvalidaError("Nenhum item encontrado na NFC-e.")
    total_nota = para_centavos(total_txt or sum(i["valor_total"] for i in itens))
    desconto = para_centavos(desconto_txt or 0)
    pago = para_centavos(pago_txt or 0) or (total_nota - desconto)
    liquidos = distribuir_desconto([para_centavos(i["valor_total"]) for i in itens], total_nota - pago if pago else desconto)
    for item, liquido in zip(itens, liquidos):
        item["valor_bruto"] = item["valor_total"]
        item["valor_total"] = para_reais(liquido)
        item["valor_unitario"] = round(item["valor_total"] / item["quantidade"], 4) if item["quantidade"] else item["valor_total"]
    return {
        "estabelecimento": nome_estabelecimento(estabelecimento),
        "cnpj": cnpj, "data_compra": data_compra, "chave_acesso": chave,
        "itens": itens, "valor_total_compra": para_reais(sum(liquidos)),
        "valor_bruto": para_reais(total_nota), "desconto": para_reais(desconto),
        "forma_pagamento": pagamento,
    }


# Texto copiado da página da NFC-e e colado no chat
_RE_ITEM_TEXTO = re.compile(
    r"\(C[óo]digo:\s*(?P<cod>\d+)\s*\)\s*Qtde\.:\s*(?P<qtd>[\d.,]+)\s*UN:\s*(?P<un>[A-Za-z]+)\s*"
    r"Vl\. Unit\.:\s*(?P<unit>[\d.,]+)\s*Vl\. Total\s*(?P<tot>[\d.,]+)")


def parece_nfce_texto(texto: str) -> bool:
    return len(_RE_ITEM_TEXTO.findall(texto or "")) >= 1 and "Vl. Total" in (texto or "")


def _valor_depois(texto: str, rotulo: str) -> Optional[str]:
    achado = re.search(re.escape(rotulo) + r"\s*([\d.]*\d,\d{2})", texto)
    return achado.group(1) if achado else None


def ler_nfce_texto(texto: str) -> Dict:
    """Texto copiado da "Consulta Resumida NFC-e" (como sai ao selecionar a página) → mesmo formato de ler_nfce."""
    texto = " ".join((texto or "").split())
    achados = list(_RE_ITEM_TEXTO.finditer(texto))
    if not achados:
        raise NotaInvalidaError("O texto não parece uma NFC-e copiada da página da Sefaz.")
    itens, inicio = [], 0
    for n, achado in enumerate(achados):
        nome = texto[inicio:achado.start()].strip()
        if n == 0:
            # Antes do 1º item vêm o cabeçalho (loja, CNPJ, endereço ", Cidade , UF") ou uma frase ("Fiz a compra:")
            fim_endereco = list(re.finditer(r",\s*[A-Z]{2}\s+(?=[A-Z0-9])", nome))
            if fim_endereco:
                nome = nome[fim_endereco[-1].end():]
            elif ":" in nome:
                nome = nome.rsplit(":", 1)[1]
        itens.append(_item(nome.strip(" -:"), achado.group("cod"), _numero(achado.group("qtd")), achado.group("un"),
                           _numero(achado.group("unit")), _numero(achado.group("tot"))))
        inicio = achado.end()
    cabecalho = texto[:achados[0].start()]
    loja = re.search(r"^(.*?)\s+CNPJ:", cabecalho)
    cnpj = (re.search(r"CNPJ:\s*([\d./-]+)", cabecalho) or [None, None])[1]
    emissao = re.search(r"Emiss[ãa]o:\s*(\d{2}/\d{2}/\d{4})", texto)
    data = datetime.strptime(emissao.group(1), "%d/%m/%Y").date().isoformat() if emissao else None
    chave = re.search(r"Chave de acesso:\s*((?:\d{4}\s*){11})", texto)
    pagamento = re.search(r"Valor pago R\$:\s*([A-Za-zÀ-ú ]+?)\s*[\d.]*\d,\d{2}", texto)
    return _com_identificacao(_fechar_nota(itens, loja.group(1) if loja else None, cnpj, data,
                                           re.sub(r"\D", "", chave.group(1)) if chave else None,
                                           _valor_depois(texto, "Valor total R$:"), _valor_depois(texto, "Descontos R$:"),
                                           _valor_depois(texto, "Valor a pagar R$:"), pagamento.group(1).strip() if pagamento else None),
                              texto)


# Texto copiado da consulta completa da NF-e (modelo 55: loja de motos, eletrônicos, móveis...)
_NUM = r"[\d.]*\d,\d+"
_RE_ITEM_NFE = re.compile(rf"(?:^|\s)(\d{{1,3}})\s+(.+?)\s+({_NUM})\s+([A-Za-z]{{1,6}})\s+({_NUM})\s+({_NUM})(?=\s|$)")


def parece_nfe_texto(texto: str) -> bool:
    t = " ".join((texto or "").split())
    return bool(re.search(r"Emitente\b", t) and re.search(r"Produtos\b", t) and "Valor Prod" in t
                and re.search(r"Data/Hora da emiss[ãa]o", t))


def ler_nfe_texto(texto: str) -> Dict:
    """Consulta da NF-e (Dados da NFe / Emitente / Destinatário / Produtos). Os dados do destinatário não são lidos."""
    texto = " ".join((texto or "").split())
    produtos = re.search(r"Valor Prod\.?\s*(.*?)\s*Valor total\s+(" + _NUM + ")", texto)
    if not produtos:
        raise NotaInvalidaError("O texto não parece uma NF-e copiada da página da Sefaz.")
    itens = []
    for achado in _RE_ITEM_NFE.finditer(produtos.group(1)):
        nome = achado.group(2).strip()
        item = _item(nome, achado.group(1), _numero(achado.group(3)), achado.group(4),
                     _numero(achado.group(5)), _numero(achado.group(6)))
        item["nome_cortado"] = nome.endswith("...") or nome.endswith("…")
        itens.append(item)
    emitente = texto.split("Destinatário", 1)[0]   # só o trecho antes do destinatário
    loja = re.search(r"Emitente.*?Nome/Raz[ãa]o Social\s+(.*?)\s+(?:Munic[íi]pio|Endere[çc]o|UF)\b", emitente)
    cnpj = re.search(r"Emitente\s+CNPJ\s+([\d./-]+)", emitente)
    emissao = re.search(r"Data/Hora da emiss[ãa]o\s+(\d{2}/\d{2}/\d{4})", texto)
    data = datetime.strptime(emissao.group(1), "%d/%m/%Y").date().isoformat() if emissao else None
    chave = re.search(r"Chave de acesso\s+([\d\s-]{44,70})", texto)
    digitos = re.sub(r"\D", "", chave.group(1))[:44] if chave else ""
    return _com_identificacao(_fechar_nota(itens, loja.group(1) if loja else None, cnpj.group(1) if cnpj else None, data,
                                           digitos if len(digitos) == 44 else None, produtos.group(2), None, None, None),
                              texto)


# Dados do consumidor fora de qualquer registro (o leitor já não os lê; o texto guardado também não deve trazê-los)
_RE_CPF = re.compile(r"(?<![\d*])[\d*]{3}[.\s]?[\d*]{3}[.\s]?[\d*]{3}[-\s]?\d{2}(?!\d)")
_RE_BLOCO_DESTINATARIO = re.compile(
    r"Destinat[áa]rio\b.*?(?=\b(?:Produtos|Itens|Emitente|Eventos|Valor total|Dados da NF|Informa[çc][õo]es)\b|$)", re.S | re.I)
_RE_LINHA_CONSUMIDOR = re.compile(r"^.*\bCONSUMIDOR\b\s*[-:]?\s*(?:CPF|CNPJ|NOME|ID\b|N[ÃA]O IDENTIFICADO).*$", re.M | re.I)


def ocultar_consumidor(texto: str) -> str:
    """Tira o bloco do destinatário (NF-e), a linha do consumidor (NFC-e) e qualquer CPF do texto."""
    texto = _RE_BLOCO_DESTINATARIO.sub("Destinatário [omitido]\n", str(texto or ""))
    texto = _RE_LINHA_CONSUMIDOR.sub("[consumidor omitido]", texto)
    return _RE_CPF.sub("[CPF omitido]", texto)


def chave_valida(chave: str) -> bool:
    """Chave de acesso de 44 dígitos com o dígito verificador certo (módulo 11, pesos 2 a 9 da direita)."""
    if not chave or len(chave) != 44 or not chave.isdigit():
        return False
    soma = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(chave[:43])))
    resto = soma % 11
    return int(chave[43]) == (0 if resto < 2 else 11 - resto)


def chave_no_texto(texto: str):
    """Primeira chave de acesso válida no texto (transcrição de foto); leitura errada não passa no dígito verificador."""
    for achado in re.finditer(r"Chave de acesso[:\s]*([\d\s.\-/]{44,90})", str(texto or ""), re.I):
        digitos = re.sub(r"\D", "", achado.group(1))
        for inicio in range(0, max(1, len(digitos) - 43)):
            if chave_valida(digitos[inicio:inicio + 44]):
                return digitos[inicio:inicio + 44]
    return None


# Identificação da nota (NFC-e e NF-e): número (Código NF), série (Série NF) e emissão (data e hora da compra)
_RE_NUMERO_NF = re.compile(r"\bN[úu]mero(?:\s+(?:da\s+)?NF-?e)?\s*:?\s*(\d[\d.]{0,14})", re.I)
_RE_SERIE_NF = re.compile(r"\bS[ée]rie\s*:?\s*(\d{1,3})\b", re.I)
_RE_EMISSAO = re.compile(r"Emiss[ãa]o\s*:?\s*(\d{2}/\d{2}/\d{4})(?:\s+(?:[àa]s\s+)?(\d{2}:\d{2}(?::\d{2})?))?", re.I)


def identificacao(texto: str) -> Dict:
    """{"numero_nf", "serie_nf", "emissao" (AAAA-MM-DDTHH:MM:SS), "data_compra"} do texto da nota; ausentes ficam fora."""
    texto = " ".join(str(texto or "").replace("*", " ").split())
    dados = {}
    numero = _RE_NUMERO_NF.search(texto)
    if numero:
        dados["numero_nf"] = str(int(re.sub(r"\D", "", numero.group(1)) or 0)) if re.sub(r"\D", "", numero.group(1)) else None
    serie = _RE_SERIE_NF.search(texto)
    if serie:
        dados["serie_nf"] = str(int(serie.group(1)))
    emissao = _RE_EMISSAO.search(texto)
    if emissao:
        try:
            dia = datetime.strptime(emissao.group(1), "%d/%m/%Y")
            hora = (emissao.group(2) or "00:00:00")
            hora = hora if hora.count(":") == 2 else hora + ":00"
            dados["emissao"] = f"{dia.date().isoformat()}T{hora}"
            dados["data_compra"] = dia.date().isoformat()
        except ValueError:
            pass
    return {k: v for k, v in dados.items() if v}


def _com_identificacao(nota: Dict, texto: str) -> Dict:
    """A emissão é a data da compra; número e série vão junto."""
    nota.update(identificacao(texto))
    return nota
