import time
import json
import re
from typing import Callable, Any, Tuple, Type
from services.logger_service import logger as custom_logger


class ResilienceException(Exception):
    """Exceção base para falhas de resiliência no sistema."""
    pass


class MaxRetriesExceededException(ResilienceException):
    """Lançada quando todas as tentativas do retry são esgotadas."""
    pass


class InvalidOrchestratorOutputException(ResilienceException):
    """Lançada quando a resposta do Orquestrador não respeita o schema esperado."""
    pass


class OllamaIndisponivelException(ResilienceException, ConnectionError):
    """
    O servidor do Ollama não respondeu (fechado ou inacessível). Repetir a chamada não resolve:
    quem usa execute_with_retry deve tratá-la como fatal e pedir ao usuário que abra o Ollama.
    """
    pass


def parse_json_com_fallback(texto_llm: str) -> dict:
    """
    Tenta decodificar o JSON recebido da LLM local.
    Se falhar, aplica regras de higienização Regex e tenta novamente.
    Caso persista, lança ValueError para acionar o Fallback de nuvem.
    """
    texto_limpo = texto_llm.strip()
    
    # 1. Tentativa de Parse Direto
    try:
        return json.loads(texto_limpo)
    except json.JSONDecodeError:
        custom_logger.log_geral("[Resilience] JSON direto falhou. Iniciando higienização...")

    # 2. Higienização: Remove blocos ```json ... ``` e pega apenas o conteúdo entre { e }
    match = re.search(r'\{.*\}', texto_limpo, re.DOTALL)
    if match:
        json_extraido = match.group(0)
        try:
            dados = json.loads(json_extraido)
            custom_logger.log_geral("[Resilience] JSON recuperado com sucesso após higienização por Regex.")
            return dados
        except json.JSONDecodeError as e:
            custom_logger.log_geral(f"[Resilience] Falha ao decodificar JSON mesmo após Regex: {e}")

    # 3. Se todas as tentativas locais falharem
    custom_logger.log_geral("[Resilience] Falha crítica de parsing no JSON local. Disparando exceção de fallback.")
    raise ValueError("INVALID_JSON_LOCAL")


def execute_with_retry(
    func: Callable,
    args: Tuple = (),
    kwargs: dict = None,
    max_tentativas: int = 3,
    tempo_espera: float = 2.0,
    excecoes_recuperaveis: Tuple[Type[Exception], ...] = (Exception,),
    excecoes_fatais: Tuple[Type[Exception], ...] = (),
    voice_service: Any = None,
    mensagem_espera_voz: str = "Aguarde um instante, estou reprocessando sua solicitação.",
    callback_validacao: Callable[[Any], None] = None,
    nome_servico: str = "Serviço IA"
) -> Any:
    """
    Executa uma função seguindo um padrão único e controlado de retry.
    Garante limite de tentativas, validação de schema, logs e alerta por voz em re-tentativas.
    """
    if kwargs is None:
        kwargs = {}

    for tentativa in range(1, max_tentativas + 1):
        try:
            # Emite aviso sonoro apenas a partir da 2ª tentativa (reprocessamento)
            if tentativa > 1 and voice_service and mensagem_espera_voz:
                custom_logger.log_geral(f"[{nome_servico}] Disparando aviso de voz: '{mensagem_espera_voz}' (Tentativa {tentativa}/{max_tentativas}).")
                try:
                    voice_service.falar(mensagem_espera_voz)
                except Exception as e_voz:
                    custom_logger.log_geral(f"[{nome_servico}] Erro ao emitir aviso de voz: {e_voz}")

            custom_logger.log_geral(f"[{nome_servico}] Executando chamada (Tentativa {tentativa}/{max_tentativas})...")
            
            resultado = func(*args, **kwargs)

            # Executa validação estrutural do retorno, se houver callback
            if callback_validacao:
                callback_validacao(resultado)

            custom_logger.log_geral(f"[{nome_servico}] Chamada executada com sucesso na tentativa {tentativa}.")
            return resultado

        except excecoes_fatais:
            # Novas tentativas não resolvem (ex.: cota esgotada)
            raise

        except excecoes_recuperaveis as e:
            import traceback
            tb_str = traceback.format_exc()
            msg_erro = f"[{nome_servico}] Falha na tentativa {tentativa}/{max_tentativas}: {e}\nTraceback:\n{tb_str}"
            custom_logger.log_geral(msg_erro)

            if tentativa == max_tentativas:
                msg_esgotado = f"[{nome_servico}] Limite máximo de {max_tentativas} tentativas atingido sem sucesso."
                custom_logger.log_geral(msg_esgotado)
                raise MaxRetriesExceededException(msg_esgotado) from e

            time.sleep(tempo_espera)

    raise MaxRetriesExceededException(f"[{nome_servico}] Falha inesperada ao esgotar retries.")