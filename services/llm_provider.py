import json
import threading
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import ollama

try:
    import httpx  # dependência do pacote ollama
    _ERROS_CONEXAO = (ConnectionError, httpx.ConnectError, httpx.ConnectTimeout)
except ImportError:  # pragma: no cover
    _ERROS_CONEXAO = (ConnectionError,)

from core.config import (
    OLLAMA_KEEP_ALIVE,
    OLLAMA_MODELO_AVANCADO,
    OLLAMA_MODELO_PADRAO,
    OLLAMA_RACIOCINIO,
    OLLAMA_SAIDA_ESTRUTURADA,
    OLLAMA_TIMEOUT,
)
from services.resilience_service import InvalidOrchestratorOutputException, OllamaIndisponivelException
from services.logger_service import logger as custom_logger

# Nomes dos modelos Ollama locais (configuráveis no .env, M27)
MODELO_PADRAO = OLLAMA_MODELO_PADRAO
MODELO_AVANCADO = OLLAMA_MODELO_AVANCADO

# Estado do Sistema em Memória
MODO_QWEN_ATIVO = False

# Verificação de saúde do Ollama (M17): /api/tags com timeout curto antes de chamar o modelo.
# Um resultado positivo vale por SAUDE_VALIDADE_S para não somar uma requisição a cada mensagem.
OLLAMA_TIMEOUT_SAUDE = 2.0
SAUDE_VALIDADE_S = 30.0
_saude_ok_ate = 0.0

# Métricas da última chamada gerar_json (tokens e tempos informados pelo Ollama); usadas pelas medições
ULTIMA_CHAMADA: Dict[str, Any] = {}
ULTIMA_ATIVIDADE_TIMESTAMP = time.time()
TEMPO_TIMEOUT_INATIVIDADE = 1800  # 30 minutos em segundos (para o estado geral do sistema)


def verificar_ollama(timeout: float = OLLAMA_TIMEOUT_SAUDE) -> Optional[str]:
    """Consulta a lista de modelos do Ollama (/api/tags). Devolve None se respondeu, ou a descrição do erro."""
    try:
        ollama.Client(timeout=timeout).list()
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def invalidar_saude_ollama() -> None:
    """Força nova verificação na próxima chamada (ex.: após erro de conexão)."""
    global _saude_ok_ate
    _saude_ok_ate = 0.0


def garantir_ollama_disponivel() -> None:
    """Lança OllamaIndisponivelException em até OLLAMA_TIMEOUT_SAUDE segundos se o Ollama não responder."""
    global _saude_ok_ate
    agora = time.monotonic()
    if agora < _saude_ok_ate:
        return
    erro = verificar_ollama()
    if erro:
        _saude_ok_ate = 0.0
        custom_logger.log_geral(f"[LLMService] Ollama indisponível na verificação de saúde: {erro}")
        raise OllamaIndisponivelException(f"O Ollama não respondeu em {OLLAMA_TIMEOUT_SAUDE:.0f} s ({erro}).")
    _saude_ok_ate = agora + SAUDE_VALIDADE_S


