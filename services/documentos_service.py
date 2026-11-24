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
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from core.skills import obter_catalogo
from services import nfce_service
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
        preparada["origem"].update({"tipo": "nota", "canal": canal, "texto": texto[:20000],
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
        for chave in ("cnpj", "chave_acesso", "valor_bruto", "desconto", "forma_pagamento"):
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
        if self.llm_visao is None:
            raise DocumentoError("Nenhum modelo para ler imagens está configurado (OLLAMA_MODELO_VISAO).")
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
        return {"compras": compras[:1], "duvidas": ["Lido de uma foto: confira cada item e valor antes de gravar."],
                "origem": {"resposta_json": json.dumps(resposta, ensure_ascii=False)[:20000],
                           "modelo": getattr(self.llm_visao, "modelo", None), "versao_prompt": "foto-v1"}}
