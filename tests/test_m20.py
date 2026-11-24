"""Testes do M20: histórico gravado, janela das últimas trocas, resumo das antigas e retomada ao reabrir."""
import sys
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from app import main as app_main  # noqa: E402
from app.sessao import PREFIXO_RESUMO, GerenciadorDeSessao  # noqa: E402


class Relogio:
    def __init__(self):
        self.agora = datetime(2026, 11, 24, 8, 0, 0)

    def __call__(self):
        self.agora += timedelta(seconds=1)
        return self.agora


def esperar_resumos():
    for t in threading.enumerate():
        if t.name == "resumo-conversa":
            t.join(timeout=5)


class TestSessao(fase1.BaseBanco):
    def nova(self, relogio=None, resumir=None, janela=2):
        sessao = GerenciadorDeSessao(janela_trocas=janela, agora=relogio or Relogio())
        sessao.conectar(self.db, resumir)
        return sessao

    def test_janela_limita_o_que_vai_ao_modelo(self):
        sessao = self.nova()
        for n in range(5):
            sessao.atualizar_sessao("geral", f"pergunta {n}", f"resposta {n}")
        self.assertEqual([m["content"] for m in sessao.historico], ["pergunta 3", "resposta 3", "pergunta 4", "resposta 4"])
        self.assertEqual(self.db.executar_consulta_uma_linha("SELECT count(*) FROM historico_conversas")[0], 10)   # tudo gravado

    def test_resumo_das_trocas_que_saem(self):
        recebidos = []

        def resumir(anterior, mensagens):
            recebidos.append((anterior, [m["content"] for m in mensagens]))
            return f"conversa sobre {len(recebidos)} assunto(s)"

        sessao = self.nova(resumir=resumir)
        for n in range(4):
            sessao.atualizar_sessao("geral", f"p{n}", f"r{n}")
            esperar_resumos()
        self.assertEqual(recebidos[0], (None, ["p0", "r0"]))
        self.assertEqual(recebidos[1][0], "conversa sobre 1 assunto(s)")   # o novo resumo parte do anterior
        historico = sessao.historico
        self.assertEqual(historico[0]["content"], PREFIXO_RESUMO + "conversa sobre 2 assunto(s)")
        self.assertEqual([m["content"] for m in historico[2:]], ["p2", "r2", "p3", "r3"])

    def test_resumo_que_falha_so_tira_da_janela(self):
        sessao = self.nova(resumir=lambda *_a: (_ for _ in ()).throw(ConnectionError("ollama")))
        for n in range(3):
            sessao.atualizar_sessao("geral", f"p{n}", f"r{n}")
            esperar_resumos()
        self.assertEqual(len(sessao.historico), 4)
        self.assertIsNone(sessao.resumo)

    def test_retoma_ao_reabrir_e_nao_retoma_conversa_velha(self):
        relogio = Relogio()
        primeira = self.nova(relogio, resumir=lambda a, m: "falamos do aniversário")
        for n in range(3):
            primeira.atualizar_sessao("geral", f"p{n}", f"r{n}")
            esperar_resumos()
        relogio.agora += timedelta(hours=2)
        reaberta = GerenciadorDeSessao(janela_trocas=2, agora=relogio)
        self.assertTrue(reaberta.conectar(self.db, None, retomar_horas=12))
        self.assertEqual((reaberta.session_id, reaberta.contexto_ativo), (primeira.session_id, "geral"))
        self.assertEqual(reaberta.resumo, "falamos do aniversário")
        self.assertEqual([m["content"] for m in reaberta.historico[2:]], ["p1", "r1", "p2", "r2"])
        relogio.agora += timedelta(hours=13)
        velha = GerenciadorDeSessao(janela_trocas=2, agora=relogio)
        self.assertFalse(velha.conectar(self.db, None, retomar_horas=12))
        self.assertEqual(velha.historico, [])

    def test_mudanca_de_contexto_e_nova_conversa(self):
        sessao = self.nova()
        sessao.atualizar_sessao("geral", "oi", "olá")
        sessao.atualizar_sessao("compras", "comprei pão", "anotado")
        self.assertEqual([m["content"] for m in sessao.historico], ["comprei pão", "anotado"])
        antiga = sessao.session_id
        sessao.nova_conversa()
        self.assertNotEqual(sessao.session_id, antiga)
        self.assertEqual((sessao.historico, sessao.contexto_ativo), ([], None))


class TestNoApp(unittest.TestCase):
    def test_frase_de_nova_conversa(self):
        for frase in ("nova conversa", "limpar a conversa", "esqueça essa conversa", "Começar uma nova conversa"):
            self.assertTrue(app_main.RE_NOVA_CONVERSA.match(app_main.normalizar_texto(frase).strip(" .!?")), frase)
        self.assertIsNone(app_main.RE_NOVA_CONVERSA.match("como foi a conversa com o pedreiro"))


if __name__ == "__main__":
    unittest.main()
