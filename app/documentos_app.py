"""
Importação de notas fiscais pelo núcleo (M25): pasta de entrada, anexo do app ou do celular e arquivo do Telegram.
A nota vira compra aguardando "sim" ou "não"; as perguntas de conferência vêm de services/perguntas_compra.py.
"""
import logging
import threading
from pathlib import Path

import core.config as config_app
from services import perguntas_compra
from services.documentos_service import DocumentoError
from services.logger_service import logger as custom_logger
from services.pasta_entradas_service import PastaEntradas

logger = logging.getLogger(__name__)

# Canais em que a pessoa está olhando a tela agora (mostra "processando" e avisa quando a nota fica na fila)
CANAIS_INTERATIVOS = {"app", "celular"}


class ImportacaoDeDocumentos:
    def _iniciar_pasta_entradas(self):
        if self.documentos is None:
            return
        self.pasta_entradas = PastaEntradas(
            config_app.ENTRADAS_DIR,
            ao_encontrar=lambda caminho, canal: self.fila.put({"type": "documento", "payload": {"caminho": str(caminho), "canal": canal}}),
            intervalo_s=config_app.ENTRADAS_INTERVALO_S,
        )
        self.pasta_entradas.iniciar_em_segundo_plano(deve_parar=lambda: self.deve_encerrar)
        self._emitir("debug_log", {"message": f"✓ Pasta de notas fiscais vigiada: {config_app.ENTRADAS_DIR}"})

    def _importar_documento(self, caminho: str, canal: str = "pasta", aguardando: bool = False):
        """Nota fiscal encontrada na pasta de entrada: vira compra aguardando "sim" ou "não"."""
        arquivo = Path(caminho)
        if self.pendencia is not None:
            # Já há uma confirmação esperando: a nota volta para a fila daqui a pouco
            if canal in CANAIS_INTERATIVOS and not aguardando:
                self._emitir("assistant_message", {"text": f"Recebi {arquivo.name}. Mostro o resumo depois que você responder a confirmação atual (sim ou não)."})
            threading.Timer(10, lambda: self.fila.put({"type": "documento", "payload": {"caminho": caminho, "canal": canal, "aguardando": True}})).start()
            return None
        if canal in CANAIS_INTERATIVOS:
            self._set_estado("PROCESSING")
        chat = self._chat_do_arquivo(arquivo)
        ok = False
        try:
            with custom_logger.requisicao(canal=canal, caracteres=0):
                preparada = self.documentos.importar(arquivo, canal)
            aberta = perguntas_compra.abrir(f"📄 Nota fiscal recebida ({arquivo.name}):",
                                            self.documentos.resumo(preparada, com_duvidas=False),
                                            preparada["compras"], preparada["origem"], preparada.get("duvidas"))
            self.pendencia = ("compras", aberta["pendencia"])
            texto = aberta["texto"]
            ok = True
        except DocumentoError as erro:
            texto = f"Não consegui importar {arquivo.name}: {erro}"
        except Exception as erro:
            logger.error(f"Falha ao importar documento: {erro}")
            texto = f"Não consegui importar {arquivo.name} ({type(erro).__name__})."
        finally:
            # Só arquivos da pasta de entrada são movidos; o anexo do app fica onde o usuário o guardou
            if self.pasta_entradas is not None and arquivo.exists() and self._na_pasta_entradas(arquivo):
                self.pasta_entradas.mover(arquivo, ok)
            # Enviado pelo celular: o original já foi copiado para Anexos/; o temporário sai (fica só se deu erro)
            if ok and self._em_recebidos(arquivo):
                try:
                    arquivo.unlink()
                except OSError as erro:
                    logger.warning(f"Não consegui apagar o temporário {arquivo.name}: {erro}")
            if canal in CANAIS_INTERATIVOS:
                self._set_estado("WAITING_INPUT")
        self._emitir("assistant_message", {"text": texto})
        if chat is not None and self.telegram is not None:
            aviso = texto.replace(perguntas_compra.PEDIR_CONFIRMACAO, "Confirme no assistente do PC (sim ou não).")
            if self.pendencia and self.pendencia[1].get("perguntas"):
                aviso += "\n\nResponda a pergunta no assistente do PC."
            self.telegram.enviar(chat, aviso)
        return texto

    @staticmethod
    def _na_pasta_entradas(arquivo: Path) -> bool:
        try:
            return Path(arquivo).resolve().parent == Path(config_app.ENTRADAS_DIR).resolve()
        except OSError:
            return False

    @staticmethod
    def _em_recebidos(arquivo: Path) -> bool:
        try:
            return Path(arquivo).resolve().parent == Path(config_app.RECEBIDOS_DIR).resolve()
        except OSError:
            return False

    @staticmethod
    def _chat_do_arquivo(arquivo: Path):
        partes = arquivo.name.split("_", 2)
        return int(partes[1]) if len(partes) == 3 and partes[0] == "telegram" and partes[1].lstrip("-").isdigit() else None

    def _receber_arquivo_telegram(self, chat: int, mensagem: dict) -> str:
        """Arquivo ou foto mandado ao bot: vai para a pasta de entrada e é importado no PC."""
        documento = mensagem.get("document") or (mensagem.get("photo") or [None])[-1]
        if not documento:
            return "Por enquanto eu entendo texto, arquivos (HTML da nota, PDF) e fotos."
        if (documento.get("file_size") or 0) > 20 * 1024 * 1024:
            return "Arquivo grande demais: o Telegram só deixa o bot baixar até 20 MB."
        nome = documento.get("file_name") or f"foto_{mensagem.get('message_id', 'cupom')}.jpg"
        nome = "".join(c if c.isalnum() or c in "._-" else "_" for c in nome)[-80:]
        destino = config_app.ENTRADAS_DIR / f"telegram_{chat}_{nome}"
        self.telegram.baixar(documento["file_id"], destino)
        return "Recebi o arquivo. O resumo da compra vai aparecer aqui e no assistente do PC para você confirmar."
