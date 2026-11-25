"""Desliga o servidor do assistente (o mesmo que o botão ⏻ da janela). Usa o token local deste PC."""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core import config  # noqa: E402


def main() -> int:
    try:
        token = config.TOKEN_LOCAL_ARQUIVO.read_text(encoding="utf-8").strip()
    except OSError:
        print("Token local não encontrado: o servidor nunca foi aberto neste PC.")
        return 1
    pedido = urllib.request.Request(
        f"http://127.0.0.1:{config.API_PORTA}/api/comandos", method="POST",
        data=json.dumps({"type": "shutdown"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(pedido, timeout=5) as resposta:
            print("Assistente desligado." if resposta.status == 202 else f"Resposta inesperada: {resposta.status}")
            return 0
    except urllib.error.URLError:
        print("O assistente já estava desligado.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
