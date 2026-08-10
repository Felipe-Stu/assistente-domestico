import json
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import ollama

from services.resilience_service import InvalidOrchestratorOutputException
from services.logger_service import logger as custom_logger


class BaseLLMProvider(ABC):
    """
    Interface abstrata para provedores de LLM (Local e Nuvem).
    Garante um contrato único para geração de texto puro e JSON estruturado.
    """

    @abstractmethod
    def gerar_texto(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Gera uma resposta em texto puro."""
        pass

    @abstractmethod
    def gerar_json(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Gera e retorna uma estrutura JSON/dicionário Python.
        Lança InvalidOrchestratorOutputException em caso de falha de parse/formato.
        """
        pass


class LocalLLMProvider(BaseLLMProvider):
    """
    Provedor de LLM Local utilizando Ollama (ex: Gemma 4).
    """

    def __init__(self, modelo: str = "gemma4:e4b", temperatura: float = 0.1):
        self.modelo = modelo
        self.temperatura = temperatura

    def _sanitizar_resposta_json(self, conteudo_bruto: str) -> str:
        """Remove marcações de código Markdown (```json ... ```) e limpa espaços extras."""
        conteudo = conteudo_bruto.strip()
        if conteudo.startswith("```"):
            linhas = conteudo.splitlines()
            if linhas[0].startswith("```"):
                linhas = linhas[1:]
            if linhas and linhas[-1].startswith("```"):
                linhas = linhas[:-1]
            conteudo = "\n".join(linhas).strip()
        return conteudo

    def _construir_mensagens(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None
    ) -> List[Dict[str, str]]:
        mensagens = [{"role": "system", "content": prompt_sistema}]
        if historico:
            mensagens.extend(historico)
        mensagens.append({"role": "user", "content": mensagem_usuario})
        return mensagens

    def gerar_texto(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None
    ) -> str:
        mensagens = self._construir_mensagens(prompt_sistema, mensagem_usuario, historico)
        
        cliente_ollama = ollama.Client(timeout=120.0)
        response = cliente_ollama.chat(
            model=self.modelo,
            messages=mensagens,
            options={"temperature": self.temperatura}
        )
        return response['message']['content'].strip()

    def gerar_json(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        mensagens = self._construir_mensagens(prompt_sistema, mensagem_usuario, historico)

        cliente_ollama = ollama.Client(timeout=120.0)
        response = cliente_ollama.chat(
            model=self.modelo,
            messages=mensagens,
            format="json",
            options={"temperature": self.temperatura}
        )

        conteudo_bruto = response['message']['content']
        conteudo_sanitizado = self._sanitizar_resposta_json(conteudo_bruto)

        try:
            dados = json.loads(conteudo_sanitizado)
            if not isinstance(dados, dict):
                raise InvalidOrchestratorOutputException("A resposta do modelo local não é um objeto JSON válido.")
            return dados
        except json.JSONDecodeError as e:
            msg = f"[LocalLLMProvider] Erro ao decodificar JSON retornado pelo Gemma: {e}"
            custom_logger.log_geral(msg)
            raise InvalidOrchestratorOutputException(msg) from e


class CloudLLMProvider(BaseLLMProvider):
    """
    Provedor de LLM na Nuvem utilizando a API do Gemini (via AIService).
    """

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    def _sanitizar_resposta_json(self, conteudo_bruto: str) -> str:
        conteudo = conteudo_bruto.strip()
        if conteudo.startswith("```"):
            linhas = conteudo.splitlines()
            if linhas[0].startswith("```"):
                linhas = linhas[1:]
            if linhas and linhas[-1].startswith("```"):
                linhas = linhas[:-1]
            conteudo = "\n".join(linhas).strip()
        return conteudo

    def gerar_texto(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None
    ) -> str:
        prompt_completo = f"Instrução de Sistema: {prompt_sistema}\n\nUsuário: {mensagem_usuario}"
        return self.ai_service.processar_requisicao_complexa(prompt_completo, historico or [])

    def gerar_json(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        prompt_orientado_json = (
            f"{prompt_sistema}\n\n"
            "ATENÇÃO: Retorne estritamente um JSON válido. Não adicione texto explicativo ou marcações fora do JSON."
        )
        prompt_completo = f"Instrução de Sistema: {prompt_orientado_json}\n\nUsuário: {mensagem_usuario}"

        resposta_bruta = self.ai_service.processar_requisicao_complexa(prompt_completo, historico or [])
        conteudo_sanitizado = self._sanitizar_resposta_json(resposta_bruta)

        try:
            dados = json.loads(conteudo_sanitizado)
            if not isinstance(dados, dict):
                raise InvalidOrchestratorOutputException("A resposta da nuvem não é um objeto JSON válido.")
            return dados
        except json.JSONDecodeError as e:
            msg = f"[CloudLLMProvider] Erro ao decodificar JSON retornado pelo Gemini: {e}"
            custom_logger.log_geral(msg)
            raise InvalidOrchestratorOutputException(msg) from e