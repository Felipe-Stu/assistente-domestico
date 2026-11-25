"""
M23: o núcleo do assistente como serviço de rede.

    python app/servidor.py          (o Electron inicia sozinho; pode também rodar sem janela)

- HTTP + eventos do servidor (SSE), sem porta aberta para a internet: escuta em 127.0.0.1. De fora de casa,
  o celular entra pelo Tailscale ("tailscale serve"), que entrega HTTPS dentro da rede privada.
- Todo pedido leva o token do dispositivo (cabeçalho Authorization, cookie depois de /entrar, ou ?token= nos eventos).
- O servidor só enfileira comandos: quem executa é o mesmo laço do núcleo (app/laco.py), um pedido por vez.

Rotas
  GET  /api/saude              estado do núcleo (sem token)
  GET  /api/eu                 quem é este dispositivo
  POST /api/mensagens          {"texto": "..."}
  POST /api/comandos           {"type": ..., "payload": {...}}   (voz, mudo, arquivo pelo caminho: só no PC)
  POST /api/anexos             multipart, campo "arquivo" (HTML da nota, PDF ou foto)
  GET  /api/eventos            SSE: histórico recente e depois cada evento do núcleo
  GET  /api/gastos/resumo      números do painel (I06)
  GET  /entrar?token=...       grava o token num cookie e abre a página (celular)
  GET  /  e  /painel           página instalável (I04) e painel de gastos (I06)
"""
import asyncio
import json
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from starlette.applications import Starlette  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from starlette.routing import Mount, Route  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

COOKIE = "assistente_token"
LIMITE_TEXTO = 4000
EXTENSOES_ANEXO = {".html", ".htm", ".pdf", ".jpg", ".jpeg", ".png", ".webp"}
COMANDOS_LOCAIS = {"toggle_voice_mode", "toggle_mute", "toggle_microphone", "documento", "shutdown"}
COMANDOS_REMOTOS: set = set()
VERSAO_API = "1"


CSP = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'"


