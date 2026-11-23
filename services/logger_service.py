"""
Registro de eventos estruturado (M26).

Cada evento vira uma linha JSON em Logs/eventos-AAAA-MM-DD.jsonl, com:
- ts, nivel, componente, evento e mensagem;
- req: identificador da requisição em andamento (quando houver);
- campos extras, como etapa e duracao_ms.

Usa o `logging` padrão. A rotação é por arquivo diário, sem renomear arquivos:
no Windows, renomear um log aberto por outro processo (um script rodando junto
com o app) falha, enquanto acrescentar linhas ao arquivo do dia funciona.
Arquivos mais antigos que LOG_RETENCAO_DIAS são apagados uma vez por dia.

A API antiga (log_geral e log_assistente) continua valendo para os módulos existentes.
"""
import contextvars
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from core.config import LOG_CONTEUDO, LOG_RETENCAO_DIAS, LOGS_DIR

LOGS_BASE_DIR = str(LOGS_DIR)
PREFIXO_ARQUIVO = "eventos-"
EXTENSAO_ARQUIVO = ".jsonl"

# Requisição em andamento na thread atual (cada thread nova começa sem requisição)
_requisicao_atual = contextvars.ContextVar("requisicao_atual", default=None)

# Chamadas antigas não informam o nível; estas palavras indicam erro
_PALAVRAS_DE_ERRO = ("erro", "falha", "falhou", "exception", "exceção", "rollback")


def nome_arquivo_do_dia(dia: datetime) -> str:
    return f"{PREFIXO_ARQUIVO}{dia.strftime('%Y-%m-%d')}{EXTENSAO_ARQUIVO}"


class FormatadorJson(logging.Formatter):
    """Uma linha JSON por evento, com os campos fixos primeiro."""

    def format(self, record: logging.LogRecord) -> str:
        evento = {
            "ts": datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
        }
        req = getattr(record, "req", None)
        if req:
            evento["req"] = req
        evento["componente"] = getattr(record, "componente", record.name)
        evento["evento"] = getattr(record, "evento", "mensagem")
        mensagem = record.getMessage()
        if mensagem:
            evento["mensagem"] = mensagem
        for chave, valor in (getattr(record, "campos", None) or {}).items():
            evento.setdefault(chave, valor)
        if record.exc_info:
            evento["erro"] = self.formatException(record.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=str)


class ArquivoDiarioHandler(logging.Handler):
    """Acrescenta cada evento ao arquivo do dia e apaga os arquivos vencidos."""

    def __init__(self, obter_pasta, retencao_dias: int):
        super().__init__()
        self.obter_pasta = obter_pasta
        self.retencao_dias = retencao_dias
        self._limpezas_feitas = set()

    def emit(self, record: logging.LogRecord):
        try:
            pasta = self.obter_pasta()
            os.makedirs(pasta, exist_ok=True)
            agora = datetime.now()
            linha = self.format(record)
            with open(os.path.join(pasta, nome_arquivo_do_dia(agora)), "a", encoding="utf-8") as arquivo:
                arquivo.write(linha + "\n")
            self._apagar_vencidos(pasta, agora)
        except Exception:
            self.handleError(record)

    def _apagar_vencidos(self, pasta: str, agora: datetime):
        chave = (pasta, agora.date())
        if chave in self._limpezas_feitas or self.retencao_dias <= 0:
            return
        self._limpezas_feitas.add(chave)
        limite = nome_arquivo_do_dia(agora - timedelta(days=self.retencao_dias))
        for nome in os.listdir(pasta):
            # O nome traz a data em ordem ano-mês-dia: comparar texto equivale a comparar datas
            if nome.startswith(PREFIXO_ARQUIVO) and nome.endswith(EXTENSAO_ARQUIVO) and nome < limite:
                try:
                    os.remove(os.path.join(pasta, nome))
                except OSError:
                    pass  # Outro processo pode estar com o arquivo aberto; tenta de novo amanhã


class _FiltroRequisicao(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "req", None):
            record.req = _requisicao_atual.get()
        return True


