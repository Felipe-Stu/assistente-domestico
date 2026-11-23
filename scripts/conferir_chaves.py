"""
Confere de onde vem a chave do Gemini (M01), sem mostrar nenhuma chave.

    python scripts/conferir_chaves.py

Mostra se existe GEMINI_API_KEY nas variáveis do Windows (que têm prioridade sobre o .env),
se o .env tem a chave e se a chave que o app carrega é a do .env.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOME = "GEMINI_API_KEY"


def ler_env(caminho: Path) -> dict:
    valores = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                chave, valor = linha.split("=", 1)
                valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def variavel_windows(escopo: str):
    """Valor no registro do Windows (usuário ou sistema), ou None."""
    try:
        import winreg
    except ImportError:
        return None
    locais = {
        "usuário": (winreg.HKEY_CURRENT_USER, r"Environment"),
        "sistema": (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    }
    raiz, caminho = locais[escopo]
    try:
        with winreg.OpenKey(raiz, caminho) as chave:
            return winreg.QueryValueEx(chave, NOME)[0]
    except OSError:
        return None


def main():
    do_env = ler_env(ROOT / ".env").get(NOME, "")
    no_processo = os.environ.get(NOME, "")
    ok = True
    print("Conferência das chaves (M01) — nenhuma chave é exibida")
    print(f"- .env: {'chave preenchida' if do_env else 'SEM CHAVE'}")
    for escopo in ("usuário", "sistema"):
        if os.name != "nt":
            print(f"- Variável do Windows ({escopo}): não verificada (fora do Windows)")
            continue
        valor = variavel_windows(escopo)
        if valor is None:
            print(f"- Variável do Windows ({escopo}): não existe [ok]")
        else:
            ok = False
            print(f"- Variável do Windows ({escopo}): EXISTE{' (igual ao .env)' if valor == do_env else ' (DIFERENTE do .env: provavelmente a chave antiga)'} — exclua")
    if no_processo and no_processo != do_env:
        ok = False
        print("- Este terminal ainda tem uma chave diferente da do .env: feche e abra o terminal de novo")

    sys.path.insert(0, str(ROOT))
    from core.config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        ok = False
        print("- Chave carregada pelo app: NENHUMA")
    elif GEMINI_API_KEY == do_env:
        print("- Chave carregada pelo app: a do .env [ok]")
    else:
        ok = False
        print("- Chave carregada pelo app: DIFERENTE da do .env")
    print("Resultado: OK, o M01 pode ser fechado" if ok else "Resultado: PENDENTE, veja os itens acima")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
