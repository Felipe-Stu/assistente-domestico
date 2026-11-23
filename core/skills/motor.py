"""
Motor de roteiros (SK3 do roadmap das skills).

Uma skill com `execucao: roteiro` tem os passos em skills/<nome>/roteiro.py, em ordem fixa:
o modelo só faz o que o roteiro pede (por exemplo, extrair os dados de uma compra); validar,
pedir confirmação e gravar continuam sendo código.

O roteiro define:
    executar(ctx, texto, decisao) -> Resposta
    responder_pendencia(ctx, texto, dados) -> Resposta     # opcional, se a skill pede confirmação

`ctx` dá acesso só ao que o núcleo entrega (serviços e a função de repetição); o roteiro não
conhece o runtime, o Electron nem a política de nuvem. Serviços entregues a toda skill:
llm_local (modelo residente), db_service, shopping_assistant, inventory_assistant,
project_analyzer e progresso. A skill de programação recebe também llm_programacao,
biblioteca e historico; o Claude só vai para as skills autorizadas em CLAUDE_SKILLS.
"""
import importlib.util
import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable, Dict, Optional

from core.skills.catalogo import Skill, SkillInvalidaError

_MODULOS: Dict[str, ModuleType] = {}


@dataclass
class Resposta:
    texto: str
    fala: Optional[str] = None          # texto para a voz, quando diferente do chat
    pendencia: Any = None               # dados aguardando confirmação; a próxima mensagem volta para a skill


@dataclass
class Contexto:
    servicos: Dict[str, Any] = field(default_factory=dict)
    # repetir(func, args, mensagem_espera_voz, nome_servico) -> resultado; aplica a política de
    # repetição do núcleo (tentativas, espera, Ollama fora é fatal)
    repetir: Callable[..., Any] = None

    def servico(self, nome: str) -> Any:
        try:
            return self.servicos[nome]
        except KeyError:
            raise KeyError(f"Serviço '{nome}' não foi entregue à skill. Disponíveis: {sorted(self.servicos)}") from None


def carregar_roteiro(skill: Skill) -> ModuleType:
    """Importa skills/<nome>/roteiro.py uma vez por execução."""
    if skill.execucao != "roteiro":
        raise SkillInvalidaError(f"{skill.nome}: a skill não é executada por roteiro")
    caminho = skill.caminho_roteiro
    chave = str(caminho)
    if chave not in _MODULOS:
        nome_modulo = "skill_roteiro_" + skill.nome.replace("-", "_")
        especificacao = importlib.util.spec_from_file_location(nome_modulo, caminho)
        modulo = importlib.util.module_from_spec(especificacao)
        sys.modules[nome_modulo] = modulo
        especificacao.loader.exec_module(modulo)
        if not callable(getattr(modulo, "executar", None)):
            raise SkillInvalidaError(f"{caminho}: o roteiro precisa definir executar(ctx, texto, decisao)")
        _MODULOS[chave] = modulo
    return _MODULOS[chave]


def executar(skill: Skill, ctx: Contexto, texto: str, decisao: Dict[str, Any]) -> Resposta:
    return _como_resposta(carregar_roteiro(skill).executar(ctx, texto, decisao))


def responder_pendencia(skill: Skill, ctx: Contexto, texto: str, dados: Any) -> Resposta:
    modulo = carregar_roteiro(skill)
    if not callable(getattr(modulo, "responder_pendencia", None)):
        raise SkillInvalidaError(f"{skill.nome}: há uma pendência, mas o roteiro não define responder_pendencia")
    return _como_resposta(modulo.responder_pendencia(ctx, texto, dados))


def _como_resposta(resultado: Any) -> Resposta:
    if isinstance(resultado, Resposta):
        return resultado
    if isinstance(resultado, str):
        return Resposta(resultado)
    raise SkillInvalidaError(f"O roteiro devolveu {type(resultado).__name__}; esperado Resposta ou texto")
