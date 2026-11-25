"""
Barramento de eventos do núcleo (M25/M23).

O runtime publica cada evento uma vez (estado, mensagens, logs, voz); quem quiser ouve:
- o modo antigo imprime em JSON na saída padrão (ponte stdin do Electron);
- o servidor repassa a cada cliente conectado (Electron, celular, painel) por eventos do servidor (SSE).
Os últimos eventos de conversa ficam guardados para quem conecta depois ver o histórico recente.
"""
import asyncio
import itertools
import secrets
import threading
from collections import deque
from typing import Callable, Deque, Dict, List, Optional

TIPOS_DE_CONVERSA = {"user_message", "assistant_message", "error"}
LIMITE_HISTORICO = 60


class Barramento:
    def __init__(self, limite_historico: int = LIMITE_HISTORICO):
        self._lock = threading.Lock()
        self._ouvintes: Dict[int, Callable[[Dict], None]] = {}
        self._ids = itertools.count(1)
        self._historico: Deque[Dict] = deque(maxlen=limite_historico)
        self._seq = itertools.count(1)
        self.ultimo_estado: Optional[str] = None
        # Muda a cada início do servidor: o cliente que já estava conectado zera o contador de eventos vistos
        self.instancia = secrets.token_hex(4)

    def publicar(self, tipo: str, payload=None) -> Dict:
        evento = {"id": next(self._seq), "type": tipo, "payload": payload}
        with self._lock:
            if tipo == "state_changed" and isinstance(payload, dict):
                self.ultimo_estado = payload.get("state")
            if tipo in TIPOS_DE_CONVERSA:
                self._historico.append(evento)
            ouvintes = list(self._ouvintes.values())
        for ouvinte in ouvintes:
            try:
                ouvinte(evento)
            except Exception:   # um cliente com problema não derruba os outros
                pass
        return evento

    def assinar(self, ouvinte: Callable[[Dict], None]) -> int:
        with self._lock:
            ident = next(self._ids)
            self._ouvintes[ident] = ouvinte
        return ident

    def cancelar(self, ident: int) -> None:
        with self._lock:
            self._ouvintes.pop(ident, None)

    def assinar_async(self, loop: asyncio.AbstractEventLoop, tamanho: int = 500):
        """Fila asyncio alimentada a partir de qualquer thread (para o servidor). Devolve (ident, fila)."""
        fila: asyncio.Queue = asyncio.Queue(maxsize=tamanho)

        def entregar(evento):
            def colocar():
                if fila.full():   # cliente lento: descarta o mais antigo
                    fila.get_nowait()
                fila.put_nowait(evento)
            loop.call_soon_threadsafe(colocar)

        return self.assinar(entregar), fila

    def historico(self) -> List[Dict]:
        with self._lock:
            return list(self._historico)


barramento = Barramento()
