import json
from typing import Dict, Any, List, Optional

from core.config import ORQUESTRADOR_MODO
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
from services.esquemas import ESQUEMA_ORQUESTRADOR
from services.intent_router import rotear_por_regras
from services.project_analyzer.command_parser import detectar_comando_projeto
from services.logger_service import logger as custom_logger


# Schema de Validação
VALORES_PERMITIDOS = {
    "dificuldade": {"facil", "medio_dificil"},
    "contexto": {"compras", "agenda", "inventario", "programacao", "projetos", "outro", "geral"},
    "acao": {"criar", "corrigir", "consultar", "delegar", "chavear_modo"}
}


# Prompt do assistente de programação: skills/programacao/prompts/sistema.md
PROMPT_PROGRAMACAO = obter_catalogo().skill("programacao").prompt("sistema")


# ==============================================================================
# SANITIZAÇÃO E VALIDAÇÃO DE SCHEMA
# ==============================================================================

def _sanitizar_resposta_json(conteudo_bruto: str) -> str:
    """Remove marcações de código Markdown (```json ... ```) e espaços extras."""
    conteudo = conteudo_bruto.strip()
    if conteudo.startswith("```"):
        linhas = conteudo.splitlines()
        if linhas[0].startswith("```"):
            linhas = linhas[1:]
        if linhas and linhas[-1].startswith("```"):
            linhas = linhas[:-1]
        conteudo = "\n".join(linhas).strip()
    return conteudo


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

    for campo, permitidos in VALORES_PERMITIDOS.items():
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

    # 3. SK2: escolha da skill pelo catálogo (prompt curto e fixo). ORQUESTRADOR_MODO=contextos volta ao prompt abaixo.
    if ORQUESTRADOR_MODO == "catalogo":
        return _orquestrar_pelo_catalogo(texto_transcrito, contexto_atual, modelo_ativo)

    system_prompt = f"""
        Você é o ORQUESTRADOR do assistente virtual.

        SUA ÚNICA FUNÇÃO é CLASSIFICAR a solicitação do usuário.
        NÃO responda, execute tarefas, faça cálculos ou pesquisas.
        RETORNE SOMENTE UM JSON VÁLIDO. NÃO use Markdown nem texto fora do JSON.

        CONTEXTO ATUAL:
        {contexto_atual if contexto_atual else "Nenhum contexto ativo."}

        SOLICITAÇÃO:
        {texto_transcrito}

        ==================================================
        DIFICULDADE
        ==================================================

        Existem somente duas opções: "facil" e "medio_dificil".

        A dificuldade representa a COMPLEXIDADE DA TAREFA, e NÃO a
        quantidade de informações existentes na frase.

        FACIL:
        Use "facil" quando a solicitação pertence a um fluxo conhecido,
        direto e previamente definido pelo sistema.

        Também é "facil" quando houver:
        - vários produtos;
        - vários preços;
        - várias quantidades;
        - vários pesos ou unidades;
        - vários estabelecimentos;
        - cálculos simples;
        - conversões simples de unidades;
        - necessidade de precisão na extração;
        - uma frase longa.

        Exemplos de "facil":
        - registrar uma compra;
        - registrar vários produtos de uma compra;
        - registrar pesos como "3 kg 124 g";
        - consultar uma compra;
        - corrigir uma compra;
        - criar ou consultar um compromisso;
        - consultar dados locais;
        - consultar o banco de dados;
        - consultar a agenda;
        - consultar inventário;
        - executar uma operação simples já prevista pelo sistema.

        EXEMPLO IMPORTANTE:
        "Comprei 3 kg 124 g de frango por R$ 16,99 o kg,
        detergente Minuano por R$ 2,69 e chiclete Trident por R$ 3,49."

        Resultado obrigatório:
        "dificuldade": "facil"

        Motivo: existem muitos dados, mas a tarefa continua sendo
        REGISTRAR UMA COMPRA, que é um fluxo conhecido.

        MEDIO_DIFICIL:
        Use "medio_dificil" SOMENTE quando a natureza da tarefa exigir
        uma capacidade significativamente diferente de um fluxo simples.

        Exemplos:
        - pesquisa na internet;
        - consulta a informações externas;
        - análise técnica detalhada;
        - comparação complexa entre alternativas;
        - análise de informações externas;
        - várias etapas INDEPENDENTES que precisam ser executadas;
        - solicitação explicitamente complexa ou difícil;
        - tarefa que não possa ser atendida adequadamente pelos fluxos
          conhecidos do sistema.

        NÃO classifique como "medio_dificil" somente porque:
        - a frase é longa;
        - existem muitos produtos ou números;
        - existem muitos preços ou quantidades;
        - existem várias unidades;
        - existem vários estabelecimentos;
        - é necessário extrair muitos campos;
        - é necessário fazer cálculos simples;
        - é necessário converter kg/g ou litro/ml;
        - é necessário validar dados;
        - é necessária alta precisão;
        - existem várias operações do MESMO TIPO.

        REGRA DE DECISÃO:
        1. Identifique primeiro a tarefa principal.
        2. Verifique se existe um fluxo conhecido e direto para ela.
        3. Se existir, use "facil".
        4. Só use "medio_dificil" se a natureza da tarefa exigir capacidade
           adicional, pesquisa, análise complexa, comparação ou etapas
           independentes.
        5. NÃO use "medio_dificil" automaticamente em caso de dúvida.

        ==================================================
        CONTEXTO
        ==================================================

        Valores permitidos:
        "compras", "agenda", "inventario", "outro", "geral"

        "compras" → compras, produtos, preços e gastos.
        "agenda" → compromissos, eventos, horários e lembretes.
        "inventario" → estoque, consumo e reposição.
        "outro" → assunto que não pertence aos contextos anteriores.
        "geral" → conversa geral sem operação específica.

        Se houver mais de um contexto, escolha o predominante.

        ==================================================
        MUDANÇA DE CONTEXTO
        ==================================================

        true → o usuário mudou de assunto/contexto.
        false → permaneceu no mesmo contexto ou não existe contexto anterior.
        Se não houver contexto atual, use false.

        ==================================================
        AÇÃO
        ==================================================

        Valores permitidos:
        "criar", "corrigir", "consultar", "delegar"

        "criar" → registrar, adicionar, agendar ou criar.
        "corrigir" → alterar, corrigir, editar ou excluir algo existente.
        "consultar" → obter, verificar ou pesquisar informação.
        "delegar" → encaminhar para outro agente, serviço ou ferramenta.

        ==================================================
        EXEMPLOS
        ==================================================

        Entrada: "Registre uma compra de 2 kg de arroz por 20 reais."
        Saída:
        {{"dificuldade":"facil","mudanca_de_contexto":false,"contexto":"compras","acao":"criar"}}

        Entrada: "Comprei 3 kg 124 g de frango, detergente por 2,69,
        chiclete por 3,49, 484 g de cebola e 106 g de alho."
        Saída:
        {{"dificuldade":"facil","mudanca_de_contexto":false,"contexto":"compras","acao":"criar"}}

        Entrada: "Pesquise na internet os preços do frango e compare
        os três mercados mais baratos."
        Saída:
        {{"dificuldade":"medio_dificil","mudanca_de_contexto":false,"contexto":"compras","acao":"consultar"}}

        Entrada: "Quanto gastei no Moreschi este mês?"
        Saída:
        {{"dificuldade":"facil","mudanca_de_contexto":false,"contexto":"compras","acao":"consultar"}}

        Entrada: "Ainda tenho leite em casa?"
        Saída:
        {{"dificuldade":"facil","mudanca_de_contexto":false,"contexto":"inventario","acao":"consultar"}}

        ==================================================
        VALIDAÇÃO FINAL
        ==================================================

        Antes de responder, confirme:
        - dificuldade representa a tarefa, não o tamanho da frase;
        - muitos dados do mesmo fluxo continuam sendo "facil";
        - contexto está correto;
        - ação está correta;
        - mudanca_de_contexto é booleano;
        - todos os valores pertencem às opções permitidas.

        RETORNE SOMENTE O JSON.
    """

    try:
        provedor = obter_provedor_local(temperatura=0.1)
        # Classificar não exige raciocínio: com ele ligado, o Gemma 4 levava ~8 s por decisão; sem ele, ~1 s,
        # com o mesmo acerto (medição de 17/11/2026 em Planejamento/medicoes)
        dados = provedor.gerar_json(system_prompt, texto_transcrito, esquema=ESQUEMA_ORQUESTRADOR, raciocinio=False)
        
        _validar_schema_orquestrador(dados)
        return dados

    except InvalidOrchestratorOutputException as e:
        msg = f"Erro de validação ou parse no JSON retornado pelo Orquestrador ({modelo_ativo}): {e}"
        custom_logger.log_geral(f"[LLMService] {msg}")
        raise InvalidOrchestratorOutputException(msg) from e
    except Exception as e:
        custom_logger.log_geral(f"[LLMService] Erro inesperado no Orquestrador ({modelo_ativo}): {e}")
        raise


