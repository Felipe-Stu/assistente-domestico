import json
import threading
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import ollama

from services.resilience_service import InvalidOrchestratorOutputException
from services.logger_service import logger as custom_logger

# Nomes dos Modelos Ollama Locais
MODELO_PADRAO = "gemma4:e4b"
MODELO_AVANCADO = "qwen2.5-coder:7b"

# Estado do Sistema em Memória
MODO_QWEN_ATIVO = False
ULTIMA_ATIVIDADE_TIMESTAMP = time.time()
TEMPO_TIMEOUT_INATIVIDADE = 1800  # 30 minutos em segundos (para o estado geral do sistema)


def _atualizar_timestamp_atividade() -> None:
    """Atualiza o registro de atividade humana no sistema."""
    global ULTIMA_ATIVIDADE_TIMESTAMP
    ULTIMA_ATIVIDADE_TIMESTAMP = time.time()


def alternar_modelo_vram(modelo_para_descarregar: str) -> None:
    """
    Instrui o Ollama a liberar a VRAM/RAM do modelo que deixará de ser utilizado
    enviando uma chamada leve com keep_alive=0.
    """
    try:
        cliente = ollama.Client(timeout=10.0)
        cliente.chat(model=modelo_para_descarregar, messages=[], keep_alive=0)
        custom_logger.log_geral(f"[LLMService] Modelo '{modelo_para_descarregar}' descarregado da VRAM.")
    except Exception as e:
        custom_logger.log_geral(f"[LLMService] Alerta ao descarregar modelo '{modelo_para_descarregar}': {e}")


def pre_carregar_modelo_background(modelo: str, keep_alive: str = "10m") -> None:
    """
    Dispara o carregamento do modelo para a VRAM em uma Thread separada.
    O Ollama manterá o modelo carregado na VRAM pelo tempo estipulado em 'keep_alive'.
    Se não for utilizado dentro desse prazo, o próprio Ollama o descartará automaticamente.
    """
    def _warmup():
        try:
            custom_logger.log_geral(f"[LLMService] 🔥 [Warmup] Pré-carregando '{modelo}' na VRAM (keep_alive={keep_alive})...")
            cliente = ollama.Client(timeout=60.0)
            # Envia chamada vazia com o parâmetro keep_alive para forçar a alocação na VRAM
            cliente.chat(model=modelo, messages=[], keep_alive=keep_alive)
            custom_logger.log_geral(f"[LLMService] ✅ [Warmup] Modelo '{modelo}' pré-carregado e pronto para uso!")
        except Exception as e:
            custom_logger.log_geral(f"[LLMService] ⚠️ [Warmup] Falha ao pré-carregar '{modelo}': {e}")

    thread = threading.Thread(target=_warmup, daemon=True)
    thread.start()


def ativar_modo_qwen() -> None:
    """
    Ativa o Modo Qwen, descarrega o Gemma 4 da VRAM e dispara 
    o pré-carregamento do Qwen em background com timeout de 10 minutos.
    """
    global MODO_QWEN_ATIVO
    if not MODO_QWEN_ATIVO:
        alternar_modelo_vram(MODELO_PADRAO)
        MODO_QWEN_ATIVO = True
        
        # Dispara o pré-carregamento assíncrono com retenção de 10 minutos
        pre_carregar_modelo_background(MODELO_AVANCADO, keep_alive="10m")
        
        custom_logger.log_geral("[LLMService] Modo QWEN ATIVADO. Qwen 2.5 7B assume a responsabilidade de execução.")


def desativar_modo_qwen() -> None:
    """Desativa o Modo Qwen, descarrega a GPU e retorna ao Gemma 4."""
    global MODO_QWEN_ATIVO
    if MODO_QWEN_ATIVO:
        alternar_modelo_vram(MODELO_AVANCADO)
        MODO_QWEN_ATIVO = False
        custom_logger.log_geral("[LLMService] Modo QWEN DESATIVADO. Retornando ao Gemma 4.")


def verificar_e_gestionar_timeout_inatividade() -> None:
    """
    Verifica se o computador ficou sem atividade humana por mais de 30 minutos.
    Se sim, desativa o Modo Qwen e libera a memória da GPU.
    """
    global MODO_QWEN_ATIVO
    if MODO_QWEN_ATIVO:
        tempo_decorrido = time.time() - ULTIMA_ATIVIDADE_TIMESTAMP
        if tempo_decorrido > TEMPO_TIMEOUT_INATIVIDADE:
            custom_logger.log_geral("[LLMService] Inatividade de 30m detectada. Desativando QWEN.")
            desativar_modo_qwen()


def obter_modelo_ativo() -> str:
    """Retorna qual modelo Ollama deve responder no momento."""
    verificar_e_gestionar_timeout_inatividade()
    return MODELO_AVANCADO if MODO_QWEN_ATIVO else MODELO_PADRAO


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
    Provedor de LLM Local utilizando Ollama (Gemma 4 ou Qwen 2.5 7B).
    """

    def __init__(self, modelo: Optional[str] = None, temperatura: float = 0.1):
        self.modelo = modelo or obter_modelo_ativo()
        self.temperatura = temperatura

    def pre_carregar_modelo(self, tempo_keep_alive: str = "10m") -> None:
        """Permite invocar explicitamente o pré-carregamento do modelo associado a esta instância."""
        pre_carregar_modelo_background(self.modelo, keep_alive=tempo_keep_alive)

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
        _atualizar_timestamp_atividade()
        mensagens = self._construir_mensagens(prompt_sistema, mensagem_usuario, historico)
        
        cliente_ollama = ollama.Client(timeout=120.0)
        response = cliente_ollama.chat(
            model=self.modelo,
            messages=mensagens,
            keep_alive="30m",
            options={"temperature": self.temperatura}
        )
        return response['message']['content'].strip()

    def gerar_json(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        _atualizar_timestamp_atividade()
        mensagens = self._construir_mensagens(prompt_sistema, mensagem_usuario, historico)

        cliente_ollama = ollama.Client(timeout=120.0)
        response = cliente_ollama.chat(
            model=self.modelo,
            messages=mensagens,
            format="json",
            keep_alive="30m",
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
            msg = f"[LocalLLMProvider] Erro ao decodificar JSON retornado pelo modelo ({self.modelo}): {e}"
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
        _atualizar_timestamp_atividade()
        prompt_completo = f"Instrução de Sistema: {prompt_sistema}\n\nUsuário: {mensagem_usuario}"
        return self.ai_service.processar_requisicao_complexa(prompt_completo, historico or [])

    def gerar_json(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        _atualizar_timestamp_atividade()
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


def obter_provedor_local(temperatura: float = 0.1) -> LocalLLMProvider:
    """Instancia dinamicamente o provedor local utilizando a IA atualmente ativa."""
    modelo_atual = obter_modelo_ativo()
    return LocalLLMProvider(modelo=modelo_atual, temperatura=temperatura)