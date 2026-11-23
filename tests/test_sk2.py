"""
Testes do SK2 (roadmap das skills): o orquestrador escolhe a skill pelo catálogo.
O modelo é simulado; a medição real fica com scripts/avaliar.py.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core import config  # noqa: E402
from core.skills import obter_catalogo, seletor  # noqa: E402
from services import gemma_service, llm_provider, logger_service  # noqa: E402
from services.resilience_service import InvalidOrchestratorOutputException  # noqa: E402


class Espiao:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = []

    def gerar_json(self, prompt_sistema, mensagem_usuario, historico=None, esquema=None, raciocinio=None):
        self.chamadas.append({"prompt": prompt_sistema, "mensagem": mensagem_usuario, "esquema": esquema, "raciocinio": raciocinio})
        return self.resposta


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        for patcher in (
            mock.patch.object(logger_service.logger, "base_dir", os.path.join(self._tmp.name, "logs")),
            mock.patch.object(gemma_service, "ORQUESTRADOR_MODO", "catalogo"),
            mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def orquestrar(self, texto, resposta, contexto_atual=None):
        espiao = Espiao(resposta)
        with mock.patch.object(gemma_service, "obter_provedor_local", return_value=espiao):
            decisao = gemma_service.orquestrar_requisicao(texto, contexto_atual)
        return decisao, espiao


class TestOrquestradorPeloCatalogo(Base):
    def test_padrao_e_o_catalogo(self):
        self.assertEqual(config.ORQUESTRADOR_MODO, "catalogo")

    def test_decisao_no_formato_do_app(self):
        decisao, espiao = self.orquestrar("Me ajuda com um erro de Python",
                                          {"skill": "programacao", "acao": "delegar", "dificuldade": "facil"})
        self.assertEqual(decisao, {"dificuldade": "facil", "mudanca_de_contexto": False, "contexto": "programacao",
                                   "acao": "delegar", "skill": "programacao"})
        gemma_service._validar_schema_orquestrador(decisao)
        chamada = espiao.chamadas[0]
        self.assertEqual(chamada["mensagem"], "Me ajuda com um erro de Python")
        self.assertIs(chamada["raciocinio"], False)
        self.assertEqual(chamada["esquema"]["properties"]["skill"]["enum"], [s.nome for s in obter_catalogo()])

    def test_prompt_fixo_sem_a_frase_do_usuario(self):
        _, a = self.orquestrar("frase um", {"skill": "conversa-geral", "acao": "consultar", "dificuldade": "facil"})
        _, b = self.orquestrar("outra frase", {"skill": "conversa-geral", "acao": "consultar", "dificuldade": "facil"}, "compras")
        self.assertEqual(a.chamadas[0]["prompt"], b.chamadas[0]["prompt"])
        self.assertNotIn("frase um", a.chamadas[0]["prompt"])
        # Bem menor que o prompt por contextos (≈ 1.600 tokens na medição do SK0)
        self.assertLess(len(a.chamadas[0]["prompt"]), 2500)

    def test_p10_programacao_e_projetos_podem_ser_escolhidos(self):
        for skill, contexto in (("programacao", "programacao"), ("documentar-projeto", "projetos")):
            with self.subTest(skill=skill):
                decisao, _ = self.orquestrar("pedido", {"skill": skill, "acao": "consultar", "dificuldade": "facil"})
                self.assertEqual(decisao["contexto"], contexto)

    def test_mudanca_de_contexto(self):
        resposta = {"skill": "conversa-geral", "acao": "consultar", "dificuldade": "facil"}
        self.assertFalse(self.orquestrar("x", resposta)[0]["mudanca_de_contexto"])
        self.assertFalse(self.orquestrar("x", resposta, "outro")[0]["mudanca_de_contexto"])
        self.assertTrue(self.orquestrar("x", resposta, "compras")[0]["mudanca_de_contexto"])

    def test_resposta_invalida_vira_erro_recuperavel(self):
        for resposta in ({"skill": "voar", "acao": "consultar", "dificuldade": "facil"},
                         {"skill": "compras", "acao": "explodir", "dificuldade": "facil"},
                         ["não", "é", "objeto"]):
            with self.subTest(resposta=resposta), self.assertRaises(InvalidOrchestratorOutputException):
                self.orquestrar("x", resposta)

    def test_dificuldade_desconhecida_vira_facil(self):
        decisao, _ = self.orquestrar("x", {"skill": "conversa-geral", "acao": "consultar", "dificuldade": "?"})
        self.assertEqual(decisao["dificuldade"], "facil")

    def test_regras_e_comandos_continuam_antes_do_modelo(self):
        with mock.patch.object(gemma_service, "obter_provedor_local") as provedor:
            self.assertEqual(gemma_service.orquestrar_requisicao("Comprei arroz")["contexto"], "compras")
            self.assertEqual(gemma_service.orquestrar_requisicao("Pesquise na internet o preço do frango e compare três mercados")["contexto"], "compras")
        provedor.assert_not_called()

    def test_modo_contextos_continua_disponivel(self):
        espiao = Espiao({"dificuldade": "facil", "mudanca_de_contexto": False, "contexto": "geral", "acao": "consultar"})
        with mock.patch.object(gemma_service, "ORQUESTRADOR_MODO", "contextos"), \
                mock.patch.object(gemma_service, "obter_provedor_local", return_value=espiao):
            decisao = gemma_service.orquestrar_requisicao("Qual a capital da França?")
        self.assertEqual(decisao["contexto"], "geral")
        self.assertIn("ORQUESTRADOR", espiao.chamadas[0]["prompt"])


class TestConversao(unittest.TestCase):
    def test_converter_decisao(self):
        catalogo = obter_catalogo()
        decisao = seletor.converter_decisao({"skill": "estoque", "acao": "corrigir", "dificuldade": "medio_dificil"}, catalogo, "inventario")
        self.assertEqual((decisao["contexto"], decisao["acao"], decisao["dificuldade"], decisao["mudanca_de_contexto"]),
                         ("inventario", "corrigir", "medio_dificil", False))
        with self.assertRaises(seletor.DecisaoInvalidaError):
            seletor.converter_decisao({"skill": None, "acao": "criar"}, catalogo, None)


if __name__ == "__main__":
    unittest.main()
