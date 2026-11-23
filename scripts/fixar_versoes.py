"""
Gera requirements-lock.txt com as versões EXATAS instaladas das dependências de requirements.txt (M27).

O requirements.txt continua com as versões mínimas (o que o código exige); o lock registra o
ambiente que funciona no PC, para reinstalar igual: pip install -r requirements-lock.txt
Rode com o Python do assistente: python scripts/fixar_versoes.py
"""
import re
import sys
from datetime import date
from importlib import metadata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_RE_NOME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def dependencias(arquivo: Path):
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.split("#", 1)[0].strip()
        encontrado = _RE_NOME.match(linha)
        if encontrado:
            yield encontrado.group(1)


def gerar(origem: Path, destino: Path, versao=metadata.version) -> list:
    fixadas, faltando = [], []
    for nome in dependencias(origem):
        try:
            fixadas.append(f"{nome}=={versao(nome)}")
        except metadata.PackageNotFoundError:
            faltando.append(nome)
    cabecalho = (f"# Versões exatas instaladas em {date.today():%d/%m/%Y} (Python {sys.version.split()[0]}).\n"
                 "# Gerado por scripts/fixar_versoes.py a partir de requirements.txt. Não edite à mão.\n")
    destino.write_text(cabecalho + "\n".join(fixadas) + "\n", encoding="utf-8")
    return faltando


def main() -> int:
    faltando = gerar(RAIZ / "requirements.txt", RAIZ / "requirements-lock.txt")
    print((RAIZ / "requirements-lock.txt").read_text(encoding="utf-8"))
    if faltando:
        print("Não instalados neste Python (ficaram de fora):", ", ".join(faltando))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
