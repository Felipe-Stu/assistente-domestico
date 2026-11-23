"""
Escolha da skill pelo catálogo.

- decisao_pelo_catalogo(): usada pelo orquestrador do app (SK2).
  O prompt é fixo (só nome e descrição das skills, sem a frase do usuário), então o Ollama
  reaproveita o prefixo entre chamadas. A resposta traz skill, ação e dificuldade, e é convertida
  para o formato de decisão que o resto do app já usa (contexto, acao, dificuldade...).
- prompt_catalogo(), ferramentas_nativas(): modos "catalogo" e "nativo" medidos pelo SK0
  (scripts/avaliar.py); a chamada nativa não é usada pelo app.
"""
from typing import Any, Dict, List, Optional

from core.skills.catalogo import Catalogo

# Ações e dificuldades que o modelo pode devolver (chavear_modo só vem de comando direto)
ACOES = ["criar", "corrigir", "consultar", "delegar"]
DIFICULDADES = ["facil", "medio_dificil"]

SKILL_PADRAO = "conversa-geral"


def nomes(catalogo: Catalogo) -> List[str]:
    return [s.nome for s in catalogo]


def prompt_catalogo(catalogo: Catalogo) -> str:
    """Prompt fixo (só nome e descrição de cada skill): o Ollama reaproveita o prefixo entre chamadas."""
    linhas = [f"- {s.nome}: {s.descricao}" for s in catalogo]
    return (
        "Você escolhe qual skill do assistente doméstico deve atender a mensagem do usuário.\n"
        "Não responda à mensagem. Devolva somente o JSON com o nome da skill.\n\n"
        "Skills:\n" + "\n".join(linhas) + "\n\n"
        f"Se nenhuma servir claramente, escolha {SKILL_PADRAO}."
    )


def esquema_catalogo(catalogo: Catalogo) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {"skill": {"type": "string", "enum": nomes(catalogo)}},
        "required": ["skill"],
    }


def nome_ferramenta(skill: str) -> str:
    return "skill_" + skill.replace("-", "_")


def ferramentas_nativas(catalogo: Catalogo) -> List[Dict[str, Any]]:
    """Uma ferramenta por skill, sem parâmetros: só a escolha é medida."""
    return [
        {
            "type": "function",
            "function": {
                "name": nome_ferramenta(s.nome),
                "description": s.descricao,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
        for s in catalogo
    ]


def skill_da_chamada_nativa(resposta: Any, catalogo: Catalogo) -> Optional[str]:
    """Nome da skill chamada pelo modelo, ou None se ele não chamou nenhuma ferramenta conhecida."""
    try:
        mensagem = resposta["message"]
    except Exception:
        mensagem = getattr(resposta, "message", None)
    chamadas = (mensagem.get("tool_calls") if isinstance(mensagem, dict) else getattr(mensagem, "tool_calls", None)) or []
    por_ferramenta = {nome_ferramenta(s.nome): s.nome for s in catalogo}
    for chamada in chamadas:
        funcao = chamada.get("function") if isinstance(chamada, dict) else getattr(chamada, "function", None)
        nome = funcao.get("name") if isinstance(funcao, dict) else getattr(funcao, "name", None)
        if nome in por_ferramenta:
            return por_ferramenta[nome]
    return None


# =============================================================================
# Orquestrador do app (SK2)
# =============================================================================

class DecisaoInvalidaError(ValueError):
    """A resposta do modelo não corresponde a uma skill e ação válidas."""


def prompt_decisao(catalogo: Catalogo) -> str:
    linhas = [f"- {s.nome}: {s.descricao}" for s in catalogo]
    return (
        "Você classifica a mensagem do usuário para o assistente doméstico.\n"
        "Não responda à mensagem. Devolva somente o JSON.\n\n"
        "skill — quem atende:\n" + "\n".join(linhas) + "\n"
        f"Se nenhuma servir claramente, use {SKILL_PADRAO}.\n\n"
        "acao:\n"
        "- criar: registrar, anotar ou agendar algo novo\n"
        "- consultar: perguntar, verificar ou pedir informação\n"
        "- corrigir: alterar ou apagar algo, ou avisar que um item acabou\n"
        "- delegar: pedir ajuda de outra natureza\n\n"
        "dificuldade: \"facil\" para quase tudo, inclusive compras com muitos itens e números. "
        "\"medio_dificil\" só para perguntas gerais que exigem pesquisa, análise ou comparação complexa."
    )


def esquema_decisao(catalogo: Catalogo) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "enum": nomes(catalogo)},
            "acao": {"type": "string", "enum": ACOES},
            "dificuldade": {"type": "string", "enum": DIFICULDADES},
        },
        "required": ["skill", "acao", "dificuldade"],
    }


def converter_decisao(dados: Dict[str, Any], catalogo: Catalogo, contexto_atual: Optional[str]) -> Dict[str, Any]:
    """Resposta do modelo → decisão no formato do orquestrador (contexto, acao, dificuldade...)."""
    if not isinstance(dados, dict):
        raise DecisaoInvalidaError("A resposta do modelo não é um objeto JSON.")
    nome = dados.get("skill")
    try:
        skill = catalogo.skill(nome)
    except KeyError:
        raise DecisaoInvalidaError(f"Skill desconhecida na resposta do modelo: {nome!r}") from None
    acao = dados.get("acao")
    if acao not in ACOES:
        raise DecisaoInvalidaError(f"Ação inválida na resposta do modelo: {acao!r}")
    dificuldade = dados.get("dificuldade")
    if dificuldade not in DIFICULDADES:
        dificuldade = "facil"
    return {
        "dificuldade": dificuldade,
        "mudanca_de_contexto": bool(contexto_atual) and contexto_atual not in skill.contextos,
        "contexto": skill.contexto,
        "acao": acao,
        "skill": skill.nome,
    }


def decisao_pelo_catalogo(texto: str, contexto_atual: Optional[str], provedor, catalogo: Catalogo) -> Dict[str, Any]:
    dados = provedor.gerar_json(prompt_decisao(catalogo), texto, esquema=esquema_decisao(catalogo), raciocinio=False)
    return converter_decisao(dados, catalogo, contexto_atual)
