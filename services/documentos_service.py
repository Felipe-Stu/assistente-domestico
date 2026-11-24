"""
Importação de documentos de compra: NFC-e em HTML, PDF e foto do cupom.

- NFC-e (HTML da Sefaz): leitor exato (services/nfce_service.py); o modelo local só deixa os nomes
  abreviados legíveis e escolhe a categoria (se o Ollama estiver fechado, ficam os nomes do cupom).
- PDF: o texto é extraído (pypdf) e vai para a mesma extração das compras por texto.
- Foto: um modelo local que entende imagem lê o cupom (OLLAMA_MODELO_VISAO).

Em todos os casos o resultado vira uma compra preparada, no mesmo formato da skill compras, e espera
"sim" ou "não" antes de gravar. O original é copiado para ANEXOS_DIR e ligado à compra pela tabela
entradas (M09); a chave de acesso da nota evita registrar a mesma nota duas vezes. Dados do consumidor
(CPF, nome) não são lidos.
"""
import hashlib
import json
import re
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from core.skills import obter_catalogo
from services import imagem_service, nfce_service
from services.dinheiro import formatar_reais, para_centavos
from services.esquemas import ESQUEMA_COMPRAS
from services.logger_service import logger as custom_logger
from services.produtos_service import CATEGORIAS, inferir_categoria

COMPONENTE = "documentos"
EXTENSOES = {".html": "html", ".htm": "html", ".txt": "html", ".pdf": "pdf",
             ".jpg": "imagem", ".jpeg": "imagem", ".png": "imagem", ".webp": "imagem"}
ESQUEMA_NOMES = {
    "type": "object",
    "properties": {"itens": {"type": "array", "items": {
        "type": "object",
        "properties": {"codigo": {"type": "string"}, "produto": {"type": "string"},
                       "categoria": {"type": "string", "enum": list(CATEGORIAS)}},
        "required": ["codigo", "produto", "categoria"]}}},
    "required": ["itens"],
}


class DocumentoError(Exception):
    """Mensagem para o usuário: o documento não pôde ser importado."""


def tipo_do_arquivo(caminho: Path) -> Optional[str]:
    return EXTENSOES.get(Path(caminho).suffix.lower())


_RE_REPETICAO = re.compile(r"(.{1,6}?)\1{12,}", re.S)


def limpar_transcricao(texto: str) -> str:
    """Tira o laço de repetição ("C/C/C/...") e linhas vazias em excesso."""
    texto = _RE_REPETICAO.sub(r"\1", str(texto or ""))
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


_RE_DATA_BR = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def datas_da_transcricao(texto: str) -> list:
    """Datas dd/mm/aaaa da transcrição, a de emissão primeiro (quando o rótulo aparece)."""
    texto = str(texto or "")
    emissao = re.search(r"emiss[ãa]o", texto, re.I)
    ordenado = texto[emissao.start():] + "\n" + texto[:emissao.start()] if emissao else texto
    datas = []
    for d, m, a in _RE_DATA_BR.findall(ordenado):
        try:
            iso = date(int(a), int(m), int(d)).isoformat()
        except ValueError:
            continue
        if iso not in datas:
            datas.append(iso)
    return datas


_RE_DESCONTO = re.compile(r"Descontos?\s*(?:R\$)?\s*:?\s*(\d{1,3}(?:\.\d{3})*,\d{2})", re.I)
_RE_A_PAGAR = re.compile(r"Valor\s+(?:a\s+pagar|pago|l[íi]quido)\s*(?:R\$)?\s*:?\s*(\d{1,3}(?:\.\d{3})*,\d{2})", re.I)


def aplicar_desconto_lido(compra: Dict, transcricao: str) -> None:
    """Desconto da nota (lido na foto) distribuído nos itens, quando a conta fecha: soma dos itens − desconto = valor pago."""
    if compra.get("desconto"):
        return
    texto = " ".join(str(transcricao or "").replace("*", " ").split())
    desconto, pago = _RE_DESCONTO.search(texto), _RE_A_PAGAR.search(texto)
    if not desconto or not pago:
        return
    d, p = para_centavos(desconto.group(1)), para_centavos(pago.group(1))
    itens = compra.get("itens") or []
    totais = [para_centavos(i.get("valor_total") or 0) for i in itens]
    if d <= 0 or not itens or abs(sum(totais) - d - p) > 5:
        return
    for item, liquido in zip(itens, nfce_service.distribuir_desconto(totais, d)):
        item["valor_bruto"] = item.get("valor_total")
        item["valor_total"] = liquido / 100
        qtd = float(item.get("quantidade") or 1)
        item["valor_unitario"] = round(item["valor_total"] / qtd, 4) if qtd else item["valor_total"]
    compra["valor_bruto"] = sum(totais) / 100
    compra["desconto"] = d / 100
    compra["valor_total_compra"] = round(sum(i["valor_total"] for i in itens), 2)


