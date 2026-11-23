import json
import logging
import os
from typing import Dict, Any, List, Optional
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
    Infraestrutura central de LLM (Nuvem).
    Responsável pela comunicação com a API do Gemini e rotas de fallback.
    """

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self._client = None
        self.model_name = model_name
        custom_logger.log_assistente(NOME_ASSISTENTE, "Serviço AIService (Gemini) inicializado com sucesso.")

    @property
    def client(self):
        """Cria o cliente apenas no primeiro uso; o sistema inicia sem a chave do Gemini."""
        if self._client is None:
            # O Client() lê a GEMINI_API_KEY automaticamente do ambiente (.env)
            self._client = genai.Client()
        return self._client

    def disponivel(self) -> bool:
        """Retorna True se há chave configurada para acessar o Gemini."""
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))

    def chamar_llm(self, prompt: str, json_output: bool = True) -> Any:
        """Envia o prompt para o Gemini na nuvem e retorna a resposta pura ou em JSON."""
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
        """Roteador secundário de intenções do sistema (em nuvem)."""
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Classificando intenção do texto: '{custom_logger.conteudo(texto_usuario)}'")
        
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
    
    @staticmethod
    def _formatar_historico(historico: Optional[List[Dict[str, str]]]) -> str:
        """Converte o histórico da sessão em texto legível para o prompt."""
        if not historico:
            return "Nenhum"
        rotulos = {"user": "Usuário", "assistant": "Assistente"}
        return "\n".join(f"{rotulos.get(m.get('role'), 'Mensagem')}: {m.get('content', '')}" for m in historico)

    def processar_requisicao_complexa(self, mensagem_usuario: str, contexto: Optional[List[Dict[str, str]]] = None) -> str:
        """
        Responde perguntas gerais pela API do Gemini na nuvem.
        Compras, estoque, agenda, programação e documentação são tratados localmente.
        """
        prompt = f"""
        Você é um assistente pessoal. Responda em português do Brasil, de forma clara e objetiva.

        Histórico recente da conversa:
        {self._formatar_historico(contexto)}

        Solicitação do usuário:
        {mensagem_usuario}
        """
        return self.chamar_llm(prompt, json_output=False)