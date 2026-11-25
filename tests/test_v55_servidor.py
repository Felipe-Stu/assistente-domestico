"""V5.5: barramento de eventos, dispositivos (tokens) e a API do núcleo.

Os testes da API sobem o servidor de verdade (uvicorn) e só rodam se starlette, uvicorn, sse-starlette,
python-multipart e requests estiverem instalados (requirements.txt)."""
import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.eventos import Barramento  # noqa: E402
from services.dispositivos_service import Dispositivos  # noqa: E402

try:
    import multipart  # noqa: F401
    import requests
    import sse_starlette  # noqa: F401
    import starlette  # noqa: F401
    import uvicorn
    TEM_SERVIDOR = True
except ImportError:
    TEM_SERVIDOR = False


class TestBarramento(unittest.TestCase):
    def test_publica_guarda_conversa_e_isola_ouvinte_com_erro(self):
        b = Barramento(limite_historico=3)
        recebidos = []
        b.assinar(lambda e: (_ for _ in ()).throw(RuntimeError("cliente quebrado")))
        ident = b.assinar(recebidos.append)
        b.publicar("state_changed", {"state": "PROCESSING"})
        for n in range(4):
            b.publicar("assistant_message", {"text": str(n)})
        b.publicar("debug_log", {"message": "x"})
        self.assertEqual(b.ultimo_estado, "PROCESSING")
        self.assertEqual(len(recebidos), 6)
        self.assertEqual([e["payload"]["text"] for e in b.historico()], ["1", "2", "3"])   # só conversa, só os últimos
        self.assertTrue(all(a["id"] < c["id"] for a, c in zip(recebidos, recebidos[1:])))
        b.cancelar(ident)
        b.publicar("assistant_message", {"text": "depois"})
        self.assertEqual(len(recebidos), 6)

    def test_ponte_antiga_imprime_e_servidor_nao(self):
        import app.ipc as ipc
        from app.eventos import barramento
        saida = io.StringIO()
        with redirect_stdout(saida):
            ipc.emitir_electron("debug_log", {"message": "ponte"})
            ipc.SAIDA_STDOUT = False
            try:
                ipc.emitir_electron("debug_log", {"message": "rede"})
            finally:
                ipc.SAIDA_STDOUT = True
        self.assertIn('"ponte"', saida.getvalue())
        self.assertNotIn('"rede"', saida.getvalue())
        self.assertIsNotNone(barramento)


class TestDispositivos(unittest.TestCase):
    def test_token_hash_revogacao_e_token_local(self):
        with tempfile.TemporaryDirectory() as pasta:
            d = Dispositivos(Path(pasta) / "d.json")
            token = d.criar("Celular", "remoto")
            self.assertEqual(d.validar(token)["escopo"], "remoto")
            self.assertIsNone(d.validar("outro"))
            gravado = (Path(pasta) / "d.json").read_text(encoding="utf-8")
            self.assertNotIn(token, gravado)
            self.assertEqual(d.revogar("Celular"), 1)
            self.assertIsNone(d.validar(token))
            local = d.token_local(Path(pasta) / "t.txt")
            self.assertEqual(d.token_local(Path(pasta) / "t.txt"), local)   # não recria à toa
            d.revogar("PC (Electron)")
            self.assertNotEqual(d.token_local(Path(pasta) / "t.txt"), local)  # revogado: recria
            with self.assertRaises(ValueError):
                d.criar("x", "admin")


