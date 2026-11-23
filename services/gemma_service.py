"""
Orquestrador: decide qual skill atende cada mensagem.

Ordem: comandos de modo (Qwen) → comando de análise de projeto → gatilhos das skills (sem modelo)
→ escolha pelo catálogo de skills (modelo, prompt curto e fixo). O prompt por contextos fixos
foi removido no SK5 (23/11/2026); está no histórico do Git até o commit d128516.
"""
from typing import Dict, Any, List, Optional

from core.skills import obter_catalogo, seletor
from services.llm_provider import (
    obter_provedor_local,
    ativar_modo_qwen,
    desativar_modo_qwen,
    obter_modelo_ativo,
    verificar_e_gestionar_timeout_inatividade,
    _atualizar_timestamp_atividade
)

from services.resilience_service import InvalidOrchestratorOutputException
from services.intent_router import rotear_por_regras
from services.project_analyzer.command_parser import detectar_comando_projeto
from services.logger_service import logger as custom_logger


def valores_permitidos() -> Dict[str, set]:
    """Contrato da decisão. Os contextos vêm do catálogo: uma skill nova é aceita sem mudar este arquivo."""
    return {
        "dificuldade": {"facil", "medio_dificil"},
        "contexto": {c for skill in obter_catalogo() for c in skill.contextos},
        "acao": {"criar", "corrigir", "consultar", "delegar", "chavear_modo"},
    }


# ==============================================================================
# SANITIZAÇÃO E VALIDAÇÃO DE SCHEMA
# ==============================================================================

def _validar_schema_orquestrador(dados: dict) -> None:
    """
    Valida se o dicionário atende ao contrato do Orquestrador.
    Lança InvalidOrchestratorOutputException se qualquer regra for violada.
    """
    if not isinstance(dados, dict):
        raise InvalidOrchestratorOutputException("O retorno da IA não é um objeto JSON/dicionário válido.")

    campos_obrigatorios = ["dificuldade", "mudanca_de_contexto", "contexto", "acao"]
    for campo in campos_obrigatorios:
        if campo not in dados:
            raise InvalidOrchestratorOutputException(f"Campo obrigatório ausente no JSON: '{campo}'")

    if not isinstance(dados["mudanca_de_contexto"], bool):
        raise InvalidOrchestratorOutputException("O campo 'mudanca_de_contexto' deve ser booleano (true/false).")

    for campo, permitidos in valores_permitidos().items():
        valor = dados.get(campo)
        if valor not in permitidos:
            raise InvalidOrchestratorOutputException(
                f"Valor inválido '{valor}' para o campo '{campo}'. Permitidos: {list(permitidos)}"
            )


# ==============================================================================
# ORQUESTRAÇÃO E EXECUÇÃO
# ==============================================================================

def orquestrar_requisicao(texto_transcrito: str, contexto_atual: Optional[str] = None) -> dict:
    """
    O Orquestrador analisa a solicitação usando o modelo ativo (Gemma ou Qwen)
    e classifica a dificuldade, o contexto e a ação necessária.
    """
    # A inatividade deve ser avaliada antes de registrar a atividade desta solicitação
    verificar_e_gestionar_timeout_inatividade()
    _atualizar_timestamp_atividade()

    # 1. Tratamento de Comandos Diretos de Chaveamento de Modo
    texto_lower = texto_transcrito.lower()
    # Desativação vem primeiro: "desativar qwen" contém "ativar qwen"
    if any(cmd in texto_lower for cmd in ["desativar qwen", "desativar modo qwen", "voltar gemma", "modo normal", "sair do qwen"]):
        desativar_modo_qwen()
        return {
            "dificuldade": "facil",
            "mudanca_de_contexto": True,
            "contexto": "geral",
            "acao": "chavear_modo",
            "resposta_direta": "Modo Qwen desativado. Retornando ao Gemma 4 como orquestrador padrão."
        }

    if any(cmd in texto_lower for cmd in ["ativar qwen", "modo qwen", "modo programador", "chamar qwen", "usar qwen"]):
        ativar_modo_qwen()
        return {
            "dificuldade": "facil",
            "mudanca_de_contexto": True,
            "contexto": "programacao",
            "acao": "chavear_modo",
            "resposta_direta": "Modo Qwen ativado com sucesso! Assumi o controle. Como posso te ajudar?"
        }

    # 1.1 Comando da Skill ProjectAnalyzer (determinístico, sem LLM)
    comando_projeto = detectar_comando_projeto(texto_transcrito)
    if comando_projeto is not None:
        decisao = {
            "dificuldade": "facil",
            "mudanca_de_contexto": True,
            "contexto": "projetos",
            "acao": "consultar",
            "parametros": comando_projeto
        }
        if not comando_projeto.get("caminho"):
            decisao["resposta_direta"] = "Informe o caminho da pasta do projeto. Exemplo: analisar projeto E:\\MOBA"
        return decisao

    # 1.2 Frases conhecidas dispensam a classificação pelo LLM
    decisao_regras = rotear_por_regras(texto_transcrito, contexto_atual)
    if decisao_regras is not None:
        return decisao_regras

    # 2. Obter o modelo ativo para orquestrar
    modelo_ativo = obter_modelo_ativo()

    # 3. Escolha da skill pelo catálogo (SK2)
    return _orquestrar_pelo_catalogo(texto_transcrito, contexto_atual, modelo_ativo)


def _orquestrar_pelo_catalogo(texto_transcrito: str, contexto_atual: Optional[str], modelo_ativo: str) -> dict:
    """Medição de 23/11/2026 no PC: 44/48 acertos em 0,87 s (o prompt por contextos dava 43/48 em 1,39 s)."""
    try:
        provedor = obter_provedor_local(temperatura=0.1)
        decisao = seletor.decisao_pelo_catalogo(texto_transcrito, contexto_atual, provedor, obter_catalogo())
        _validar_schema_orquestrador(decisao)
        return decisao
    except (InvalidOrchestratorOutputException, seletor.DecisaoInvalidaError) as e:
        msg = f"Erro de validação na escolha da skill pelo catálogo ({modelo_ativo}): {e}"
        custom_logger.log_geral(f"[LLMService] {msg}")
        raise InvalidOrchestratorOutputException(msg) from e
    except Exception as e:
        custom_logger.log_geral(f"[LLMService] Erro inesperado no Orquestrador ({modelo_ativo}): {e}")
        raise


def executar_assistente_local(
    contexto: str, 
    historico_mensagens: List[Dict[str, str]], 
    instrucao_usuario: str
) -> str:
    """Responde em texto com o modelo ativo (conversa geral e skills sem roteiro)."""
    _atualizar_timestamp_atividade()

    # O prompt vem da skill do contexto (prompts/sistema.md); sem um, vale o da conversa geral.
    # Compras, estoque, agenda e programação têm roteiro próprio e não passam por aqui.
    catalogo = obter_catalogo()
    skill = catalogo.por_contexto(contexto)
    if skill is not None and skill.caminho_prompt("sistema").exists():
        prompt_sistema = skill.prompt("sistema")
    else:
        prompt_sistema = catalogo.skill("conversa-geral").prompt("sistema")

    provedor = obter_provedor_local(temperatura=0.2)
    return provedor.gerar_texto(prompt_sistema, instrucao_usuario, historico_mensagens)
