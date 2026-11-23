"""
Valida todas as skills (SK6). Roda na integração contínua e localmente.

    python scripts/validar_skills.py

Confere: cabeçalhos (via catálogo), roteiros importáveis com executar(), prompts com marcadores
fechados e exemplos.jsonl com frase e ação válidas. Não chama nenhum modelo.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ACOES = {"criar", "corrigir", "consultar", "delegar"}


def validar(pasta: Path = None) -> list:
    from core.skills import carregar_catalogo, motor
    from core.skills.catalogo import PASTA_SKILLS
    pasta = Path(pasta or PASTA_SKILLS)
    erros = []
    try:
        catalogo = carregar_catalogo(pasta)
    except Exception as erro:
        return [str(erro)]
    for skill in catalogo:
        if skill.execucao == "roteiro":
            try:
                motor.carregar_roteiro(skill)
            except Exception as erro:
                erros.append(f"{skill.nome}/roteiro.py: {type(erro).__name__}: {erro}")
        for prompt in sorted((skill.pasta / "prompts").glob("*.md")):
            texto = prompt.read_text(encoding="utf-8")
            if texto.count("{{") != texto.count("}}"):
                erros.append(f"{skill.nome}/prompts/{prompt.name}: marcador {{{{ }}}} sem fechar")
        exemplos = skill.pasta / "exemplos.jsonl"
        if exemplos.exists():
            for numero, linha in enumerate(exemplos.read_text(encoding="utf-8").splitlines(), 1):
                if not linha.strip():
                    continue
                try:
                    caso = json.loads(linha)
                except ValueError:
                    erros.append(f"{skill.nome}/exemplos.jsonl:{numero}: JSON inválido")
                    continue
                if not str(caso.get("frase", "")).strip():
                    erros.append(f"{skill.nome}/exemplos.jsonl:{numero}: falta 'frase'")
                if caso.get("acao") not in ACOES:
                    erros.append(f"{skill.nome}/exemplos.jsonl:{numero}: 'acao' deve ser uma de {sorted(ACOES)}")
    return erros


def main():
    erros = validar()
    if erros:
        print("Skills com problema:")
        for erro in erros:
            print(f"- {erro}")
        return 1
    from core.skills import obter_catalogo
    print(f"OK: {len(obter_catalogo())} skills válidas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
