"""
Bot do Telegram para mandar ideias do celular (opcional).

- Busca mensagens com long polling (getUpdates): o PC não fica exposto na internet.
- Só os chats em TELEGRAM_CHAT_IDS são atendidos; os outros são ignorados e registrados só pelo número
  (para descobrir o seu, use scripts/configurar_telegram.py).
- O Telegram guarda mensagens não buscadas por até 24 h: o que você mandar com o PC desligado é
  recebido quando o assistente abrir, dentro desse prazo.
- O token nunca vai para os logs (as exceções do requests trazem a URL, que contém o token).

As mensagens passam pelos servidores do Telegram (bots não têm criptografia de ponta a ponta).
Referência: https://core.telegram.org/bots/api
"""
import json
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import requests

from services.logger_service import logger as custom_logger

COMPONENTE = "telegram"
URL = "https://api.telegram.org/bot{token}/{metodo}"
URL_ARQUIVO = "https://api.telegram.org/file/bot{token}/{caminho}"
LIMITE_MENSAGEM = 4000


class TelegramErro(Exception):
    pass


def dividir_mensagem(texto: str, limite: int = LIMITE_MENSAGEM) -> List[str]:
    partes, atual = [], ""
    for linha in (texto or "").splitlines(keepends=True):
        while len(linha) > limite:
            if atual:
                partes.append(atual)
                atual = ""
            partes.append(linha[:limite])
            linha = linha[limite:]
        if len(atual) + len(linha) > limite:
            partes.append(atual)
            atual = ""
        atual += linha
    if atual.strip():
        partes.append(atual)
    return partes or [""]


class TelegramService:
    def __init__(self, token: str, chats_permitidos: Iterable[int], arquivo_offset: Path,
                 ao_receber: Optional[Callable[[int, str], Optional[str]]] = None,
                 ao_receber_arquivo: Optional[Callable[[int, Dict], Optional[str]]] = None,
                 get: Callable = requests.get, post: Callable = requests.post, espera_s: int = 30):
        self._token = token or ""
        self.chats_permitidos = set(chats_permitidos)
        self.arquivo_offset = Path(arquivo_offset)
        self.ao_receber = ao_receber
        self.ao_receber_arquivo = ao_receber_arquivo
        self._get = get
        self._post = post
        self.espera_s = espera_s

    def configurado(self) -> bool:
        return bool(self._token and self.chats_permitidos)

    def _chamar(self, metodo: str, http: Callable, **kwargs):
        try:
            resposta = http(URL.format(token=self._token, metodo=metodo), timeout=self.espera_s + 15, **kwargs)
            dados = resposta.json()
        except (requests.RequestException, ValueError) as erro:
            raise TelegramErro(f"falha ao falar com o Telegram ({type(erro).__name__})") from None
        if not dados.get("ok"):
            raise TelegramErro(f"Telegram recusou {metodo}: {dados.get('error_code')} {str(dados.get('description', ''))[:120]}")
        return dados.get("result")

    def enviar(self, chat_id: int, texto: str) -> None:
        for parte in dividir_mensagem(texto):
            self._chamar("sendMessage", self._post, json={"chat_id": chat_id, "text": parte})

    def baixar(self, file_id: str, destino: Path) -> Path:
        """Baixa um arquivo mandado ao bot (getFile + download). O token não vai para os logs."""
        info = self._chamar("getFile", self._get, params={"file_id": file_id})
        caminho = (info or {}).get("file_path")
        if not caminho:
            raise TelegramErro("o Telegram não informou o arquivo")
        try:
            resposta = self._get(URL_ARQUIVO.format(token=self._token, caminho=caminho), timeout=120)
            conteudo = resposta.content
        except requests.RequestException as erro:
            raise TelegramErro(f"falha ao baixar o arquivo ({type(erro).__name__})") from None
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(destino.name + ".parcial")
        temporario.write_bytes(conteudo)
        temporario.replace(destino)  # só aparece com o nome final quando o download terminou
        return destino

    def _ler_offset(self) -> int:
        try:
            return int(json.loads(self.arquivo_offset.read_text(encoding="utf-8")).get("offset", 0))
        except (OSError, ValueError, AttributeError):
            return 0

    def _gravar_offset(self, offset: int) -> None:
        self.arquivo_offset.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo_offset.write_text(json.dumps({"offset": offset}), encoding="utf-8")

    def buscar_atualizacoes(self, espera_s: Optional[int] = None) -> List[Dict]:
        return self._chamar("getUpdates", self._get, params={
            "offset": self._ler_offset(), "timeout": self.espera_s if espera_s is None else espera_s,
            "allowed_updates": json.dumps(["message"]),
        }) or []

    def processar_uma_vez(self) -> int:
        atendidas = 0
        for atualizacao in self.buscar_atualizacoes():
            self._gravar_offset(int(atualizacao["update_id"]) + 1)  # antes de responder: nunca processa duas vezes
            mensagem = atualizacao.get("message") or {}
            chat_id = (mensagem.get("chat") or {}).get("id")
            if chat_id not in self.chats_permitidos:
                custom_logger.evento(COMPONENTE, "chat_recusado", nivel="WARNING", chat_id=chat_id)
                continue
            texto = mensagem.get("text")
            if not texto and (mensagem.get("document") or mensagem.get("photo")) and self.ao_receber_arquivo:
                try:
                    resposta = self.ao_receber_arquivo(chat_id, mensagem)
                except Exception as erro:
                    custom_logger.evento(COMPONENTE, "falha_arquivo", type(erro).__name__, nivel="ERROR")
                    resposta = "Não consegui baixar o arquivo. Tente de novo em instantes."
                if resposta:
                    self.enviar(chat_id, resposta)
                atendidas += 1
                continue
            if not texto:
                self.enviar(chat_id, "Por enquanto eu só entendo texto. Escreva a ideia, por favor.")
                continue
            try:
                resposta = self.ao_receber(chat_id, texto) if self.ao_receber else None
            except Exception as erro:
                custom_logger.evento(COMPONENTE, "falha_ao_processar", type(erro).__name__, nivel="ERROR")
                resposta = "Não consegui salvar agora. Tente de novo em instantes."
            if resposta:
                self.enviar(chat_id, resposta)
            atendidas += 1
        return atendidas

    def iniciar_em_segundo_plano(self, deve_parar: Callable[[], bool], dormir: Callable[[float], None] = time.sleep):
        def laco():
            espera = 5
            while not deve_parar():
                try:
                    self.processar_uma_vez()
                    espera = 5
                except TelegramErro as erro:
                    custom_logger.evento(COMPONENTE, "falha", str(erro), nivel="WARNING")
                    dormir(espera)
                    espera = min(espera * 2, 300)

        linha = threading.Thread(target=laco, name="telegram", daemon=True)
        linha.start()
        custom_logger.evento(COMPONENTE, "iniciado", chats=len(self.chats_permitidos))
        return linha
