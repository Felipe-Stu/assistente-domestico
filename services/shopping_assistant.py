from datetime import datetime
import json
import logging
from services.logger_service import logger as custom_logger

# Logger do console (terminal)
logging_logger = logging.getLogger(__name__)

NOME_ASSISTENTE = "shopping_assistant"

class ShoppingAssistant:
    def __init__(self, ai_service, db_service):
        """
        Inicializa o assistente de compras.
        Recebe as instâncias de ai_service (para LLM) e db_service (para persistência).
        """
        self.ai_service = ai_service
        self.db_service = db_service
        custom_logger.log_assistente(NOME_ASSISTENTE, "Inicialização do assistente.")

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
        solicita a estruturação ao ai_service e persiste as compras no banco.
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Áudio recebido: '{texto_transcrito}'")
        
        data_atual = datetime.now().strftime("%Y-%m-%d")
        
        prompt = f"""
            Você é um assistente especializado em transformar descrições de compras em registros estruturados.

            Sua única função é analisar o texto informado e retornar APENAS um JSON válido, sem explicações, sem markdown e sem qualquer texto adicional.

            REGRAS

            1. Identifique todos os estabelecimentos mencionados. O usuário pode relatar compras em mais de um mercado no mesmo relato (ex: "comprei tal coisa no Moreschi e tal coisa no Proença").
            2. Se houver mais de um estabelecimento, separe os produtos correspondentes a cada um deles em objetos de compras distintos dentro da lista principal "compras".
            3. A data atual de cada compra é obrigatoriamente: {data_atual}.
            4. Extraia todos os produtos comprados e associe-os ao mercado correto com base no contexto do texto.
            5. Sempre que possível identifique para cada item:
            - nome do produto
            - marca
            - quantidade
            - unidade de medida
            - valor total do item
            - valor unitário
            - categoria (ex: carne, laticínio, limpeza, mercearia, hortifruti, bebida, higiene, etc.)
            6. Caso o valor unitário não seja informado mas exista quantidade e valor total:
            valor_unitario = valor_total / quantidade
            7. Caso quantidade não seja informada:
            quantidade = 1
            8. Caso a unidade não seja informada:
            unidade = "un"
            9. Caso a marca não seja identificada:
            marca = null
            10. Caso o estabelecimento não seja identificado para um grupo de itens:
                estabelecimento = null
            11. Todos os valores monetários devem ser números (float), sem "R$".
            12. Identifique a categoria com base no tipo do produto e preencha como uma string em letras minúsculas (ex: "carne", "laticínio", "limpeza", "bebida", "mercearia").
            13. Não invente informações.

            FORMATO DA RESPOSTA

            {{
                "compras": [
                    {{
                        "estabelecimento": "Nome do Mercado A",
                        "data_compra": "{data_atual}",
                        "itens": [
                            {{
                                "produto": "",
                                "marca": null,
                                "quantidade": 1,
                                "unidade": "un",
                                "valor_unitario": 0.0,
                                "valor_total": 0.0,
                                "categoria": ""
                            }}
                        ],
                        "valor_total_compra": 0.0
                    }},
                    {{
                        "estabelecimento": "Nome do Mercado B",
                        "data_compra": "{data_atual}",
                        "itens": [
                            {{
                                "produto": "",
                                "marca": null,
                                "quantidade": 1,
                                "unidade": "un",
                                "valor_unitario": 0.0,
                                "valor_total": 0.0,
                                "categoria": ""
                            }}
                        ],
                        "valor_total_compra": 0.0
                    }}
                ]
            }}

            Texto informado:

            "{texto_transcrito}"
        """

        logging_logger.info("Enviando texto de compras para estruturação no ShoppingAssistant...")
        custom_logger.log_assistente(NOME_ASSISTENTE, "Envio para o Gemini")
        
        # Chama o ai_service de forma agnóstica
        resposta_json = self.ai_service.enviar_prompt_json(prompt)
        custom_logger.log_assistente(NOME_ASSISTENTE, "Retorno do Gemini")
        
        listagem_compras = []
        if isinstance(resposta_json, dict):
            listagem_compras = resposta_json.get("compras", [resposta_json])
        elif isinstance(resposta_json, list):
            listagem_compras = resposta_json

        # Persiste no banco SQLite através do db_service
        compras_salvas = 0
        for dados_compra in listagem_compras:
            dados_validados = self._validar_e_sanitizar_compra(dados_compra)
            compra_id = self.db_service.salvar_compra_da_ia(dados_validados)
            qtd_itens = len(dados_validados.get("itens", []))
            
            msg_db = f"Procedimentos feitos: Compra (ID: {compra_id}) e {qtd_itens} itens gravados no banco de dados SQLite."
            logging_logger.info("Compra gravada com sucesso pelo ShoppingAssistant! ID: %d", compra_id)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_db)
            compras_salvas += 1

        custom_logger.log_assistente(NOME_ASSISTENTE, f"Dados de processamento: {compras_salvas} compras salvas com sucesso.")

        return {
            "status": "sucesso",
            "mensagem": "Informações inseridas com sucesso!",
            "compras_processadas": compras_salvas
        }