def _converter_erro_conexao(e: Exception) -> OllamaIndisponivelException:
    invalidar_saude_ollama()
    return OllamaIndisponivelException(f"Conexão com o Ollama perdida ({type(e).__name__}: {e}).")


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
        historico: Optional[List[Dict[str, str]]] = None,
        esquema: Optional[Dict[str, Any]] = None,
        raciocinio: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Gera e retorna uma estrutura JSON/dicionário Python.
        esquema: JSON Schema opcional que restringe a resposta (usado pelos provedores que o suportam).
        raciocinio: liga/desliga o raciocínio ("think") nos provedores que o suportam. OLLAMA_RACIOCINIO
                    no .env, quando preenchido, prevalece (permite medir e reverter sem alterar o código).
        Lança InvalidOrchestratorOutputException em caso de falha de parse/formato.
        """
        pass


def _metricas_resposta(response, modelo: str, think) -> Dict[str, Any]:
    """Extrai do retorno do Ollama os tokens e tempos (durações em nanossegundos viram segundos)."""
    def campo(nome):
        try:
            return response[nome]
        except Exception:
            return getattr(response, nome, None)

    def segundos(nome):
        valor = campo(nome)
        return round(valor / 1e9, 2) if valor else None

    try:
        mensagem = response["message"]
        pensamento = mensagem.get("thinking") if isinstance(mensagem, dict) else getattr(mensagem, "thinking", None)
    except Exception:
        pensamento = None
    return {
        "modelo": modelo,
        "think": think,
        "tokens_prompt": campo("prompt_eval_count"),
        "tokens_gerados": campo("eval_count"),
        "s_carga": segundos("load_duration"),
        "s_prompt": segundos("prompt_eval_duration"),
        "s_geracao": segundos("eval_duration"),
        "s_total": segundos("total_duration"),
        "chars_raciocinio": len(pensamento or ""),
    }


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
        garantir_ollama_disponivel()
        mensagens = self._construir_mensagens(prompt_sistema, mensagem_usuario, historico)

        cliente_ollama = ollama.Client(timeout=OLLAMA_TIMEOUT)
        try:
            response = cliente_ollama.chat(
                model=self.modelo,
                messages=mensagens,
                keep_alive=OLLAMA_KEEP_ALIVE,
                options={"temperature": self.temperatura}
            )
        except _ERROS_CONEXAO as e:
            raise _converter_erro_conexao(e) from e
        return response['message']['content'].strip()

    def gerar_texto_imagem(self, prompt_sistema: str, mensagem_usuario: str, imagens: List[Any],
                           max_tokens: int = 1500) -> str:
        """Texto livre sobre imagens (bytes ou caminhos). M34: limite de tokens e penalidade de repetição
        evitam o laço "C/C/C/..." visto no gemma3:4b em letra miúda."""
        _atualizar_timestamp_atividade()
        garantir_ollama_disponivel()
        cliente_ollama = ollama.Client(timeout=OLLAMA_TIMEOUT * 2)
        try:
            response = cliente_ollama.chat(
                model=self.modelo,
                messages=[{"role": "system", "content": prompt_sistema},
                          {"role": "user", "content": mensagem_usuario, "images": list(imagens)}],
                keep_alive=OLLAMA_KEEP_ALIVE,
                options={"temperature": self.temperatura, "num_predict": max_tokens, "repeat_penalty": 1.15},
            )
        except _ERROS_CONEXAO as e:
            raise _converter_erro_conexao(e) from e
        return response['message']['content'].strip()

    def gerar_json_imagem(self, prompt_sistema: str, mensagem_usuario: str, imagens: List[str],
                          esquema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Como gerar_json, com imagens (caminhos) anexadas à mensagem; o modelo precisa entender imagem."""
        _atualizar_timestamp_atividade()
        garantir_ollama_disponivel()
        cliente_ollama = ollama.Client(timeout=OLLAMA_TIMEOUT * 2)
        parametros = {
            "model": self.modelo,
            "messages": [{"role": "system", "content": prompt_sistema},
                         {"role": "user", "content": mensagem_usuario, "images": list(imagens)}],
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": self.temperatura},
            "format": esquema if (esquema and OLLAMA_SAIDA_ESTRUTURADA) else "json",
        }
        try:
            response = cliente_ollama.chat(**parametros)
        except _ERROS_CONEXAO as e:
            raise _converter_erro_conexao(e) from e
        conteudo = response['message']['content']
        try:
            return json.loads(self._sanitizar_resposta_json(conteudo))
        except ValueError as e:
            raise InvalidOrchestratorOutputException(f"Resposta da imagem não é JSON: {e}") from e

    def gerar_json(
        self,
        prompt_sistema: str,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, str]]] = None,
        esquema: Optional[Dict[str, Any]] = None,
        raciocinio: Optional[bool] = None
    ) -> Dict[str, Any]:
        _atualizar_timestamp_atividade()
        garantir_ollama_disponivel()
        mensagens = self._construir_mensagens(prompt_sistema, mensagem_usuario, historico)

        cliente_ollama = ollama.Client(timeout=OLLAMA_TIMEOUT)
        parametros = {
            "model": self.modelo,
            "messages": mensagens,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": self.temperatura},
        }
        think = OLLAMA_RACIOCINIO if OLLAMA_RACIOCINIO is not None else raciocinio
        if think is not None:
            parametros["think"] = think

        def _chamar(formato):
            try:
                return cliente_ollama.chat(format=formato, **parametros)
            except _ERROS_CONEXAO as e:
                raise _converter_erro_conexao(e) from e
            except ollama.ResponseError as e:
                # Modelo sem suporte a raciocínio: repete sem o parâmetro "think"
                if "think" in parametros and "think" in str(e).lower():
                    custom_logger.log_geral(
                        f"[LocalLLMProvider] {self.modelo} não aceita 'think' ({e}). Repetindo sem o parâmetro."
                    )
                    parametros.pop("think")
                    return cliente_ollama.chat(format=formato, **parametros)
                raise

        usar_esquema = bool(esquema) and OLLAMA_SAIDA_ESTRUTURADA
        if usar_esquema:
            try:
                response = _chamar(esquema)
            except (TypeError, ValueError) as e:
                # Biblioteca ollama antiga (anterior à 0.4) não aceita esquema em `format`
                custom_logger.log_geral(
                    f"[LocalLLMProvider] Esquema JSON recusado pelo cliente Ollama ({e}). Usando format='json'."
                )
                response = _chamar("json")
        else:
            response = _chamar("json")

        ULTIMA_CHAMADA.clear()
        ULTIMA_CHAMADA.update(_metricas_resposta(response, self.modelo, parametros.get("think")))

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
        historico: Optional[List[Dict[str, str]]] = None,
        esquema: Optional[Dict[str, Any]] = None,
        raciocinio: Optional[bool] = None
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