def data_suspeita(data_iso, hoje: date) -> bool:
    """Data no futuro ou com mais de um ano: modelo de imagem costuma errar o ano."""
    try:
        dia = date.fromisoformat(str(data_iso)[:10])
    except ValueError:
        return True
    return dia > hoje or (hoje - dia).days > 365


class DocumentosService:
    def __init__(self, db, compras, pasta_anexos: Path, llm_nomes=None, llm_visao=None,
                 tamanho_max_mb: float = 20, agora=datetime.now):
        self.db = db
        self.compras = compras
        self.pasta_anexos = Path(pasta_anexos)
        self.llm_nomes = llm_nomes
        self.llm_visao = llm_visao
        self.tamanho_max = int(tamanho_max_mb * 1024 * 1024)
        self._agora = agora

    # ------------------------------------------------------------------

    def guardar_original(self, caminho: Path) -> Path:
        """Cópia do original em ANEXOS_DIR/AAAA-MM/<hash>-<nome> (o arquivo de entrada não é alterado)."""
        conteudo = Path(caminho).read_bytes()
        destino = self.pasta_anexos / self._agora().strftime("%Y-%m") / f"{hashlib.sha1(conteudo).hexdigest()[:10]}-{Path(caminho).name}"
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not destino.exists():
            shutil.copy2(caminho, destino)
        return destino

    def importar(self, caminho, canal: str = "pasta") -> Dict:
        caminho = Path(caminho)
        tipo = tipo_do_arquivo(caminho)
        if tipo is None:
            raise DocumentoError(f"Formato não suportado: {caminho.suffix or 'sem extensão'}. Use HTML da NFC-e, PDF ou foto (JPG/PNG).")
        if caminho.stat().st_size > self.tamanho_max:
            raise DocumentoError(f"Arquivo maior que {self.tamanho_max // (1024 * 1024)} MB.")
        inicio = time.monotonic()
        anexo = self.guardar_original(caminho)
        if tipo == "html":
            preparada = self._importar_nfce(caminho)
        elif tipo == "pdf":
            preparada = self._importar_pdf(caminho, canal)
        else:
            preparada = self._importar_imagem(anexo)
        if not preparada["compras"]:
            raise DocumentoError("Não encontrei itens de compra nesse documento.")
        self._avisar_repetida(preparada)
        origem = preparada.setdefault("origem", {})
        origem.update({"tipo": "nota", "canal": canal, "anexo": str(anexo),
                       "texto": origem.get("texto") or f"Arquivo: {caminho.name}",
                       "duracao_ms": int((time.monotonic() - inicio) * 1000)})
        custom_logger.evento(COMPONENTE, "importado", tipo=tipo, canal=canal, itens=len(preparada["compras"][0]["itens"]))
        return preparada

    def resumo(self, preparada: Dict, com_duvidas: bool = True) -> str:
        compra = preparada["compras"][0]
        linhas = [self.compras.formatar_resumo(preparada["compras"])]
        if compra.get("desconto"):
            linhas.append(f"Desconto de {formatar_reais(compra['desconto'])} já distribuído nos itens "
                          f"(preço cheio {formatar_reais(compra.get('valor_bruto'))}).")
        if com_duvidas and preparada.get("duvidas"):
            linhas.append("Pontos de dúvida:\n" + "\n".join(f"- {d}" for d in preparada["duvidas"]))
        return "\n".join(linhas)

    # ------------------------------------------------------------------

    def importar_texto(self, texto: str, canal: str = "chat") -> Dict:
        """Texto da NFC-e copiado da página e colado no chat: mesmo leitor exato, mesma confirmação."""
        inicio = time.monotonic()
        nfe = nfce_service.parece_nfe_texto(texto) and not nfce_service.parece_nfce_texto(texto)
        try:
            nota = nfce_service.ler_nfe_texto(texto) if nfe else nfce_service.ler_nfce_texto(texto)
        except nfce_service.NotaInvalidaError as erro:
            raise DocumentoError(str(erro)) from None
        preparada = self._preparar_nota(nota)
        self._avisar_repetida(preparada)
        preparada["origem"].update({"tipo": "nota", "canal": canal, "texto": nfce_service.ocultar_consumidor(texto)[:20000],
                                    "versao_prompt": "nfe-texto-v1" if nfe else "nfce-texto-v1", "duracao_ms": int((time.monotonic() - inicio) * 1000)})
        return preparada

    def _importar_nfce(self, caminho: Path) -> Dict:
        bruto = caminho.read_bytes()
        conteudo = bruto.decode("utf-8", errors="replace")
        if "\ufffd" in conteudo:
            conteudo = bruto.decode("latin-1")
        try:
            nota = nfce_service.ler_nfce(conteudo)
        except nfce_service.NotaInvalidaError as erro:
            raise DocumentoError(str(erro)) from None
        return self._preparar_nota(nota)

    def _avisar_repetida(self, preparada: Dict) -> None:
        """Mesmo valor de uma compra dos últimos 120 dias: provável nota repetida (foto não tem chave de acesso)."""
        try:
            compra = preparada["compras"][0]
            centavos = para_centavos(compra.get("valor_total_compra") or 0)
            if centavos <= 0:
                return
            linhas = self.db.executar_consulta(
                "SELECT id, data_compra, nome_comercio FROM compras WHERE total_centavos = ? AND data_compra >= ? "
                "ORDER BY id DESC LIMIT 3", (centavos, (self._agora().date() - timedelta(days=120)).isoformat()))
        except Exception:   # aviso é ajuda, não pode impedir a importação
            return
        for compra_id, data, loja in linhas:
            preparada.setdefault("duvidas", []).append(
                f"Pode ser repetida: a compra #{compra_id} ({data[8:10]}/{data[5:7]}/{data[0:4]} · {loja}) tem o mesmo valor. "
                "Se for a mesma, responda \"não\".")

    def _preparar_nota(self, nota: Dict) -> Dict:
        if self.db.documento_ja_gravado(nota.get("chave_acesso")):
            raise DocumentoError("Essa nota já foi registrada (mesma chave de acesso).")
        modelo = self._nomes_legiveis(nota["itens"])
        validada = self.compras._validar_e_sanitizar_compra(nota)
        validada["data_compra"] = nota.get("data_compra") or date.today().isoformat()
        for chave in ("cnpj", "chave_acesso", "valor_bruto", "desconto", "forma_pagamento", "numero_nf", "serie_nf", "emissao"):
            validada[chave] = nota.get(chave)
        registro = {k: v for k, v in nota.items()}
        duvidas = []
        if not nota.get("data_compra"):
            duvidas.append(f"A data da compra não veio na nota: vai como hoje ({date.today():%d/%m/%Y}). Se for outra, "
                           "responda \"não\" e mande de novo com a linha \"Emissão: dd/mm/aaaa\".")
        if validada.get("estabelecimento") in (None, "", "Não informado"):
            duvidas.append("A loja não veio no texto colado.")
        return {"compras": [validada], "duvidas": duvidas,
                "origem": {"resposta_json": json.dumps(registro, ensure_ascii=False)[:20000],
                           "modelo": modelo, "versao_prompt": "nfce-v1", "chave_documento": nota.get("chave_acesso")}}

    def _nomes_legiveis(self, itens) -> Optional[str]:
        """O modelo local reescreve os nomes do cupom e escolhe a categoria; sem ele, fica o nome do cupom."""
        for item in itens:
            item["nome_cupom"] = item["produto"]
            item["categoria"] = inferir_categoria(item["produto"], "outros")
        if self.llm_nomes is None:
            return None
        # Nome cortado pela Sefaz ("C...") não vai ao modelo: ele inventaria um produto
        pedido = json.dumps([{"codigo": i.get("codigo") or str(n), "nome": i["produto"]} for n, i in enumerate(itens)
                             if not i.get("nome_cortado")], ensure_ascii=False)
        try:
            prompt = obter_catalogo().skill("compras").prompt("nomes_nota")
            resposta = self.llm_nomes.gerar_json(prompt_sistema=prompt, mensagem_usuario=pedido, esquema=ESQUEMA_NOMES)
        except Exception as erro:  # Ollama fechado ou resposta ruim: ficam os nomes do cupom
            custom_logger.evento(COMPONENTE, "nomes_sem_modelo", type(erro).__name__, nivel="WARNING")
            for item in itens:
                item["produto"] = item["produto"].lower()
            return None
        por_codigo = {str(r.get("codigo")): r for r in (resposta or {}).get("itens", []) if isinstance(r, dict)}
        for n, item in enumerate(itens):
            novo = None if item.get("nome_cortado") else por_codigo.get(item.get("codigo") or str(n))
            if novo and str(novo.get("produto") or "").strip():
                item["produto"] = str(novo["produto"]).strip().lower()
                item["categoria"] = inferir_categoria(item["produto"], novo.get("categoria"))
            else:
                item["produto"] = item["produto"].lower()
        return getattr(self.llm_nomes, "modelo", None)

    def _importar_pdf(self, caminho: Path, canal: str) -> Dict:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise DocumentoError("Para ler PDF falta a biblioteca pypdf: rode \"pip install pypdf\" no PC.") from None
        try:
            texto = "\n".join((pagina.extract_text() or "") for pagina in PdfReader(str(caminho)).pages).strip()
        except Exception as erro:  # PDF corrompido, protegido por senha etc.
            raise DocumentoError(f"Não consegui ler o PDF ({type(erro).__name__}).") from None
        if len(texto) < 20:
            # PDF sem texto (página salva como imagem): lê a maior imagem de cada página
            return self._importar_imagem(*self._imagens_do_pdf(caminho))
        if nfce_service.eh_nfce(texto):
            return self._importar_nfce(caminho)
        preparada = self.compras.preparar_compra(texto[:8000], canal)
        preparada.setdefault("duvidas", []).append("Lido de um PDF: confira os itens e valores.")
        return preparada

    def _imagens_do_pdf(self, caminho: Path) -> List[Path]:
        from pypdf import PdfReader
        destino = self.pasta_anexos / "_paginas"
        destino.mkdir(parents=True, exist_ok=True)
        arquivos = []
        try:
            for n, pagina in enumerate(PdfReader(str(caminho)).pages[:3], start=1):
                imagens = sorted(pagina.images, key=lambda im: len(im.data), reverse=True)
                if not imagens:
                    continue
                maior = imagens[0]
                extensao = Path(maior.name).suffix.lower() or ".png"
                saida = destino / f"{caminho.stem}-p{n}{extensao}"
                saida.write_bytes(maior.data)
                arquivos.append(saida)
        except Exception as erro:
            raise DocumentoError(f"Não consegui tirar a imagem do PDF ({type(erro).__name__}).") from None
        if not arquivos:
            raise DocumentoError("O PDF não tem texto nem imagem que eu consiga ler.")
        return arquivos

    def _importar_imagem(self, *anexos: Path) -> Dict:
        """M34: o modelo de imagem só transcreve; a compra sai da transcrição (leitor exato da NFC-e/NF-e ou o
        modelo de texto, melhor com estrutura). Sem transcrição útil, cai na leitura direta em JSON."""
        if self.llm_visao is None:
            raise DocumentoError("Nenhum modelo para ler imagens está configurado (OLLAMA_MODELO_VISAO).")
        transcricao = self._transcrever([parte for anexo in anexos for parte in imagem_service.preparar(anexo)])
        transcricao = nfce_service.ocultar_consumidor(transcricao)
        # Chave de acesso lida certa (dígito verificador confere) evita registrar a mesma nota duas vezes
        chave = nfce_service.chave_no_texto(transcricao)
        if chave and self.db.documento_ja_gravado(chave):
            raise DocumentoError("Essa nota já foi registrada (mesma chave de acesso, lida na foto).")
        preparada = self._compra_da_transcricao(transcricao) if transcricao else None
        if not preparada or not preparada.get("compras"):
            preparada = self._leitura_direta(anexos)
        compra = preparada["compras"][0]
        # Número, série e emissão lidos na transcrição; a emissão é a data da compra. Sem emissão, vale a primeira
        # data da transcrição (o modelo de texto às vezes troca a data lida pela de hoje)
        ident = nfce_service.identificacao(transcricao)
        for campo in ("numero_nf", "serie_nf", "emissao"):
            if ident.get(campo) and not compra.get(campo):
                compra[campo] = ident[campo]
        datas = datas_da_transcricao(transcricao)
        if ident.get("data_compra"):
            compra["data_compra"] = ident["data_compra"]
        elif datas and compra.get("data_compra") not in datas:
            compra["data_compra"] = datas[0]
        aplicar_desconto_lido(compra, transcricao)
        conferir = ["loja"] if compra.get("estabelecimento") not in (None, "", "Não informado") else []
        if data_suspeita(compra.get("data_compra"), self._agora().date()):
            conferir.append("data")
        compra["_conferir"] = conferir
        preparada.setdefault("duvidas", []).insert(0, "Lido de uma foto: confira cada item e valor antes de gravar.")
        origem = preparada.setdefault("origem", {})
        origem["modelo"] = f"{getattr(self.llm_visao, 'modelo', None)} + {origem.get('modelo') or 'leitor'}"
        origem["texto"] = ("Transcrição da foto:\n" + transcricao[:18000]) if transcricao else origem.get("texto")
        if chave:
            origem["chave_documento"] = chave
            compra["chave_acesso"] = chave
        return preparada

    def _transcrever(self, partes: List[bytes]) -> str:
        prompt = ("Você transcreve cupons e notas fiscais. Copie fielmente todo o texto desta imagem, linha por linha, "
                  "como está escrito, mantendo números, vírgulas e datas. Não resuma, não traduza e não invente: "
                  "o que estiver ilegível vira [ilegível].")
        textos = []
        for n, parte in enumerate(partes, start=1):
            try:
                texto = self.llm_visao.gerar_texto_imagem(prompt, f"Transcreva o texto (parte {n} de {len(partes)}).", [parte])
            except AttributeError:   # provedor sem transcrição: só a leitura direta
                return ""
            except Exception as erro:
                raise DocumentoError(f"Não consegui ler a foto ({type(erro).__name__}). Confira se o Ollama está aberto "
                                     "e se o modelo de imagem está instalado.") from None
            textos.append(limpar_transcricao(texto))
        return "\n".join(t for t in textos if t).strip()

    def _compra_da_transcricao(self, texto: str) -> Optional[Dict]:
        for parece, ler in ((nfce_service.parece_nfce_texto, nfce_service.ler_nfce_texto),
                            (nfce_service.parece_nfe_texto, nfce_service.ler_nfe_texto)):
            if parece(texto):
                try:
                    preparada = self._preparar_nota(ler(texto))
                    preparada["origem"]["versao_prompt"] = "foto-transcricao-nota-v1"
                    return preparada
                except (nfce_service.NotaInvalidaError, DocumentoError):
                    pass
        try:
            preparada = self.compras.preparar_compra(texto[:8000], "chat")
        except Exception as erro:
            custom_logger.evento(COMPONENTE, "transcricao_sem_extracao", erro=type(erro).__name__, nivel="WARNING")
            return None
        if preparada.get("compras"):
            preparada.setdefault("origem", {})["versao_prompt"] = "foto-transcricao-v1"
        return preparada

    def _leitura_direta(self, anexos) -> Dict:
        prompt = obter_catalogo().skill("compras").prompt("foto_cupom", data_atual=date.today().isoformat())
        try:
            resposta = self.llm_visao.gerar_json_imagem(prompt, "Leia este cupom de compra.", [str(a) for a in anexos], ESQUEMA_COMPRAS)
        except Exception as erro:
            raise DocumentoError(f"Não consegui ler a foto ({type(erro).__name__}). Confira se o Ollama está aberto "
                                 "e se o modelo de imagem está instalado.") from None
        compras = []
        for dados in (resposta or {}).get("compras", []):
            validada = self.compras._validar_e_sanitizar_compra(dados)
            if validada.get("itens"):
                validada["data_compra"] = dados.get("data_compra") or date.today().isoformat()
                compras.append(validada)
        if not compras:
            # Guarda o que o modelo devolveu para diagnosticar (só itens e valores; o prompt manda ignorar CPF)
            custom_logger.evento(COMPONENTE, "imagem_sem_itens", modelo=getattr(self.llm_visao, "modelo", None),
                                 resposta=json.dumps(resposta, ensure_ascii=False)[:2000])
            raise DocumentoError("o modelo de imagem não reconheceu itens. Para nota aberta no site da Sefaz, "
                                 "salve a página (Ctrl+S) e mande o arquivo HTML: a leitura é exata.")
        return {"compras": compras[:1], "duvidas": [],
                "origem": {"resposta_json": json.dumps(resposta, ensure_ascii=False)[:20000],
                           "modelo": None, "versao_prompt": "foto-v1"}}
