import json
import ollama
from services.resilience_service import InvalidOrchestratorOutputException
from services.logger_service import logger as custom_logger

NOME_MODELO = "gemma4:e4b"

VALORES_PERMITIDOS = {
    "dificuldade": {"facil", "medio_dificil"},
    "contexto": {"compras", "agenda", "inventario", "outro", "geral"},
    "acao": {"criar", "corrigir", "consultar", "delegar"}
}


def _sanitizar_resposta_json(conteudo_bruto: str) -> str:
    """
    Remove marcações de código Markdown (```json ... ```) e espaços extras.
    """
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
    Valida rigorosamente se o dicionário atende ao contrato exigido do Orquestrador.
    Lança InvalidOrchestratorOutputException se qualquer regra for violada.
    """
    if not isinstance(dados, dict):
        raise InvalidOrchestratorOutputException("O retorno do Gemma não é um objeto JSON/dicionário válido.")

    campos_obrigatorios = ["dificuldade", "mudanca_de_contexto", "contexto", "acao"]
    for campo in campos_obrigatorios:
        if campo not in dados:
            raise InvalidOrchestratorOutputException(f"Campo obrigatório ausente no JSON do Gemma: '{campo}'")

    if not isinstance(dados["mudanca_de_contexto"], bool):
        raise InvalidOrchestratorOutputException("O campo 'mudanca_de_contexto' deve ser booleano (true/false).")

    for campo, permitidos in VALORES_PERMITIDOS.items():
        valor = dados.get(campo)
        if valor not in permitidos:
            raise InvalidOrchestratorOutputException(
                f"Valor inválido '{valor}' para o campo '{campo}'. Permitidos: {list(permitidos)}"
            )


def orquestrar_requisicao(texto_transcrito: str, contexto_atual: str = None) -> dict:
    """
        O Orquestrador analisa a solicitação do usuário e o contexto atual e determina a dificuldade, o contexto e a ação necessária.
    """

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
        cliente_ollama = ollama.Client(timeout=120.0)
        response = cliente_ollama.chat(
            model=NOME_MODELO,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": texto_transcrito}
            ],
            format="json",
            options={"temperature": 0.1}
        )

        conteudo_bruto = response['message']['content']
        conteudo_sanitizado = _sanitizar_resposta_json(conteudo_bruto)
        
        dados = json.loads(conteudo_sanitizado)
        _validar_schema_orquestrador(dados)

        return dados

    except json.JSONDecodeError as e:
        msg = f"Erro de parse no JSON retornado pelo Gemma: {e}"
        custom_logger.log_geral(f"[GemmaService] {msg}")
        raise InvalidOrchestratorOutputException(msg) from e
    except Exception as e:
        if not isinstance(e, InvalidOrchestratorOutputException):
            custom_logger.log_geral(f"[GemmaService] Erro inesperado na chamada do Gemma: {e}")
        raise


def executar_assistente_local(contexto: str, historico_mensagens: list, instrucao_usuario: str) -> str:
    """
    Executa demandas simples no modelo local especialista.
    """
    system_prompts = {
        "compras": "Você é o Assistente de Compras e Gastos. Extraia valores, produtos e locais em JSON para gravação no banco.",
        "agenda": "Você é o Assistente de Agenda. Extraia eventos, datas e horários em JSON."
    }

    prompt_sistema = system_prompts.get(contexto, "Você é um assistente pessoal prestativo.")

    messages = [{"role": "system", "content": prompt_sistema}]
    messages.extend(historico_mensagens)
    messages.append({"role": "user", "content": instrucao_usuario})

    cliente_ollama = ollama.Client(timeout=120.0)
    response = cliente_ollama.chat(
        model=NOME_MODELO,
        messages=messages,
        format="json" if contexto in ["compras", "agenda"] else None
    )

    return response['message']['content']