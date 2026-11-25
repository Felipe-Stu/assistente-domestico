"""
Comunicação com o Electron por stdin/stdout (JSON por linha).

Importado antes de qualquer outro módulo do app: configura UTF-8 nos fluxos e isola o pipe de
entrada num descritor privado (ENTRADA_IPC) antes que alguma biblioteca toque na entrada padrão.
"""
import io
import json
import os
import sys

# Configura codificação de fluxo para UTF-8 no Windows antes de qualquer saída
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def _isolar_entrada_ipc():
    """
    Devolve um leitor UTF-8 exclusivo para os comandos do Electron e troca a entrada
    padrão do processo por uma vazia (os.devnull).

    Motivo: no Windows, enquanto a thread de leitura espera a próxima linha no pipe,
    qualquer consulta de outra thread a esse mesmo pipe (bibliotecas que checam o stdin
    ao serem importadas, como na carga do modelo de embeddings) fica bloqueada até chegar
    uma nova mensagem. Com o pipe em um descritor privado, ninguém além do leitor o toca.
    O Electron envia os comandos em UTF-8; sem isso, acentos chegam corrompidos ("café" -> "cafÃ©").
    """
    try:
        fd_privado = os.dup(sys.stdin.fileno())
        fd_nulo = os.open(os.devnull, os.O_RDONLY)
        os.dup2(fd_nulo, 0)  # no Windows também atualiza o handle padrão de entrada
        os.close(fd_nulo)
        entrada = open(fd_privado, "r", encoding="utf-8", closefd=True)
        sys.stdin = open(os.devnull, "r", encoding="utf-8")
        return entrada
    except Exception:
        # Sem descritor real (ex.: execução embutida): mantém o comportamento anterior
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
        return sys.stdin


ENTRADA_IPC = _isolar_entrada_ipc()


# Ponte antiga (Electron lendo a saída padrão). O servidor (app/servidor.py) desliga: lá os eventos vão pela rede.
SAIDA_STDOUT = True


def emitir_electron(tipo, payload=None):
    """Publica um evento do núcleo no barramento e, na ponte antiga, imprime em JSON para o Electron."""
    from app.eventos import barramento
    barramento.publicar(tipo, payload)
    if SAIDA_STDOUT:
        msg = {"type": tipo}
        if payload is not None:
            msg["payload"] = payload
        print(json.dumps(msg, ensure_ascii=False), flush=True)