class CustomLogger:
    def __init__(self, base_dir: str = LOGS_BASE_DIR, nome: str = "assistente.eventos"):
        self.base_dir = base_dir
        self._logger = logging.getLogger(nome)
        self._logger.setLevel(logging.DEBUG)
        # Os eventos vão só para o arquivo; o terminal continua com o logging de cada módulo
        self._logger.propagate = False
        for handler in list(self._logger.handlers):
            self._logger.removeHandler(handler)
        handler = ArquivoDiarioHandler(lambda: self.base_dir, LOG_RETENCAO_DIAS)
        handler.setFormatter(FormatadorJson())
        handler.addFilter(_FiltroRequisicao())
        self._logger.addHandler(handler)

    # ------------------------------------------------------------------
    # API estruturada
    # ------------------------------------------------------------------

    def evento(self, componente: str, evento: str, mensagem: str = "", nivel: str = "INFO", **campos):
        """Registra um evento com campos livres (ex.: evento("backup", "gravado", bytes=123))."""
        self._logger.log(
            logging.getLevelName(nivel.upper()) if isinstance(nivel, str) else nivel,
            mensagem,
            extra={"componente": componente, "evento": evento, "campos": campos},
        )

    @contextmanager
    def requisicao(self, canal: str = "texto", **campos):
        """
        Abre uma requisição: todos os eventos registrados dentro do bloco, nesta thread,
        recebem o mesmo `req`. Registra o início e o fim com a duração total.
        """
        req_id = uuid.uuid4().hex[:8]
        token = _requisicao_atual.set(req_id)
        inicio = time.perf_counter()
        self.evento("main", "requisicao_inicio", canal=canal, **campos)
        try:
            yield req_id
        except BaseException as erro:
            self.evento("main", "requisicao_fim", nivel="ERROR", status="erro",
                        erro_tipo=type(erro).__name__, duracao_ms=_ms_desde(inicio))
            raise
        else:
            self.evento("main", "requisicao_fim", status="ok", duracao_ms=_ms_desde(inicio))
        finally:
            _requisicao_atual.reset(token)

    @contextmanager
    def etapa(self, nome: str, componente: str = "main", **campos):
        """Mede uma etapa (roteamento, extração, banco, voz...) e registra a duração e o resultado."""
        inicio = time.perf_counter()
        try:
            yield
        except BaseException as erro:
            self.evento(componente, "etapa", nivel="WARNING", etapa=nome, status="erro",
                        erro_tipo=type(erro).__name__, duracao_ms=_ms_desde(inicio), **campos)
            raise
        else:
            self.evento(componente, "etapa", etapa=nome, status="ok", duracao_ms=_ms_desde(inicio), **campos)

    def cronometrado(self, nome: str, func, componente: str = "main"):
        """Envolve `func` para medir cada chamada como etapa (útil dentro de execute_with_retry)."""
        def _medida(*args, **kwargs):
            with self.etapa(nome, componente=componente):
                return func(*args, **kwargs)
        _medida.__name__ = getattr(func, "__name__", nome)
        return _medida

    @staticmethod
    def conteudo(texto) -> str:
        """Texto do usuário para o log: inteiro, ou só o tamanho quando LOG_CONTEUDO=0."""
        texto = "" if texto is None else str(texto)
        return texto if LOG_CONTEUDO else f"[omitido: {len(texto)} caracteres]"

    @staticmethod
    def id_requisicao():
        return _requisicao_atual.get()

    # ------------------------------------------------------------------
    # API antiga (mantida para os módulos existentes)
    # ------------------------------------------------------------------

    def log_geral(self, mensagem: str):
        self.evento("main", "mensagem", mensagem, nivel=_nivel_por_texto(mensagem))

    def log_assistente(self, nome_assistente: str, mensagem: str):
        # Normaliza o nome do componente (ex.: "Controle de Consumo" -> "controle_de_consumo")
        componente = nome_assistente.lower().replace(" ", "_")
        self.evento(componente, "mensagem", mensagem, nivel=_nivel_por_texto(mensagem))


def _ms_desde(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)


def _nivel_por_texto(mensagem: str) -> str:
    texto = (mensagem or "").lower()
    return "ERROR" if any(palavra in texto for palavra in _PALAVRAS_DE_ERRO) else "INFO"


# Instância global pronta para importação
logger = CustomLogger()
