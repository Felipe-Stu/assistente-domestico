"""
Confere o Claude pela assinatura: Claude Code instalado, login no plano (não por chave de API) e uma
resposta curta. Grava o resultado em Planejamento/medicoes/claude-assinatura-ultima.txt.
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core import config  # noqa: E402
from services.claude_assinatura_service import ClaudeAssinaturaService, VARIAVEIS_RETIRADAS  # noqa: E402
from services.claude_service import ClaudeIndisponivelError  # noqa: E402

SAIDA = RAIZ.parent / "Planejamento" / "medicoes" / "claude-assinatura-ultima.txt"


def main() -> int:
    linhas = [f"Teste do Claude pela assinatura — {datetime.now():%d/%m/%Y %H:%M}", f"CLAUDE_MODO={config.CLAUDE_MODO}"]
    servico = ClaudeAssinaturaService(config.CLAUDE_COMANDO, config.CLAUDE_MODELO_ASSINATURA,
                                      config.CLAUDE_ESTADO_ASSINATURA_ARQUIVO, timeout=180)
    caminho = servico.caminho()
    linhas.append(f"1. Claude Code: {caminho or 'NÃO ENCONTRADO — instale: https://code.claude.com/docs/en/setup'}")
    ok = bool(caminho)
    if ok:
        import os
        ambiente = {k: v for k, v in os.environ.items() if k not in VARIAVEIS_RETIRADAS}
        status = subprocess.run([caminho, "auth", "status"], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=ambiente, timeout=60)
        try:
            metodo = json.loads(status.stdout).get("authMethod")
        except ValueError:
            metodo = None
        if status.returncode != 0:
            linhas.append("2. Login: NÃO — rode 'claude auth login' e entre com a sua conta do Claude")
            ok = False
        else:
            linhas.append(f"2. Login: sim ({metodo or 'método não informado'})"
                          + ("" if metodo in (None, "claude.ai", "oauth_token") else " — ATENÇÃO: não é a assinatura; pode haver cobrança"))
    if ok:
        inicio = time.monotonic()
        try:
            resposta = servico.gerar_texto("Responda só com a palavra pedida.", "Responda: funcionando")
            linhas.append(f"3. Resposta em {time.monotonic() - inicio:.1f} s: {resposta[:80]!r}")
        except ClaudeIndisponivelError as erro:
            linhas.append(f"3. Resposta: FALHOU — {erro.motivo}")
            ok = False
    linhas.append("RESULTADO: OK" if ok else "RESULTADO: com pendências (veja acima)")
    texto = "\n".join(linhas)
    print(texto)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(texto + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
