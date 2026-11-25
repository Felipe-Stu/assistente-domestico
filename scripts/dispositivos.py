"""
Dispositivos que podem usar a API do assistente (V5.5).

    python scripts/dispositivos.py novo "Celular do Felipe"     cria o token e mostra o link para abrir no celular
    python scripts/dispositivos.py listar
    python scripts/dispositivos.py revogar <id ou nome>

O token aparece uma única vez. Quem tiver o link entra no assistente: abra-o só no seu celular e revogue se perder o aparelho.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core import config  # noqa: E402
from services.dispositivos_service import Dispositivos  # noqa: E402


def endereco_tailscale():
    """Nome HTTPS do PC na rede do Tailscale (se o Tailscale estiver instalado e logado)."""
    if not shutil.which("tailscale"):
        return None
    try:
        saida = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10).stdout
        nome = (json.loads(saida).get("Self") or {}).get("DNSName", "").rstrip(".")
        return f"https://{nome}" if nome else None
    except Exception:
        return None


def main(argv) -> int:
    dispositivos = Dispositivos(config.DISPOSITIVOS_ARQUIVO)
    if len(argv) >= 2 and argv[0] == "novo":
        nome = " ".join(argv[1:]).replace("--local", "").strip()
        token = dispositivos.criar(nome, "local" if "--local" in argv else "remoto")
        base = endereco_tailscale()
        print(f"Dispositivo criado: {nome}")
        if base:
            print(f"\nAbra este link no celular (uma vez; depois instale a página na tela inicial):\n  {base}/entrar?token={token}")
        else:
            print("\nTailscale não encontrado. Na rede de casa, troque <IP-do-PC> pelo IP deste computador:")
            print(f"  http://<IP-do-PC>:{config.API_PORTA}/entrar?token={token}")
            print("  (com API_HOST=0.0.0.0 no .env; fora de casa use o Tailscale, veja Sobre a Versão/08)")
        print("\nGuarde o link só no seu aparelho. Para cortar o acesso: scripts/dispositivos.py revogar", repr(nome))
        return 0
    if argv and argv[0] == "listar":
        for item in dispositivos.listar():
            estado = "REVOGADO" if item["revogado"] else "ativo"
            print(f"{item['id']}  {item['nome']:<28} {item['escopo']:<7} {estado:<9} criado {item['criado_em']}  último uso {item['ultimo_uso'] or '-'}")
        return 0
    if len(argv) >= 2 and argv[0] == "revogar":
        n = dispositivos.revogar(" ".join(argv[1:]))
        print(f"{n} dispositivo(s) revogado(s).")
        return 0 if n else 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
