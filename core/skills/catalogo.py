"""
Catálogo de skills (SK1 do roadmap das skills).

Cada capacidade do assistente é uma pasta em skills/<nome>/ com:
- SKILL.md: cabeçalho YAML (nome, descrição, contextos, privacidade, gatilhos...) e instruções;
- prompts/*.md: textos enviados ao modelo, com marcadores {{nome}} preenchidos pelo código;
- código próprio, quando houver (no SK1, o código continua em services/).

Este módulo só lê e valida as pastas. Quem decide o que fazer com cada skill é o núcleo:
o roteador por regras usa os gatilhos e os assistentes usam os prompts. A política de
privacidade continua no núcleo; o campo `privacidade` declara a intenção e um teste
garante que os dois concordam.
"""
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

PASTA_SKILLS = Path(__file__).resolve().parent.parent.parent / "skills"

ESTADOS = {"ativa", "planejada"}
# roteiro: passos em skills/<nome>/roteiro.py, em ordem fixa (SK3); nucleo: ainda executada por app/main.py
EXECUCOES = {"roteiro", "nucleo"}
PRIVACIDADES = {"local", "nuvem-permitida"}
# Entradas e saídas previstas: o roadmap traz voz local, leitura de PDF, imagens e relatórios
ENTRADAS = {"texto", "voz", "pdf", "imagem", "audio"}
SAIDAS = {"texto", "relatorio", "acao"}
ACOES = {"criar", "corrigir", "consultar", "delegar", "chavear_modo"}
CAMPOS_OBRIGATORIOS = ("name", "description", "contextos", "estado", "privacidade", "versao")
_RE_NOME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RE_MARCADOR = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


class SkillInvalidaError(ValueError):
    """Cabeçalho ou estrutura de uma skill fora do formato."""


@dataclass(frozen=True)
class Gatilho:
    skill: str
    acao: str
    prioridade: int
    regex: "re.Pattern"
    parametros: Dict[str, Any] = field(default_factory=dict)
    sem_interrogacao: bool = False

    def casa(self, texto_normalizado: str) -> bool:
        if self.sem_interrogacao and "?" in texto_normalizado:
            return False
        return self.regex.search(texto_normalizado) is not None


@dataclass(frozen=True)
class Skill:
    nome: str
    descricao: str
    contextos: Tuple[str, ...]
    estado: str
    privacidade: str
    entradas: Tuple[str, ...]
    saidas: Tuple[str, ...]
    versao: int
    gatilhos: Tuple[Gatilho, ...]
    instrucoes: str
    pasta: Path
    execucao: str = "nucleo"

    @property
    def contexto(self) -> str:
        """Contexto principal no formato atual do orquestrador."""
        return self.contextos[0]

    @property
    def caminho_roteiro(self) -> Path:
        return self.pasta / "roteiro.py"

    def caminho_prompt(self, nome: str) -> Path:
        return self.pasta / "prompts" / f"{nome}.md"

    def prompt(self, nome: str, **valores: Any) -> str:
        """Lê prompts/<nome>.md e troca cada {{marcador}} pelo valor informado."""
        caminho = self.caminho_prompt(nome)
        if not caminho.exists():
            raise SkillInvalidaError(f"{self.nome}: prompt '{nome}' não encontrado em {caminho}")
        texto = caminho.read_text(encoding="utf-8").rstrip("\n")
        faltando = sorted(set(_RE_MARCADOR.findall(texto)) - set(valores))
        if faltando:
            raise SkillInvalidaError(f"{self.nome}/{nome}: faltam valores para {faltando}")
        return _RE_MARCADOR.sub(lambda m: str(valores[m.group(1)]), texto)


class Catalogo:
    def __init__(self, skills: List[Skill]):
        self.skills = sorted(skills, key=lambda s: s.nome)
        self._por_nome = {s.nome: s for s in self.skills}
        self._por_contexto: Dict[str, Skill] = {}
        for skill in self.skills:
            for contexto in skill.contextos:
                if contexto in self._por_contexto:
                    raise SkillInvalidaError(
                        f"Contexto '{contexto}' declarado por '{self._por_contexto[contexto].nome}' e '{skill.nome}'"
                    )
                self._por_contexto[contexto] = skill
        self.gatilhos = sorted((g for s in self.skills for g in s.gatilhos), key=lambda g: g.prioridade)
        prioridades = [g.prioridade for g in self.gatilhos]
        if len(prioridades) != len(set(prioridades)):
            raise SkillInvalidaError(f"Prioridades de gatilho repetidas: {prioridades}")

    def __iter__(self):
        return iter(self.skills)

    def __len__(self):
        return len(self.skills)

    def skill(self, nome: str) -> Skill:
        try:
            return self._por_nome[nome]
        except KeyError:
            raise KeyError(f"Skill '{nome}' não existe. Disponíveis: {sorted(self._por_nome)}") from None

    def por_contexto(self, contexto: str) -> Optional[Skill]:
        return self._por_contexto.get(contexto)

    def ativas(self) -> List[Skill]:
        return [s for s in self.skills if s.estado == "ativa"]

    def primeiro_gatilho(self, texto_normalizado: str) -> Optional[Gatilho]:
        return next((g for g in self.gatilhos if g.casa(texto_normalizado)), None)


def _lista(valor, campo: str, arquivo: Path) -> Tuple[str, ...]:
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list) or not all(isinstance(v, str) for v in valor) or not valor:
        raise SkillInvalidaError(f"{arquivo}: '{campo}' deve ser uma lista de textos")
    return tuple(valor)