class CabecalhosDeSeguranca:
    """Middleware ASGI puro (não atrapalha o fluxo de eventos): cabeçalhos de segurança em toda resposta."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def enviar(mensagem):
            if mensagem["type"] == "http.response.start":
                cabecalhos = list(mensagem.get("headers") or [])
                existentes = {k.lower() for k, _ in cabecalhos}
                extras = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                          (b"x-frame-options", b"DENY"), (b"content-security-policy", CSP.encode())]
                cabecalhos += [(k, v) for k, v in extras if k not in existentes]
                mensagem = dict(mensagem, headers=cabecalhos)
            await send(mensagem)

        await self.app(scope, receive, enviar)


def _nome_seguro(nome: str) -> str:
    nome = Path(str(nome or "arquivo")).name
    nome = "".join(c if c.isalnum() or c in "._-" else "_" for c in nome)[-80:]
    return nome or "arquivo"


def criar_app(enfileirar: Callable[[Dict], None], dispositivos, barramento, *, pasta_recebidos: Path,
              pasta_web: Optional[Path] = None, tamanho_max_mb: float = 20,
              resumo_gastos: Optional[Callable[[int], Dict]] = None,
              ao_desligar: Optional[Callable[[], None]] = None, ping_s: float = 15) -> Starlette:
    pasta_recebidos = Path(pasta_recebidos)
    limite_bytes = int(tamanho_max_mb * 1024 * 1024)

    def token_do_pedido(request: Request) -> Optional[str]:
        cabecalho = request.headers.get("authorization", "")
        if cabecalho.lower().startswith("bearer "):
            return cabecalho[7:].strip()
        return request.cookies.get(COOKIE) or request.query_params.get("token")

    def autenticar(request: Request):
        return dispositivos.validar(token_do_pedido(request))

    def negado():
        return JSONResponse({"erro": "token ausente, inválido ou revogado"}, status_code=401)

    async def saude(request: Request):
        return JSONResponse({"ok": True, "estado": barramento.ultimo_estado, "versao_api": VERSAO_API})

    async def eu(request: Request):
        dispositivo = autenticar(request)
        if not dispositivo:
            return negado()
        return JSONResponse({"nome": dispositivo["nome"], "escopo": dispositivo["escopo"], "id": dispositivo["id"]})

    async def mensagens(request: Request):
        dispositivo = autenticar(request)
        if not dispositivo:
            return negado()
        try:
            dados = await request.json()
        except (ValueError, json.JSONDecodeError):
            return JSONResponse({"erro": "JSON inválido"}, status_code=400)
        texto = " ".join(str(dados.get("texto") or "").split("\x00")).strip()
        if not texto:
            return JSONResponse({"erro": "texto vazio"}, status_code=400)
        if len(texto) > LIMITE_TEXTO:
            return JSONResponse({"erro": f"texto acima de {LIMITE_TEXTO} caracteres"}, status_code=413)
        canal = "chat" if dispositivo["escopo"] == "local" else "celular"
        enfileirar({"type": "send_text", "payload": {"text": texto, "canal": canal, "dispositivo": dispositivo["nome"]}})
        return JSONResponse({"ok": True}, status_code=202)

    async def comandos(request: Request):
        dispositivo = autenticar(request)
        if not dispositivo:
            return negado()
        try:
            dados = await request.json()
        except (ValueError, json.JSONDecodeError):
            return JSONResponse({"erro": "JSON inválido"}, status_code=400)
        tipo = dados.get("type")
        permitidos = COMANDOS_LOCAIS if dispositivo["escopo"] == "local" else COMANDOS_REMOTOS
        if tipo not in permitidos:
            return JSONResponse({"erro": f"comando não permitido para este dispositivo: {tipo}"}, status_code=403)
        payload = dados.get("payload") if isinstance(dados.get("payload"), dict) else {}
        if tipo == "documento":
            caminho = Path(str(payload.get("caminho") or ""))
            if caminho.suffix.lower() not in EXTENSOES_ANEXO or not caminho.is_file():
                return JSONResponse({"erro": "arquivo inexistente ou de formato não aceito"}, status_code=400)
            payload = {"caminho": str(caminho), "canal": "app"}
        if tipo == "shutdown":
            enfileirar({"type": "shutdown"})
            if ao_desligar:
                threading.Timer(0.5, ao_desligar).start()
            return JSONResponse({"ok": True}, status_code=202)
        enfileirar({"type": tipo, "payload": payload})
        return JSONResponse({"ok": True}, status_code=202)

    async def anexos(request: Request):
        dispositivo = autenticar(request)
        if not dispositivo:
            return negado()
        tamanho = int(request.headers.get("content-length") or 0)
        if tamanho > limite_bytes * 5 + 1024 * 1024:
            return JSONResponse({"erro": f"envio acima de {tamanho_max_mb:g} MB por arquivo"}, status_code=413)
        formulario = await request.form(max_files=5)
        aceitos, recusados = [], []
        pasta_recebidos.mkdir(parents=True, exist_ok=True)
        for campo in formulario.getlist("arquivo"):
            if not hasattr(campo, "read"):
                continue
            nome = _nome_seguro(campo.filename)
            conteudo = await campo.read()
            if Path(nome).suffix.lower() not in EXTENSOES_ANEXO:
                recusados.append({"nome": nome, "motivo": "formato não aceito (use HTML da nota, PDF ou foto)"})
                continue
            if len(conteudo) > limite_bytes:
                recusados.append({"nome": nome, "motivo": f"acima de {tamanho_max_mb:g} MB"})
                continue
            destino = pasta_recebidos / f"{datetime.now():%Y%m%d-%H%M%S}-{time.monotonic_ns() % 100000:05d}-{nome}"
            destino.write_bytes(conteudo)
            enfileirar({"type": "documento", "payload": {"caminho": str(destino), "canal": "celular"}})
            aceitos.append(nome)
        await formulario.close()
        if not aceitos and not recusados:
            return JSONResponse({"erro": "nenhum arquivo no campo 'arquivo'"}, status_code=400)
        return JSONResponse({"aceitos": aceitos, "recusados": recusados}, status_code=202 if aceitos else 400)

    async def eventos(request: Request):
        dispositivo = autenticar(request)
        if not dispositivo:
            return negado()
        from sse_starlette.sse import EventSourceResponse
        loop = asyncio.get_running_loop()
        ident, fila = barramento.assinar_async(loop)

        async def gerador():
            try:
                yield {"event": "historico", "data": json.dumps({"eventos": barramento.historico(),
                                                                 "estado": barramento.ultimo_estado}, ensure_ascii=False)}
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        evento = await asyncio.wait_for(fila.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    yield {"event": "evento", "id": str(evento["id"]), "data": json.dumps(evento, ensure_ascii=False)}
            finally:
                barramento.cancelar(ident)

        return EventSourceResponse(gerador(), ping=ping_s)

    async def gastos(request: Request):
        if not autenticar(request):
            return negado()
        if resumo_gastos is None:
            return JSONResponse({"erro": "painel indisponível"}, status_code=503)
        try:
            meses = int(request.query_params.get("meses", "12"))
        except ValueError:
            meses = 12
        dados = await asyncio.get_running_loop().run_in_executor(None, resumo_gastos, meses)
        return JSONResponse(dados)

    async def entrar(request: Request):
        token = request.query_params.get("token", "")
        if not dispositivos.validar(token):
            return JSONResponse({"erro": "token inválido ou revogado"}, status_code=401)
        resposta = RedirectResponse(url="/", status_code=303)
        seguro = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resposta.set_cookie(COOKIE, token, max_age=60 * 60 * 24 * 365, httponly=True, samesite="strict", secure=seguro)
        return resposta

    async def sair(request: Request):
        resposta = RedirectResponse(url="/", status_code=303)
        resposta.delete_cookie(COOKIE)
        return resposta

    def pagina(nome: str):
        async def servir(request: Request):
            if pasta_web is None or not (Path(pasta_web) / nome).is_file():
                return Response("Página não encontrada.", status_code=404)
            return FileResponse(Path(pasta_web) / nome, headers={"Cache-Control": "no-cache"})
        return servir

    rotas = [
        Route("/api/saude", saude),
        Route("/api/eu", eu),
        Route("/api/mensagens", mensagens, methods=["POST"]),
        Route("/api/comandos", comandos, methods=["POST"]),
        Route("/api/anexos", anexos, methods=["POST"]),
        Route("/api/eventos", eventos),
        Route("/api/gastos/resumo", gastos),
        Route("/entrar", entrar),
        Route("/sair", sair),
        Route("/", pagina("index.html")),
        Route("/painel", pagina("painel.html")),
        Route("/sw.js", pagina("sw.js")),
        Route("/manifest.webmanifest", pagina("manifest.webmanifest")),
    ]
    if pasta_web is not None and Path(pasta_web).is_dir():
        rotas.append(Mount("/web", app=StaticFiles(directory=str(pasta_web)), name="web"))
    return Starlette(routes=rotas, middleware=[Middleware(CabecalhosDeSeguranca)])


def main() -> int:
    import uvicorn

    import app.ipc as ipc
    ipc.SAIDA_STDOUT = False   # os eventos vão pela rede, não pela saída padrão
    import core.config as config
    from app.eventos import barramento
    from app.main import AssistenteRuntime
    from services.consultas_service import resumo_para_painel
    from services.dispositivos_service import Dispositivos

    dispositivos = Dispositivos(config.DISPOSITIVOS_ARQUIVO)
    dispositivos.token_local(config.TOKEN_LOCAL_ARQUIVO)
    runtime = AssistenteRuntime()
    nucleo = threading.Thread(target=runtime.rodar, kwargs={"ler_stdin": False}, daemon=True, name="nucleo")
    nucleo.start()
    servidor_holder = {}

    def desligar():
        servidor = servidor_holder.get("servidor")
        if servidor is not None:
            servidor.should_exit = True

    def resumo(meses: int):
        if runtime.db_service is None:
            raise RuntimeError("banco ainda não aberto")
        return resumo_para_painel(runtime.db_service, meses)

    app = criar_app(runtime.fila.put, dispositivos, barramento, pasta_recebidos=config.RECEBIDOS_DIR,
                    pasta_web=config.WEB_DIR, tamanho_max_mb=config.ENTRADAS_TAMANHO_MAX_MB,
                    resumo_gastos=resumo, ao_desligar=desligar)
    configuracao = uvicorn.Config(app, host=config.API_HOST, port=config.API_PORTA, log_level="warning")
    servidor = uvicorn.Server(configuracao)
    servidor_holder["servidor"] = servidor
    print(f"Assistente em http://{config.API_HOST}:{config.API_PORTA}  (Ctrl+C encerra)", flush=True)
    try:
        servidor.run()
    finally:
        runtime.fila.put({"type": "shutdown"})
        nucleo.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
