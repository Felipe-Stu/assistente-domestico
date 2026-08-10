from datetime import datetime
import logging
from typing import Dict, Any, List, Optional

from services.llm_provider import BaseLLMProvider
from services.logger_service import logger as custom_logger

# Logger do console (terminal)
logging_logger = logging.getLogger(__name__)

NOME_ASSISTENTE = "shopping_assistant"


class ShoppingAssistant:
    def __init__(
        self, 
        db_service: Any, 
        ai_service: Any = None, 
        llm_provider: Optional[BaseLLMProvider] = None
    ):
        """
        Inicializa o assistente de compras.
        Suporta injeção flexível do serviço de IA (ai_service ou llm_provider desacoplado).
        """
        self.db_service = db_service
        self.ai_service = ai_service
        # Se llm_provider não for informado explicitamente, assume o ai_service como provedor
        self.llm_provider = llm_provider or ai_service
        
        if not self.llm_provider:
            logging_logger.warning(
                "ShoppingAssistant inicializado sem 'llm_provider' ou 'ai_service' válido!"
            )

        custom_logger.log_assistente(
            NOME_ASSISTENTE, 
            "Inicialização do assistente de compras concluída com sucesso."
        )

    def _validar_e_sanitizar_compra(self, dados_compra: dict) -> dict:
        """
        Valida e higieniza os valores numéricos dos itens da compra para evitar divisões por zero
        e assegurar a consistência dos dados financeiros antes de salvar no banco.
        """
        dados_validados = dados_compra.copy()
        itens = dados_validados.get("itens", [])
        itens_validados = []
        valor_total_calculado_compra = 0.0

        for item in itens:
            item_validado = item.copy()

            produto = item_validado.get("produto", "").strip()
            if not produto:
                continue

            quantidade = item_validado.get("quantidade")
            valor_unitario = item_validado.get("valor_unitario")
            valor_total = item_validado.get("valor_total")

            try:
                quantidade = float(quantidade) if quantidade is not None else 0.0
            except (ValueError, TypeError):
                quantidade = 0.0

            try:
                valor_unitario = float(valor_unitario) if valor_unitario is not None else 0.0
            except (ValueError, TypeError):
                valor_unitario = 0.0

            try:
                valor_total = float(valor_total) if valor_total is not None else 0.0
            except (ValueError, TypeError):
                valor_total = 0.0

            if quantidade <= 0:
                if valor_total > 0 and valor_unitario > 0:
                    quantidade = valor_total / valor_unitario
                else:
                    quantidade = 1.0

            if valor_unitario <= 0:
                if valor_total > 0 and quantidade > 0:
                    valor_unitario = valor_total / quantidade
                else:
                    valor_unitario = 0.0

            if valor_total <= 0:
                if quantidade > 0 and valor_unitario > 0:
                    valor_total = quantidade * valor_unitario
                else:
                    valor_total = 0.0

            if abs(valor_total - (quantidade * valor_unitario)) > 0.05:
                valor_total = round(quantidade * valor_unitario, 2)

            item_validado["quantidade"] = quantidade
            item_validado["valor_unitario"] = round(valor_unitario, 2)
            item_validado["valor_total"] = round(valor_total, 2)

            valor_total_calculado_compra += valor_total
            itens_validados.append(item_validado)

        dados_validados["itens"] = itens_validados
        dados_validados["valor_total_compra"] = round(valor_total_calculado_compra, 2)
        return dados_validados

    def processar_texto_compra(self, texto_transcrito: str) -> dict:
        """
        Gera o prompt especializado em parsing de compras (multi-mercados),
        solicita a estruturação ao llm_provider e persiste as compras no banco.
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Áudio recebido: '{texto_transcrito}'")

        if not self.llm_provider:
            erro_msg = "Nenhum provedor de LLM configurado para processar a compra."
            logging_logger.error(erro_msg)
            return {"status": "erro", "mensagem": erro_msg, "compras_processadas": 0}

        data_atual = datetime.now().strftime("%Y-%m-%d")

        prompt_sistema = f"""
        Você é um extrator de dados de compras em formato JSON rigoroso.
        Sua única tarefa é converter a transcrição de voz fornecida pelo usuário em um JSON válido.

        ### REGRAS CRÍTICAS DE SAÍDA:
        1. Responda APENAS com o JSON. 
        2. NÃO use blocos de código (NÃO use ```json ou ```).
        3. NÃO inclua nenhum texto de apresentação, explicação ou comentário antes ou depois do JSON.

        ---

        ### REGRAS DE CONVERSÃO E CÁLCULO:

        1. QUANTIDADES COMPOSTAS (PESOS E VOLUMES):
        - Some quilos e gramas em um único valor decimal em quilos (kg).
            * Exemplo: "3 kg 124 g" ou "3 kg e 124 g" -> quantidade: 3.124, unidade: "kg"
            * Exemplo: "106 gramas" ou "106 g" -> quantidade: 0.106, unidade: "kg"
            * Exemplo: "484 g" -> quantidade: 0.484, unidade: "kg"
        - Some litros e mililitros em um único valor decimal em litros (litro).
            * Exemplo: "1 litro e 250 ml" -> quantidade: 1.25, unidade: "litro"

        2. PREÇOS E CÁLCULOS:
        - valor_unitario: O preço por unidade (kg, litro, un, pacote).
        - valor_total (item): Arredonde para 2 casas decimais -> quantidade * valor_unitario
        - valor_total_compra: Soma dos valores totais dos itens do estabelecimento.

        3. VALORES PADRÃO (QUANDO NÃO INFORMADO):
        - marca -> null
        - estabelecimento -> "Não informado" (se nenhum for dito)
        - data_compra -> "{data_atual}"

        ---

        ### EXEMPLOS DE CONVERSÃO (Siga este padrão estritamente):

        ENTRADA:
        "eu fui ao mercado Moreschi e comprei peito de frango por r$ 16,99 o quilo comprei 3 kg 124 G comprei também detergente Minuano por r$ 2,69 e alho 27,99 o quilo eu comprei 106 gramas"

        SAÍDA:
        {{
        "compras": [
            {{
            "estabelecimento": "Moreschi",
            "data_compra": "{data_atual}",
            "itens": [
                {{
                "produto": "peito de frango",
                "marca": null,
                "quantidade": 3.124,
                "unidade": "kg",
                "valor_unitario": 16.99,
                "valor_total": 53.08,
                "categoria": "carne"
                }},
                {{
                "produto": "detergente",
                "marca": "Minuano",
                "quantidade": 1.0,
                "unidade": "un",
                "valor_unitario": 2.69,
                "valor_total": 2.69,
                "categoria": "limpeza"
                }},
                {{
                "produto": "alho",
                "marca": null,
                "quantidade": 0.106,
                "unidade": "kg",
                "valor_unitario": 27.99,
                "valor_total": 2.97,
                "categoria": "hortifruti"
                }}
            ],
            "valor_total_compra": 58.74
            }}
        ]
        }}

        ---

        ### FORMATO FINAL OBRIGATÓRIO:

        {{
        "compras": [
            {{
            "estabelecimento": "Nome do Estabelecimento",
            "data_compra": "{data_atual}",
            "itens": [
                {{
                "produto": "nome do produto",
                "marca": null,
                "quantidade": 1.0,
                "unidade": "un",
                "valor_unitario": 0.0,
                "valor_total": 0.0,
                "categoria": "categoria"
                }}
            ],
            "valor_total_compra": 0.0
            }}
        ]
        }}
        """

        logging_logger.info("Enviando texto de compras para estruturação via LLMProvider...")
        custom_logger.log_assistente(NOME_ASSISTENTE, "Solicitando extração de compras em JSON ao LLMProvider.")

        # Solicita a estrutura JSON através do provedor de LLM configurado (Local ou Nuvem)
        resposta_json = self.llm_provider.gerar_json(
            prompt_sistema=prompt_sistema,
            mensagem_usuario=texto_transcrito
        )
        custom_logger.log_assistente(NOME_ASSISTENTE, "Estrutura JSON retornada pelo LLMProvider com sucesso.")

        listagem_compras = []
        if isinstance(resposta_json, dict):
            listagem_compras = resposta_json.get("compras", [resposta_json])
        elif isinstance(resposta_json, list):
            listagem_compras = resposta_json

        # Persiste no banco SQLite através do db_service
        compras_salvas = 0
        for dados_compra in listagem_compras:
            if not isinstance(dados_compra, dict):
                continue
            dados_validados = self._validar_e_sanitizar_compra(dados_compra)
            compra_id = self.db_service.salvar_compra_da_ia(dados_validados)
            qtd_itens = len(dados_validados.get("itens", []))

            msg_db = f"Procedimentos feitos: Compra (ID: {compra_id}) e {qtd_itens} itens gravados no banco SQLite."
            logging_logger.info("Compra gravada com sucesso pelo ShoppingAssistant! ID: %s", compra_id)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_db)
            compras_salvas += 1

        custom_logger.log_assistente(NOME_ASSISTENTE, f"Dados de processamento: {compras_salvas} compras salvas com sucesso.")

        return {
            "status": "sucesso",
            "mensagem": "Informações inseridas com sucesso!",
            "compras_processadas": compras_salvas}