def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(TEM_SERVIDOR, "starlette/uvicorn/sse-starlette/python-multipart/requests ausentes")
class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.servidor import criar_app
        cls.tmp = tempfile.TemporaryDirectory()
        pasta = Path(cls.tmp.name)
        cls.disp = Dispositivos(pasta / "disp.json")
        cls.local = cls.disp.token_local(pasta / "token.txt")
        cls.celular = cls.disp.criar("celular", "remoto")
        cls.bar = Barramento()
        cls.fila = []
        cls.desligado = []

        def enfileirar(cmd):
            cls.fila.append(cmd)
            if cmd["type"] == "send_text":
                cls.bar.publicar("user_message", {"text": cmd["payload"]["text"]})
                cls.bar.publicar("assistant_message", {"text": "ok: " + cmd["payload"]["text"]})

        web = pasta / "web"
        web.mkdir()
        (web / "index.html").write_text("<h1>pwa</h1>", encoding="utf-8")
        app = criar_app(enfileirar, cls.disp, cls.bar, pasta_recebidos=pasta / "rec", pasta_web=web, tamanho_max_mb=1,
                        resumo_gastos=lambda m: {"meses": m}, ao_desligar=lambda: cls.desligado.append(1), ping_s=2)
        cls.porta = _porta_livre()
        cls.servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.porta, log_level="warning"))
        threading.Thread(target=cls.servidor.run, daemon=True).start()
        cls.U = f"http://127.0.0.1:{cls.porta}"
        for _ in range(100):
            try:
                requests.get(cls.U + "/api/saude", timeout=0.5)
                break
            except requests.RequestException:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.should_exit = True
        time.sleep(0.3)
        cls.tmp.cleanup()

    def h(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_autenticacao(self):
        self.assertEqual(requests.get(self.U + "/api/saude").status_code, 200)
        self.assertEqual(requests.post(self.U + "/api/mensagens", json={"texto": "oi"}).status_code, 401)
        self.assertEqual(requests.post(self.U + "/api/mensagens", json={"texto": "oi"}, headers=self.h("x")).status_code, 401)
        self.assertEqual(requests.get(self.U + "/api/eu", headers=self.h(self.celular)).json()["escopo"], "remoto")
        s = requests.Session()
        r = s.get(self.U + "/entrar?token=" + self.celular, allow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("HttpOnly", r.headers["set-cookie"])
        self.assertEqual(s.get(self.U + "/api/eu").status_code, 200)
        r = requests.get(self.U + "/")
        self.assertIn("default-src 'self'", r.headers["content-security-policy"])

    def test_mensagem_e_eventos(self):
        resultado = {}

        def ler():
            with requests.get(self.U + "/api/eventos?token=" + self.celular, stream=True, timeout=10) as resp:
                evento = None
                for linha in resp.iter_lines(decode_unicode=True):
                    if linha.startswith("event:"):
                        evento = linha[6:].strip()
                    elif linha.startswith("data:") and evento == "evento":
                        dados = json.loads(linha[5:])
                        if dados["type"] == "assistant_message":
                            resultado["resposta"] = dados["payload"]["text"]
                            return
        t = threading.Thread(target=ler, daemon=True)
        t.start()
        time.sleep(0.6)
        r = requests.post(self.U + "/api/mensagens", json={"texto": "quanto gastei?"}, headers=self.h(self.celular))
        self.assertEqual(r.status_code, 202)
        self.assertEqual(self.fila[-1]["payload"]["canal"], "celular")
        t.join(5)
        self.assertEqual(resultado.get("resposta"), "ok: quanto gastei?")

    def test_comandos_por_escopo_e_anexos(self):
        mudo = {"type": "toggle_mute", "payload": {"muted": True}}
        self.assertEqual(requests.post(self.U + "/api/comandos", json=mudo, headers=self.h(self.celular)).status_code, 403)
        self.assertEqual(requests.post(self.U + "/api/comandos", json=mudo, headers=self.h(self.local)).status_code, 202)
        r = requests.post(self.U + "/api/anexos", headers=self.h(self.celular),
                          files=[("arquivo", ("foto nota.jpg", b"jpg", "image/jpeg")), ("arquivo", ("x.exe", b"x", "application/x"))])
        self.assertEqual(r.json()["aceitos"], ["foto_nota.jpg"])
        self.assertEqual(self.fila[-1]["payload"]["canal"], "celular")
        self.assertTrue(Path(self.fila[-1]["payload"]["caminho"]).exists())


if __name__ == "__main__":
    unittest.main()