def _ler_cabecalho(arquivo: Path) -> Tuple[Dict[str, Any], str]:
    texto = arquivo.read_text(encoding="utf-8")
    if not texto.startswith("---"):
        raise SkillInvalidaError(f"{arquivo}: falta o cabeçalho entre '---'")
    try:
        _, cabecalho, corpo = texto.split("---", 2)
    except ValueError:
        raise SkillInvalidaError(f"{arquivo}: cabeçalho não fechado com '---'") from None
    try:
        dados = yaml.safe_load(cabecalho) or {}
    except yaml.YAMLError as erro:
        raise SkillInvalidaError(f"{arquivo}: YAML inválido no cabeçalho: {erro}") from None
    if not isinstance(dados, dict):
        raise SkillInvalidaError(f"{arquivo}: o cabeçalho deve ser um mapa de campos")
    return dados, corpo.strip()


def _ler_gatilhos(dados: Dict[str, Any], nome: str, arquivo: Path) -> Tuple[Gatilho, ...]:
    gatilhos = []
    for indice, g in enumerate(dados.get("gatilhos") or []):
        onde = f"{arquivo}: gatilho {indice + 1}"
        if not isinstance(g, dict):
            raise SkillInvalidaError(f"{onde}: deve ser um mapa")
        if g.get("acao") not in ACOES:
            raise SkillInvalidaError(f"{onde}: 'acao' deve ser uma de {sorted(ACOES)}")
        if not isinstance(g.get("prioridade"), int):
            raise SkillInvalidaError(f"{onde}: 'prioridade' deve ser um número inteiro")
        padrao = "|".join(_lista(g.get("padrao"), "padrao", arquivo))
        try:
            regex = re.compile(padrao)
        except re.error as erro:
            raise SkillInvalidaError(f"{onde}: expressão regular inválida: {erro}") from None
        parametros = g.get("parametros") or {}
        if not isinstance(parametros, dict):
            raise SkillInvalidaError(f"{onde}: 'parametros' deve ser um mapa")
        gatilhos.append(Gatilho(nome, g["acao"], g["prioridade"], regex, parametros, bool(g.get("sem_interrogacao"))))
    return tuple(gatilhos)


def carregar_skill(pasta: Path) -> Skill:
    arquivo = pasta / "SKILL.md"
    dados, corpo = _ler_cabecalho(arquivo)
    faltando = [c for c in CAMPOS_OBRIGATORIOS if c not in dados]
    if faltando:
        raise SkillInvalidaError(f"{arquivo}: campos obrigatórios ausentes: {faltando}")
    nome = dados["name"]
    if not isinstance(nome, str) or not _RE_NOME.match(nome) or nome != pasta.name:
        raise SkillInvalidaError(f"{arquivo}: 'name' deve ser igual ao nome da pasta, em minúsculas com hífens")
    if not isinstance(dados["description"], str) or len(dados["description"].strip()) < 20:
        raise SkillInvalidaError(f"{arquivo}: 'description' deve dizer em uma frase quando usar a skill")
    if dados["estado"] not in ESTADOS:
        raise SkillInvalidaError(f"{arquivo}: 'estado' deve ser um de {sorted(ESTADOS)}")
    if dados["privacidade"] not in PRIVACIDADES:
        raise SkillInvalidaError(f"{arquivo}: 'privacidade' deve ser um de {sorted(PRIVACIDADES)}")
    if not isinstance(dados["versao"], int):
        raise SkillInvalidaError(f"{arquivo}: 'versao' deve ser um número inteiro")
    execucao = dados.get("execucao", "nucleo")
    if execucao not in EXECUCOES:
        raise SkillInvalidaError(f"{arquivo}: 'execucao' deve ser um de {sorted(EXECUCOES)}")
    if execucao == "roteiro" and not (pasta / "roteiro.py").is_file():
        raise SkillInvalidaError(f"{arquivo}: 'execucao: roteiro' exige o arquivo roteiro.py na pasta da skill")
    entradas = _lista(dados.get("entradas", ["texto"]), "entradas", arquivo)
    saidas = _lista(dados.get("saidas", ["texto"]), "saidas", arquivo)
    for valor, permitidos, campo in ((entradas, ENTRADAS, "entradas"), (saidas, SAIDAS, "saidas")):
        if set(valor) - permitidos:
            raise SkillInvalidaError(f"{arquivo}: '{campo}' aceita {sorted(permitidos)}")
    return Skill(
        nome=nome,
        descricao=" ".join(dados["description"].split()),
        contextos=_lista(dados["contextos"], "contextos", arquivo),
        estado=dados["estado"],
        privacidade=dados["privacidade"],
        entradas=entradas,
        saidas=saidas,
        versao=dados["versao"],
        gatilhos=_ler_gatilhos(dados, nome, arquivo),
        instrucoes=corpo,
        pasta=pasta,
        execucao=execucao,
    )


def carregar_catalogo(pasta: Path = PASTA_SKILLS) -> Catalogo:
    pasta = Path(pasta)
    if not pasta.is_dir():
        raise SkillInvalidaError(f"Pasta de skills não encontrada: {pasta}")
    return Catalogo([carregar_skill(p) for p in sorted(pasta.iterdir()) if (p / "SKILL.md").is_file()])


@lru_cache(maxsize=1)
def obter_catalogo() -> Catalogo:
    """Catálogo da pasta padrão, lido uma vez por execução."""
    return carregar_catalogo(PASTA_SKILLS)


def recarregar_catalogo() -> Catalogo:
    obter_catalogo.cache_clear()
    return obter_catalogo()