def _orquestrar_pelo_catalogo(texto_transcrito: str, contexto_atual: Optional[str], modelo_ativo: str) -> dict:
    """Medição de 23/11/2026 (SK0): 45/48 acertos em 0,55 s, contra 43/48 em 1,39 s do prompt por contextos."""
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
    """
    Executa a tarefa utilizando a IA ativa (Gemma ou Qwen).
    Funciona de forma unificada para qualquer contexto ou assistente.
    """
    _atualizar_timestamp_atividade()

    system_prompts = {
        "compras": "Você é o Assistente de Compras e Gastos. Extraia valores, produtos e locais em JSON para gravação no banco.",
        "agenda": "Você é o Assistente de Agenda. Extraia eventos, datas e horários em JSON.",
    }

    # O prompt de cada contexto vem da skill (prompts/sistema.md); sem um, vale o da conversa geral
    catalogo = obter_catalogo()
    skill = catalogo.por_contexto(contexto)
    if skill is not None and skill.caminho_prompt("sistema").exists():
        prompt_sistema = skill.prompt("sistema")
    else:
        prompt_sistema = system_prompts.get(contexto) or catalogo.skill("conversa-geral").prompt("sistema")

    provedor = obter_provedor_local(temperatura=0.2)

    if contexto in ["compras", "agenda"]:
        dados_json = provedor.gerar_json(prompt_sistema, instrucao_usuario, historico_mensagens)
        return json.dumps(dados_json, ensure_ascii=False)
    else:
        return provedor.gerar_texto(prompt_sistema, instrucao_usuario, historico_mensagens)