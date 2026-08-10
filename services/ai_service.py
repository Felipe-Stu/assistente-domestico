import json
import logging
from typing import Dict, Any
from google import genai
from google.genai import types
from services.logger_service import logger as custom_logger

# Configuração do Logging nativo (Console)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

NOME_ASSISTENTE = "ai_service"


class TokenExhaustedException(Exception):
    """Exceção lançada quando a cota ou os tokens da API do Gemini são esgotados."""
    pass


class ServiceUnavailableException(Exception):
    """Exceção lançada quando o Gemini retorna erro 503 (Servidor indisponível / Alta demanda)."""
    pass


class AIService:
    """
    Infraestrutura central de LLM.
    Responsável pela comunicação com a API do Gemini, 
    gerenciamento de chamadas e roteamento de intenção.
    """

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.client = genai.Client()
        self.model_name = model_name
        custom_logger.log_assistente(NOME_ASSISTENTE, "Serviço AIService inicializado com sucesso.")

    def chamar_llm(self, prompt: str, json_output: bool = True) -> Any:
        """Envia o prompt para o Gemini e retorna a resposta pura ou em JSON."""
        custom_logger.log_assistente(NOME_ASSISTENTE, "Envio para o Gemini iniciado.")
        
        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json" if json_output else "text/plain"
            )
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config
            )

            if json_output:
                dados_json = json.loads(response.text)
                custom_logger.log_assistente(NOME_ASSISTENTE, "Retorno do Gemini: JSON extraído com sucesso.")
                return dados_json

            custom_logger.log_assistente(NOME_ASSISTENTE, "Retorno do Gemini: Texto recebido com sucesso.")
            return response.text

        except json.JSONDecodeError as e:
            msg_erro = f"Erro ao decodificar JSON retornado pelo Gemini: {e}"
            logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)
            raise

        except Exception as e:
            str_erro = str(e).lower()

            # Captura erro 503 / Service Unavailable / High Demand
            if "503" in str_erro or "unavailable" in str_erro or "high demand" in str_erro:
                msg_503 = f"Erro 503 detectado: Servidor do Gemini congestionado ou indisponível. {e}"
                logger.warning(msg_503)
                custom_logger.log_assistente(NOME_ASSISTENTE, msg_503)
                raise ServiceUnavailableException(msg_503) from e

            # Captura esgotamento de cota/tokens da API (HTTP 429)
            elif "quota" in str_erro or "429" in str_erro or "resource_exhausted" in str_erro:
                msg_exaustao = "Limite de requisições/tokens da API do Gemini atingido."
                logger.error(msg_exaustao)
                custom_logger.log_assistente(NOME_ASSISTENTE, msg_exaustao)
                raise TokenExhaustedException(msg_exaustao) from e

            msg_erro = f"Erro ao se comunicar com a API do Gemini: {e}"
            logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)
            raise

    def classificar_intencao_usuario(self, texto_usuario: str) -> Dict[str, Any]:
        """Roteador primário de intenções do sistema."""
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Classificando intenção do texto: '{texto_usuario}'")
        
        prompt = f"""
        Você é o roteador principal de intenções de um sistema de gestão doméstica.
        Classifique o texto do usuário em UMA das seguintes intenções:

        - "REGISTRO_COMPRA": O usuário está informando que comprou itens, relatando nota ou cupom fiscal.
        - "CONSULTA_ESTOQUE": O usuário está perguntando sobre disponibilidade, estoque ou se precisa comprar algo.
        - "ATUALIZACAO_ESTOQUE": O usuário está avisando que um produto acabou, que usou um item ou atualizando quantidade residual.
        - "OUTRO": Qualquer outra mensagem que não se encaixe nas categorias acima.

        Retorne APENAS um JSON no seguinte formato:
        {{
            "intencao": "REGISTRO_COMPRA | CONSULTA_ESTOQUE | ATUALIZACAO_ESTOQUE | OUTRO",
            "confianca": 0.0 a 1.0
        }}

        Texto do usuário: "{texto_usuario}"
        """
        return self.chamar_llm(prompt, json_output=True)

    def enviar_prompt_json(self, prompt: str) -> Any:
        """Alias para chamar_llm com saída JSON."""
        return self.chamar_llm(prompt, json_output=True)
    
    def processar_requisicao_complexa(self, mensagem_usuario: str, contexto: str = None) -> str:
        """
        Método de Fallback acionado quando o LLM local falha.
        Envia a requisição para a API do Gemini na nuvem.
        """
        prompt = f"""
        Você é um assistente doméstico. Processe e estruture o seguinte texto de compras:
        "{mensagem_usuario}"
        
        Retorne os itens e valores identificados.
        """
        # Execute a chamada ao modelo Gemini aqui (ex: google-genai ou httpx)
        resposta = self.gemini_client.generate_content(prompt) # Adapte para sua chamada real
        return resposta.text