"""
M23: dispositivos autorizados a usar a API do assistente.

Cada dispositivo (PC, celular, painel) tem um token próprio, revogável. Só o hash SHA-256 do token fica
gravado; o token aparece uma única vez, ao ser criado. Escopos:
- "local": o próprio PC (Electron). Pode importar arquivo pelo caminho, ligar a voz e desligar o servidor.
- "remoto": celular e navegador. Conversa, envia foto/arquivo e vê o painel; não toca em arquivos do PC.
"""
import hashlib
import hmac
import json
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

ESCOPOS = ("local", "remoto")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Dispositivos:
    def __init__(self, arquivo: Path, agora=datetime.now):
        self.arquivo = Path(arquivo)
        self._agora = agora
        self._lock = threading.Lock()
        self._lista: List[Dict] = self._ler()

    def _ler(self) -> List[Dict]:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            return dados if isinstance(dados, list) else []
        except (OSError, ValueError):
            return []

    def _gravar(self) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(self._lista, ensure_ascii=False, indent=1), encoding="utf-8")
        temporario.replace(self.arquivo)

    def criar(self, nome: str, escopo: str = "remoto") -> str:
        if escopo not in ESCOPOS:
            raise ValueError(f"Escopo inválido: {escopo}")
        token = secrets.token_urlsafe(32)
        with self._lock:
            ident = secrets.token_hex(3)
            self._lista.append({"id": ident, "nome": " ".join(str(nome).split())[:60] or "dispositivo", "escopo": escopo,
                                "hash": _hash(token), "criado_em": self._agora().isoformat(timespec="seconds"),
                                "ultimo_uso": None, "revogado": False})
            self._gravar()
        return token

    def validar(self, token: Optional[str]) -> Optional[Dict]:
        if not token:
            return None
        procurado = _hash(token)
        with self._lock:
            for item in self._lista:
                if not item.get("revogado") and hmac.compare_digest(item["hash"], procurado):
                    agora = self._agora().isoformat(timespec="minutes")
                    if item.get("ultimo_uso") != agora:   # grava no máximo uma vez por minuto
                        item["ultimo_uso"] = agora
                        self._gravar()
                    return {k: v for k, v in item.items() if k != "hash"}
        return None

    def revogar(self, ident_ou_nome: str) -> int:
        with self._lock:
            n = 0
            for item in self._lista:
                if not item.get("revogado") and ident_ou_nome in (item["id"], item["nome"]):
                    item["revogado"] = True
                    n += 1
            if n:
                self._gravar()
        return n

    def listar(self) -> List[Dict]:
        with self._lock:
            return [{k: v for k, v in item.items() if k != "hash"} for item in self._lista]

    def token_local(self, arquivo_token: Path) -> str:
        """Token do Electron deste PC, guardado num arquivo que só o PC lê. Recria se sumiu ou foi revogado."""
        arquivo_token = Path(arquivo_token)
        try:
            token = arquivo_token.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        atual = self.validar(token)
        if atual and atual.get("escopo") == "local":
            return token
        token = self.criar("PC (Electron)", "local")
        arquivo_token.parent.mkdir(parents=True, exist_ok=True)
        arquivo_token.write_text(token, encoding="utf-8")
        return token
