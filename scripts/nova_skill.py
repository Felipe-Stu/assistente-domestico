"""
Cria uma skill nova a partir do modelo em skills/_modelo (SK6).

    python scripts/nova_skill.py musica --descricao "Toca músicas e playlists no Spotify. Use quando a pessoa pede para tocar, pausar ou trocar a música."
    python scripts/nova_skill.py lembretes --descricao "..." --privacidade local --contexto lembretes

Depois: edite skills/<nome>/SKILL.md e roteiro.py, preencha exemplos.jsonl e rode
    python scripts/validar_skills.py
    python scripts/avaliar.py --skill <nome> --so-roteamento --modelos gemma4:e4b
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.skills.catalogo import PASTA_SKILLS, PRIVACIDADES, carregar_catalogo  # noqa: E402

PASTA_MODELO = PASTA_SKILLS / "_modelo"
_RE_NOME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def criar_skill(nome: str, descricao: str, contexto: str = None, privacidade: str = "local",
                pasta_skills: Path = PASTA_SKILLS, pasta_modelo: Path = PASTA_MODELO) -> Path:
    if not _RE_NOME.match(nome):
        raise ValueError("O nome deve ter só letras minúsculas, números e hífens (ex.: lista-de-compras).")
    if privacidade not in PRIVACIDADES:
        raise ValueError(f"Privacidade deve ser uma de {sorted(PRIVACIDADES)}.")
    if len(descricao.strip()) < 20:
        raise ValueError("A descrição deve dizer em uma frase o que a skill faz e quando usar.")
    destino = Path(pasta_skills) / nome
    if destino.exists():
        raise FileExistsError(f"A skill '{nome}' já existe em {destino}.")

    catalogo = carregar_catalogo(pasta_skills)
    contexto = contexto or nome.replace("-", "_")
    if catalogo.por_contexto(contexto) is not None:
        raise ValueError(f"O contexto '{contexto}' já pertence à skill '{catalogo.por_contexto(contexto).nome}'.")
    prioridade = max([g.prioridade for g in catalogo.gatilhos] + [0]) + 10
    valores = {"nome": nome, "descricao": " ".join(descricao.split()), "contexto": contexto,
               "privacidade": privacidade, "prioridade": str(prioridade),
               "titulo": nome.replace("-", " ").capitalize()}

    shutil.copytree(pasta_modelo, destino, ignore=shutil.ignore_patterns("__pycache__"))
    try:
        for arquivo in destino.rglob("*"):
            if arquivo.is_file():
                texto = arquivo.read_text(encoding="utf-8")
                for chave, valor in valores.items():
                    texto = texto.replace("{{" + chave + "}}", valor)
                arquivo.write_text(texto, encoding="utf-8")
        carregar_catalogo(pasta_skills)  # a skill nova precisa passar na validação
    except Exception:
        shutil.rmtree(destino, ignore_errors=True)
        raise
    return destino


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cria uma skill nova a partir do modelo.")
    parser.add_argument("nome")
    parser.add_argument("--descricao", required=True, help="o que a skill faz e quando usar (o orquestrador lê isto)")
    parser.add_argument("--contexto", help="padrão: o nome, com _ no lugar de -")
    parser.add_argument("--privacidade", default="local", choices=sorted(PRIVACIDADES))
    args = parser.parse_args(argv)
    try:
        destino = criar_skill(args.nome, args.descricao, args.contexto, args.privacidade)
    except (ValueError, FileExistsError) as erro:
        print(f"Erro: {erro}")
        return 1
    print(f"Skill criada em {destino}. Próximos passos: edite SKILL.md e roteiro.py, preencha exemplos.jsonl "
          f"e rode python scripts/validar_skills.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
