"""
Claude pela assinatura (Pro/Max): chama o Claude Code em modo não interativo (`claude -p`).

O gasto sai da cota do plano em que o Claude Code está logado (a mesma do chat), sem chave de API.
Mesma interface do ClaudeService (configurado, verificar_disponibilidade, gerar_texto), para que as
skills não saibam qual dos dois está em uso.

Segurança:
- Nenhuma ferramenta: `--tools ""` e `--disallowedTools mcp__*`. O Claude só devolve texto; não lê nem
  altera arquivos e não roda comandos.
- Roda numa pasta temporária vazia e sem gravar a sessão (`--no-session-persistence`).
- ANTHROPIC_API_KEY e ANTHROPIC_AUTH_TOKEN são retirados do ambiente do processo: com eles o
  Claude Code cobraria pela API em vez de usar a assinatura.

Disponibilidade:
- Claude Code não instalado: serviço desligado (a skill usa a reserva local).
- Sem login: indisponível até a manhã seguinte (CLAUDE_HORA_RETESTE).
- Limite de uso do plano: indisponível por CLAUDE_ASSINATURA_RETESTE_MIN minutos.
- Outras falhas (timeout, erro passageiro): só esta solicitação falha.

Referência: https://code.claude.com/docs/en/cli-reference
"""
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from services.claude_service import COMPONENTE, ClaudeIndisponivelError, ClaudeService, proxima_manha
from services.logger_service import logger as custom_logger

VARIAVEIS_RETIRADAS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
_SINAIS_LOGIN = ("/login", "not logged", "log in", "login", "authentication", "invalid api key", "oauth", "unauthorized")
_SINAIS_LIMITE = ("usage limit", "limit reached", "rate limit", "rate_limit", "quota", "resets at", "limite de uso")


def montar_conversa(historico: Optional[List[Dict[str, str]]], mensagem: str) -> str:
    """O `claude -p` recebe um texto só: o histórico vai como transcrição antes da mensagem atual."""
    linhas = []
    for item in historico or []:
        papel, conteudo = item.get("role"), (item.get("content") or "").strip()
        if papel in ("user", "assistant") and conteudo:
            linhas.append(f"{'Usuário' if papel == 'user' else 'Assistente'}: {conteudo}")
    if not linhas:
        return mensagem
    return "Conversa até aqui:\n\n" + "\n\n".join(linhas) + f"\n\nMensagem atual do usuário:\n\n{mensagem}"


class ClaudeAssinaturaService(ClaudeService):
    def __init__(
        self,
        comando: str,
        modelo: str,
        arquivo_estado: Path,
        hora_reteste: int = 8,
        reteste_minutos: int = 60,
        timeout: float = 300.0,
        agora: Callable[[], datetime] = datetime.now,
        executar: Callable = subprocess.run,
        localizar: Callable[[str], Optional[str]] = shutil.which,
    ):
        super().__init__(api_key="", modelo=modelo, versao_api="", arquivo_estado=arquivo_estado,
                         limite_mensal_usd=0, hora_reteste=hora_reteste, agora=agora, timeout=timeout)
        self.comando = comando
        self.reteste_minutos = reteste_minutos
        self._executar = executar
        self._localizar = localizar

    def caminho(self) -> Optional[str]:
        return self._localizar(self.comando)

    def configurado(self) -> bool:
        return bool(self.caminho())

    def _motivo_nao_configurado(self) -> str:
        return "Claude Code não encontrado no PC (instale e rode 'claude auth login')"

    def argumentos(self, arquivo_prompt: Path) -> List[str]:
        return [self.caminho(), "-p", "--output-format", "json", "--system-prompt-file", str(arquivo_prompt),
                "--tools", "", "--disallowedTools", "mcp__*", "--no-session-persistence", "--model", self.modelo]

    def gerar_texto(self, prompt_sistema: str, mensagem_usuario: str,
                    historico: Optional[List[Dict[str, str]]] = None, max_tokens: Optional[int] = None) -> str:
        self.verificar_disponibilidade()
        ambiente = {k: v for k, v in os.environ.items() if k not in VARIAVEIS_RETIRADAS}
        with tempfile.TemporaryDirectory(prefix="claude-assistente-") as pasta:
            arquivo_prompt = Path(pasta) / "sistema.md"
            arquivo_prompt.write_text(prompt_sistema, encoding="utf-8")
            with custom_logger.etapa("claude", componente=COMPONENTE, modelo=self.modelo, modo="assinatura"):
                try:
                    processo = self._executar(
                        self.argumentos(arquivo_prompt), input=montar_conversa(historico, mensagem_usuario),
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=self.timeout, cwd=pasta, env=ambiente,
                    )
                except subprocess.TimeoutExpired as erro:
                    raise ClaudeIndisponivelError("o Claude Code não respondeu a tempo") from erro
                except OSError as erro:
                    raise ClaudeIndisponivelError(f"não foi possível iniciar o Claude Code ({type(erro).__name__})") from erro
        dados = _ler_json(processo.stdout)
        if processo.returncode == 0 and dados and not dados.get("is_error") and dados.get("subtype", "success") == "success":
            # total_cost_usd é a estimativa do Claude Code; na assinatura não é cobrado
            custom_logger.evento(COMPONENTE, "resposta", modo="assinatura",
                                 custo_estimado_usd=dados.get("total_cost_usd"), duracao_ms=dados.get("duration_ms"))
            return str(dados.get("result") or "").strip()
        detalhe = str((dados or {}).get("result") or processo.stderr or processo.stdout or "")
        raise self._erro_cli(detalhe, processo.returncode)

    def _erro_cli(self, detalhe: str, codigo: int) -> ClaudeIndisponivelError:
        texto = detalhe.lower()
        if any(sinal in texto for sinal in _SINAIS_LIMITE):
            ate = self._agora() + timedelta(minutes=self.reteste_minutos)
            return self._marcar_indisponivel("limite de uso da assinatura do Claude atingido", ate)
        if any(sinal in texto for sinal in _SINAIS_LOGIN):
            return self._marcar_indisponivel("Claude Code sem login (rode 'claude auth login')",
                                             proxima_manha(self._agora(), self.hora_reteste))
        custom_logger.evento(COMPONENTE, "falha", detalhe[:200], nivel="WARNING", modo="assinatura", codigo=codigo)
        return ClaudeIndisponivelError(f"o Claude Code falhou (código {codigo})")


def _ler_json(saida: str) -> Optional[Dict]:
    """A saída `--output-format json` é um objeto; avisos eventuais vêm antes, em outras linhas."""
    for trecho in [saida or ""] + list(reversed((saida or "").strip().splitlines())):
        try:
            dados = json.loads(trecho)
        except ValueError:
            continue
        if isinstance(dados, dict):
            return dados
    return None
