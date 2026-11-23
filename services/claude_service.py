"""
Cliente do Claude (API da Anthropic) para a skill de programação (SKP).

- Sem chave configurada, o serviço fica desligado e o Qwen local responde.
- Cota esgotada, teto de gasto ou problema de cobrança/chave: o Claude fica indisponível até a
  primeira solicitação depois de CLAUDE_HORA_RETESTE (8h) do dia seguinte; com `retry-after`
  (limite de taxa), até o horário indicado.
- Falha passageira (sobrecarga, timeout, rede): só esta solicitação vai para o Qwen.
- O gasto do mês é estimado pelos tokens de cada resposta; ao passar de CLAUDE_LIMITE_MENSAL_USD,
  o Claude fica indisponível até o mês seguinte.

O estado fica em core/database/estado_claude.json (ignorado pelo Git). Nenhuma chave é registrada.

Erros conforme https://platform.claude.com/docs/en/api/errors
"""
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

from services.logger_service import logger as custom_logger

URL_MENSAGENS = "https://api.anthropic.com/v1/messages"
COMPONENTE = "claude"


class ClaudeIndisponivelError(Exception):
    """O Claude não pode responder agora; `motivo` é uma frase para o usuário."""

    def __init__(self, motivo: str, ate: Optional[datetime] = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.ate = ate


def proxima_manha(agora: datetime, hora: int) -> datetime:
    """Próximo horário de reteste: hoje às `hora`, se ainda não passou; senão, amanhã."""
    hoje = agora.replace(hour=hora, minute=0, second=0, microsecond=0)
    return hoje if agora < hoje else hoje + timedelta(days=1)


def _primeiro_dia_do_mes_seguinte(agora: datetime, hora: int) -> datetime:
    ano, mes = (agora.year + 1, 1) if agora.month == 12 else (agora.year, agora.month + 1)
    return datetime(ano, mes, 1, hora)


class ClaudeService:
    def __init__(
        self,
        api_key: str,
        modelo: str,
        versao_api: str,
        arquivo_estado: Path,
        limite_mensal_usd: float = 5.0,
        preco_entrada: float = 2.0,
        preco_saida: float = 10.0,
        hora_reteste: int = 8,
        max_tokens: int = 4096,
        agora: Callable[[], datetime] = datetime.now,
        post: Callable = requests.post,
        timeout: float = 120.0,
    ):
        self._api_key = api_key or ""
        self.modelo = modelo
        self.versao_api = versao_api
        self.arquivo_estado = Path(arquivo_estado)
        self.limite_mensal_usd = limite_mensal_usd
        self.preco_entrada = preco_entrada
        self.preco_saida = preco_saida
        self.hora_reteste = hora_reteste
        self.max_tokens = max_tokens
        self._agora = agora
        self._post = post
        self.timeout = timeout
        self._trava = threading.Lock()

    # ------------------------------------------------------------------
    # Estado (disponibilidade e gasto do mês)
    # ------------------------------------------------------------------

    def configurado(self) -> bool:
        return bool(self._api_key)

    def _ler_estado(self) -> Dict:
        try:
            dados = json.loads(self.arquivo_estado.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        mes = self._agora().strftime("%Y-%m")
        if dados.get("mes") != mes:
            dados.update({"mes": mes, "gasto_usd": 0.0, "tokens_entrada": 0, "tokens_saida": 0})
        return dados

    def _gravar_estado(self, dados: Dict) -> None:
        self.arquivo_estado.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo_estado.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    def estado(self) -> Dict:
        with self._trava:
            return self._ler_estado()

    def _marcar_indisponivel(self, motivo: str, ate: datetime) -> ClaudeIndisponivelError:
        with self._trava:
            dados = self._ler_estado()
            dados.update({"indisponivel_ate": ate.isoformat(timespec="minutes"), "motivo": motivo})
            self._gravar_estado(dados)
        custom_logger.evento(COMPONENTE, "indisponivel", motivo, nivel="WARNING", ate=ate.isoformat(timespec="minutes"))
        return ClaudeIndisponivelError(motivo, ate)

    def verificar_disponibilidade(self) -> None:
        """Lança ClaudeIndisponivelError se não for hora de tentar o Claude."""
        if not self.configurado():
            raise ClaudeIndisponivelError("Claude não configurado (sem ANTHROPIC_API_KEY no .env)")
        with self._trava:
            dados = self._ler_estado()
            ate = dados.get("indisponivel_ate")
            if ate and self._agora() < datetime.fromisoformat(ate):
                raise ClaudeIndisponivelError(f"{dados.get('motivo', 'Claude indisponível')} (volta a ser testado em {_formatar(ate)})",
                                              datetime.fromisoformat(ate))
            if ate:
                dados.pop("indisponivel_ate", None)
                dados.pop("motivo", None)
                self._gravar_estado(dados)
            if dados.get("gasto_usd", 0.0) >= self.limite_mensal_usd > 0:
                fim = _primeiro_dia_do_mes_seguinte(self._agora(), self.hora_reteste)
                motivo = f"limite mensal de US$ {self.limite_mensal_usd:.2f} atingido"
                dados.update({"indisponivel_ate": fim.isoformat(timespec="minutes"), "motivo": motivo})
                self._gravar_estado(dados)
                raise ClaudeIndisponivelError(f"{motivo} (volta em {_formatar(fim.isoformat())})", fim)

    def _registrar_uso(self, uso: Dict) -> float:
        entrada, saida = int(uso.get("input_tokens") or 0), int(uso.get("output_tokens") or 0)
        custo = (entrada * self.preco_entrada + saida * self.preco_saida) / 1_000_000
        with self._trava:
            dados = self._ler_estado()
            dados["tokens_entrada"] = dados.get("tokens_entrada", 0) + entrada
            dados["tokens_saida"] = dados.get("tokens_saida", 0) + saida
            dados["gasto_usd"] = round(dados.get("gasto_usd", 0.0) + custo, 6)
            self._gravar_estado(dados)
        return custo

    # ------------------------------------------------------------------
    # Chamada
    # ------------------------------------------------------------------

    @staticmethod
    def _mensagens(historico: Optional[List[Dict[str, str]]], mensagem_usuario: str) -> List[Dict[str, str]]:
        """A API exige papéis user/assistant alternados, começando pelo usuário."""
        mensagens: List[Dict[str, str]] = []
        for item in historico or []:
            papel, conteudo = item.get("role"), item.get("content")
            if papel not in ("user", "assistant") or not conteudo:
                continue
            if not mensagens and papel != "user":
                continue
            if mensagens and mensagens[-1]["role"] == papel:
                mensagens[-1]["content"] += "\n\n" + conteudo
            else:
                mensagens.append({"role": papel, "content": conteudo})
        if mensagens and mensagens[-1]["role"] == "user":
            mensagens[-1]["content"] += "\n\n" + mensagem_usuario
        else:
            mensagens.append({"role": "user", "content": mensagem_usuario})
        return mensagens

    def gerar_texto(self, prompt_sistema: str, mensagem_usuario: str,
                    historico: Optional[List[Dict[str, str]]] = None, max_tokens: Optional[int] = None) -> str:
        self.verificar_disponibilidade()
        corpo = {
            "model": self.modelo,
            "max_tokens": max_tokens or self.max_tokens,
            "system": prompt_sistema,
            "messages": self._mensagens(historico, mensagem_usuario),
        }
        cabecalhos = {"x-api-key": self._api_key, "anthropic-version": self.versao_api, "content-type": "application/json"}
        with custom_logger.etapa("claude", componente=COMPONENTE, modelo=self.modelo):
            try:
                resposta = self._post(URL_MENSAGENS, headers=cabecalhos, json=corpo, timeout=self.timeout)
            except requests.RequestException as erro:
                raise ClaudeIndisponivelError(f"falha de conexão com o Claude ({type(erro).__name__})") from erro
        if resposta.status_code == 200:
            dados = resposta.json()
            custo = self._registrar_uso(dados.get("usage") or {})
            custom_logger.evento(COMPONENTE, "resposta", custo_usd=round(custo, 6), **(dados.get("usage") or {}))
            return "".join(b.get("text", "") for b in dados.get("content", []) if b.get("type") == "text").strip()
        raise self._erro(resposta)

    def _erro(self, resposta) -> ClaudeIndisponivelError:
        try:
            erro = (resposta.json() or {}).get("error") or {}
        except ValueError:
            erro = {}
        tipo, mensagem = erro.get("type", ""), (erro.get("message") or "")
        status = resposta.status_code
        manha = proxima_manha(self._agora(), self.hora_reteste)
        retry_after = resposta.headers.get("retry-after") if hasattr(resposta, "headers") else None

        if status == 429 and retry_after:
            try:
                ate = self._agora() + timedelta(seconds=float(retry_after))
            except ValueError:
                ate = manha
            return self._marcar_indisponivel("limite de uso do Claude atingido", ate)
        if status == 429:
            return self._marcar_indisponivel("cota ou teto de gasto do Claude atingido", manha)
        if status == 402:
            return self._marcar_indisponivel("problema de cobrança na conta do Claude", manha)
        if status in (401, 403):
            return self._marcar_indisponivel("chave do Claude recusada (confira ANTHROPIC_API_KEY)", manha)
        if status == 400 and any(p in mensagem.lower() for p in ("spend", "limit", "credit", "billing", "balance")):
            return self._marcar_indisponivel("limite de gasto do Claude atingido", manha)
        # Sobrecarga, timeout, erro interno ou pedido inválido: só esta solicitação vai para o Qwen
        custom_logger.evento(COMPONENTE, "falha", mensagem[:200], nivel="WARNING", status=status, tipo=tipo)
        return ClaudeIndisponivelError(f"Claude não respondeu (HTTP {status})")


def _formatar(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except ValueError:
        return iso
