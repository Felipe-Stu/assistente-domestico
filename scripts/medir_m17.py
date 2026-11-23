"""
Medição do M17 (falhar rápido quando o Ollama está fora) contra o aplicativo real.

Abre app/main.py como o Electron faz (comandos por pipe), espera o chat ficar pronto, envia uma
frase sem regra fixa (passa pelo orquestrador) e mede o tempo até a resposta. Não grava no banco.

Uso, com o Ollama FECHADO (feche-o pela bandeja do Windows):
    python scripts/medir_m17.py
Para comparar com o Ollama aberto, rode de novo depois de abri-lo.
"""
import json
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASTA_SAIDA = ROOT.parent / "Planejamento" / "medicoes"
FRASE = "Conte uma curiosidade sobre gatos"
LIMITE = 120.0


def main():
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    from services.llm_provider import verificar_ollama

    erro_saude = verificar_ollama()
    estado = "fechado" if erro_saude else "aberto"
    print(f"[M17] Ollama {estado}{' (' + erro_saude[:80] + ')' if erro_saude else ''}", flush=True)

    t0 = time.perf_counter()
    proc = subprocess.Popen([sys.executable, "-u", "app/main.py"], cwd=ROOT, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    eventos = queue.Queue()

    def ler():
        for linha in proc.stdout:
            eventos.put((time.perf_counter() - t0, linha.strip()))
        eventos.put((time.perf_counter() - t0, None))

    threading.Thread(target=ler, daemon=True).start()
    r = {"ollama": estado, "frase": FRASE, "pronto_s": None, "resposta_s": None, "tempo_resposta_s": None,
         "tentar_novamente": False, "resposta": None, "aviso_inicio": None}
    enviado_em = None
    while time.perf_counter() - t0 < LIMITE:
        try:
            t, linha = eventos.get(timeout=1.0)
        except queue.Empty:
            continue
        if linha is None:
            break
        try:
            msg = json.loads(linha)
        except json.JSONDecodeError:
            continue
        tipo, carga = msg.get("type"), msg.get("payload") or {}
        if tipo == "debug_log" and "Ollama" in (carga.get("message") or ""):
            r["aviso_inicio"] = carga["message"]
            print(f"[M17]   início: {carga['message']}", flush=True)
        if tipo == "system_ready" and enviado_em is None:
            r["pronto_s"] = round(t, 2)
            proc.stdin.write(json.dumps({"type": "send_text", "payload": {"text": FRASE}}) + "\n")
            proc.stdin.flush()
            enviado_em = t
            print(f"[M17]   chat pronto em {t:.1f} s; enviando: {FRASE}", flush=True)
        elif tipo == "assistant_message" and enviado_em is not None:
            r["resposta_s"] = round(t, 2)
            r["tempo_resposta_s"] = round(t - enviado_em, 2)
            r["tentar_novamente"] = bool(carga.get("tentar_novamente"))
            r["resposta"] = (carga.get("text") or "")[:160]
            print(f"[M17]   resposta em {t - enviado_em:.2f} s · botão 'Tentar de novo': "
                  f"{'sim' if r['tentar_novamente'] else 'não'}\n[M17]   {r['resposta']}", flush=True)
            break
    try:
        proc.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
        proc.stdin.flush()
        proc.wait(timeout=15)
    except Exception:
        proc.kill()

    carimbo = datetime.now().strftime("%Y%m%d-%H%M")
    destino = PASTA_SAIDA / f"m17-{carimbo}-ollama-{estado}.json"
    destino.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResultado em {destino}")


if __name__ == "__main__":
    main()
