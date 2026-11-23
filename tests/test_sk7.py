"""
Testes do SK7 (roadmap das skills): agenda criada só com a pasta da skill.
O modelo local é simulado; o banco é um SQLite temporário.
"""
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from app import main as app_main  # noqa: E402
from core.skills import Contexto, motor, obter_catalogo  # noqa: E402
from services import llm_provider  # noqa: E402

SEGUNDA = datetime(2026, 11, 23, 10, 0)


class ModeloFalso:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.prompts = []

    def gerar_json(self, prompt, texto, *_a, **_k):
        self.prompts.append((prompt, texto))
        return self.respostas.pop(0)


class BaseAgenda(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        self.skill = obter_catalogo().skill("agenda")
        self.roteiro = motor.carregar_roteiro(self.skill)
        patcher = mock.patch.object(self.roteiro, "_agora", lambda: SEGUNDA)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ctx(self, modelo=None):
        return Contexto(servicos={"db_service": self.db, "llm_local": modelo}, repetir=lambda f, a, **_k: f(*a))

    def executar(self, texto, acao, modelo=None):
        return motor.executar(self.skill, self.ctx(modelo), texto, {"acao": acao})


class TestAnotar(BaseAgenda):
    def test_anota_com_data_e_hora(self):
        modelo = ModeloFalso({"titulo": "Dentista", "data": "2026-11-26", "hora": "14:00"})
        resposta = self.executar("Marquei dentista pra quinta às 14h", "criar", modelo)
        self.assertEqual(resposta.texto, "Anotado na agenda: Dentista — qui, 26/11 às 14:00.")
        self.assertIn("Hoje é 2026-11-23 (segunda-feira)", modelo.prompts[0][0])
        self.assertEqual(self.db.executar_consulta("SELECT titulo, data, hora FROM compromissos"),
                         [("Dentista", "2026-11-26", "14:00")])

    def test_sem_data_pergunta_e_a_resposta_completa(self):
        modelo = ModeloFalso({"titulo": "Revisão da moto", "data": None, "hora": None},
                             {"titulo": "Revisão da moto", "data": "2026-11-28", "hora": "09:00"})
        resposta = self.executar("Agende a revisão da moto", "criar", modelo)
        self.assertIn("Para quando", resposta.texto)
        self.assertEqual(resposta.pendencia["titulo"], "Revisão da moto")
        final = motor.responder_pendencia(self.skill, self.ctx(modelo), "sábado às 9h", resposta.pendencia)
        self.assertEqual(final.texto, "Anotado na agenda: Revisão da moto — sáb, 28/11 às 09:00.")
        self.assertEqual(modelo.prompts[1][1], "Revisão da moto sábado às 9h")

    def test_valores_invalidos_do_modelo(self):
        modelo = ModeloFalso({"titulo": "Reunião", "data": "26/11/2026", "hora": "25:99"})
        self.assertIn("Para quando", self.executar("reunião", "criar", modelo).texto)
        modelo = ModeloFalso({"titulo": "Reunião", "data": "2026-11-27", "hora": "8:5"})
        self.assertEqual(self.executar("reunião", "criar", modelo).texto, "Anotado na agenda: Reunião — sex, 27/11.")
        modelo = ModeloFalso({"titulo": "", "data": "2026-11-27", "hora": None})
        self.assertIn("Não entendi", self.executar("??", "criar", modelo).texto)

    def test_data_no_passado_avisa(self):
        modelo = ModeloFalso({"titulo": "Pagar boleto", "data": "2026-11-20", "hora": None})
        self.assertIn("essa data já passou", self.executar("pagar boleto dia 20", "criar", modelo).texto)


class TestConsultar(BaseAgenda):
    def anotar(self, titulo, data, hora=None):
        self.executar(titulo, "criar", ModeloFalso({"titulo": titulo, "data": data, "hora": hora}))

    def test_periodos(self):
        hoje = SEGUNDA.date()
        casos = {
            "o que tenho pra hoje": (hoje, hoje),
            "e amanhã?": (date(2026, 11, 24), date(2026, 11, 24)),
            "e na quinta?": (date(2026, 11, 26), date(2026, 11, 26)),
            "dia 05/12": (date(2026, 12, 5), date(2026, 12, 5)),
            "minha agenda": (hoje, date(2026, 11, 29)),
            "agenda do mês": (hoje, date(2026, 12, 23)),
        }
        for texto, (inicio, fim) in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(self.roteiro.periodo(texto, hoje)[:2], (inicio, fim))

    def test_lista_em_ordem_e_mensagem_vazia(self):
        self.assertEqual(self.executar("amanhã", "consultar").texto, "Nenhum compromisso para amanhã (24/11).")
        self.anotar("Dentista", "2026-11-24", "14:00")
        self.anotar("Pagar a luz", "2026-11-24")
        self.anotar("Mercado", "2026-11-24", "09:30")
        self.anotar("Longe", "2026-12-20")
        resposta = self.executar("o que tenho amanhã?", "consultar")
        self.assertEqual(resposta.texto, "Seus compromissos para amanhã (24/11):\n- 09:30: Mercado\n- 14:00: Dentista\n- dia todo: Pagar a luz")
        semana = self.executar("minha agenda", "consultar").texto
        self.assertIn("ter, 24/11 às 09:30: Mercado", semana)
        self.assertNotIn("Longe", semana)


class TestCancelar(BaseAgenda):
    def test_cancela_o_ultimo_com_confirmacao(self):
        self.executar("x", "criar", ModeloFalso({"titulo": "Dentista", "data": "2026-11-26", "hora": "14:00"}))
        pedido = self.executar("Cancela o último compromisso", "corrigir")
        self.assertIn("Cancelar \"Dentista\"", pedido.texto)
        self.assertEqual(motor.responder_pendencia(self.skill, self.ctx(), "não", pedido.pendencia).texto, "Mantido na agenda.")
        self.assertEqual(len(self.db.executar_consulta("SELECT id FROM compromissos")), 1)
        self.assertIn("cancelado", motor.responder_pendencia(self.skill, self.ctx(), "sim", pedido.pendencia).texto)
        self.assertEqual(self.db.executar_consulta("SELECT id FROM compromissos"), [])
        self.assertIn("Não há compromisso", self.executar("cancela o compromisso", "corrigir").texto)


class TestAgendaNoApp(BaseAgenda):
    def test_fluxo_completo_pelo_runtime(self):
        modelo = ModeloFalso({"titulo": "Dentista", "data": "2026-11-26", "hora": "14:00"})
        for patcher in (mock.patch.object(app_main, "emitir_electron", lambda *_a, **_k: None),
                        mock.patch.object(app_main, "TEMPO_RETRY", 0),
                        mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False),
                        mock.patch.object(app_main, "LocalLLMProvider", lambda *a, **k: modelo)):
            patcher.start()
            self.addCleanup(patcher.stop)
        runtime = app_main.AssistenteRuntime()
        runtime.db_service = self.db
        runtime.ai_service = mock.Mock()
        runtime.memory_service = mock.Mock()
        self.assertEqual(runtime._processar_solicitacao("Me lembre do dentista quinta às 14h"),
                         "Anotado na agenda: Dentista — qui, 26/11 às 14:00.")
        self.assertIn("Dentista", runtime._processar_solicitacao("O que tenho na agenda esta semana?"))
        runtime.memory_service.salvar_memoria_longo_prazo.assert_not_called()  # agenda não vira memória


if __name__ == "__main__":
    unittest.main()
