"""
Testes do SK3 (roadmap das skills): compras, estoque e agenda executam o roteiro da própria skill.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from app import main as app_main  # noqa: E402
from core.skills import Contexto, Resposta, SkillInvalidaError, carregar_catalogo, motor, obter_catalogo  # noqa: E402
from services import llm_provider, logger_service  # noqa: E402


class TestRoteirosDoProjeto(unittest.TestCase):
    def test_skills_com_roteiro(self):
        com_roteiro = {s.nome for s in obter_catalogo() if s.execucao == "roteiro"}
        self.assertEqual(com_roteiro, {"compras", "estoque", "agenda", "programacao"})
        for nome in com_roteiro:
            with self.subTest(skill=nome):
                self.assertTrue(callable(motor.carregar_roteiro(obter_catalogo().skill(nome)).executar))
        self.assertTrue(callable(motor.carregar_roteiro(obter_catalogo().skill("compras")).responder_pendencia))

    def test_estoque_e_agenda(self):
        estoque = obter_catalogo().skill("estoque")
        inventario = mock.Mock()
        inventario.consultar_estoque.return_value = "Você tem 2 litros de leite."
        ctx = Contexto(servicos={"inventory_assistant": inventario})
        self.assertEqual(motor.executar(estoque, ctx, "tem leite?", {"acao": "consultar"}).texto, "Você tem 2 litros de leite.")
        self.assertIn("apenas consultar", motor.executar(estoque, ctx, "acabou o leite", {"acao": "corrigir"}).texto)
        agenda = motor.executar(obter_catalogo().skill("agenda"), Contexto(), "me lembre", {"acao": "criar"})
        self.assertIn("agenda ainda não está disponível", agenda.texto)


class TestMotor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.pasta = Path(self._tmp.name)

    def criar(self, nome, roteiro=None, execucao="roteiro"):
        pasta = self.pasta / nome
        pasta.mkdir()
        (pasta / "SKILL.md").write_text(
            f"---\nname: {nome}\ndescription: Skill de exemplo para os testes do motor.\ncontextos: [{nome}]\n"
            f"estado: ativa\nprivacidade: local\nversao: 1\nexecucao: {execucao}\n---\n", encoding="utf-8")
        if roteiro is not None:
            (pasta / "roteiro.py").write_text(roteiro, encoding="utf-8")

    def test_roteiro_ausente_e_recusado(self):
        self.criar("sem-arquivo")
        with self.assertRaises(SkillInvalidaError):
            carregar_catalogo(self.pasta)

    def test_texto_vira_resposta_e_tipo_errado_e_recusado(self):
        self.criar("texto", "def executar(ctx, texto, decisao):\n    return 'ok ' + texto\n")
        self.criar("errado", "def executar(ctx, texto, decisao):\n    return 42\n")
        catalogo = carregar_catalogo(self.pasta)
        self.assertEqual(motor.executar(catalogo.skill("texto"), Contexto(), "x", {}).texto, "ok x")
        with self.assertRaises(SkillInvalidaError):
            motor.executar(catalogo.skill("errado"), Contexto(), "x", {})
        with self.assertRaises(SkillInvalidaError):
            motor.responder_pendencia(catalogo.skill("texto"), Contexto(), "sim", None)

    def test_servico_nao_entregue(self):
        with self.assertRaises(KeyError):
            Contexto(servicos={}).servico("banco")


class TestRuntimeComSkills(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.object(app_main, "emitir_electron", lambda *_a, **_k: None),
            mock.patch.object(app_main, "TEMPO_RETRY", 0),
            mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runtime = app_main.AssistenteRuntime()
        self.runtime.db_service = self.db
        self.runtime.ai_service = mock.Mock()
        self.runtime.ai_service.disponivel.return_value = True
        self.runtime.inventory_assistant = mock.Mock()
        self.runtime.context_retrieval = mock.Mock()
        self.runtime.context_retrieval.montar_contexto_recuperado.return_value = ""
        self.runtime.memory_service = mock.Mock()

    def test_uma_chamada_ao_modelo_por_compra(self):
        chamadas = []

        class LLMContador(fase1.LLMFalso):
            def gerar_json(self, **kwargs):
                chamadas.append(1)
                return super().gerar_json(**kwargs)

        self.runtime.shopping_assistant = fase1.ShoppingAssistant(
            self.db, llm_provider=LLMContador({"compras": [fase1.compra()]}), vector_store=self.vetor)
        with mock.patch.object(app_main, "orquestrar_requisicao", wraps=app_main.orquestrar_requisicao) as orq, \
                mock.patch("services.gemma_service.obter_provedor_local") as provedor_orquestrador:
            resposta = self.runtime._processar_solicitacao("Comprei leite por 10 reais no Moreschi")
        self.assertIn("Compra registrada", resposta)
        self.assertEqual(len(chamadas), 1)
        provedor_orquestrador.assert_not_called()  # resolvida por gatilho, sem o modelo do orquestrador
        self.assertEqual(orq.call_count, 1)

    def test_pendencia_vale_para_qualquer_skill(self):
        tmp = Path(tempfile.mkdtemp(dir=self._tmp.name))
        for skill in obter_catalogo():
            destino = tmp / skill.nome
            for arquivo in skill.pasta.rglob("*"):
                if arquivo.is_file() and "__pycache__" not in arquivo.parts:
                    alvo = destino / arquivo.relative_to(skill.pasta)
                    alvo.parent.mkdir(parents=True, exist_ok=True)
                    alvo.write_bytes(arquivo.read_bytes())
        (tmp / "lembretes").mkdir()
        (tmp / "lembretes" / "SKILL.md").write_text(
            "---\nname: lembretes\ndescription: Skill nova de teste que pede confirmação antes de salvar.\n"
            "contextos: [lembretes]\nestado: ativa\nprivacidade: local\nversao: 1\nexecucao: roteiro\n---\n", encoding="utf-8")
        (tmp / "lembretes" / "roteiro.py").write_text(
            "from core.skills.motor import Resposta\n"
            "def executar(ctx, texto, decisao):\n"
            "    return Resposta('Salvo o lembrete? (sim/não)', pendencia={'texto': texto})\n"
            "def responder_pendencia(ctx, texto, dados):\n"
            "    return Resposta('Lembrete salvo: ' + dados['texto'] if texto == 'sim' else 'Descartado.')\n",
            encoding="utf-8")
        catalogo = carregar_catalogo(tmp)
        decisao = {"dificuldade": "facil", "mudanca_de_contexto": False, "contexto": "lembretes", "acao": "criar"}
        with mock.patch.object(app_main, "obter_catalogo", return_value=catalogo), \
                mock.patch.object(app_main, "orquestrar_requisicao", return_value=decisao) as orq:
            self.assertIn("Salvo o lembrete?", self.runtime._processar_solicitacao("regar as plantas"))
            self.assertEqual(self.runtime.pendencia[0], "lembretes")
            self.assertIsNone(self.runtime.compra_pendente)
            self.assertEqual(self.runtime._processar_solicitacao("sim"), "Lembrete salvo: regar as plantas")
        self.assertIsNone(self.runtime.pendencia)
        self.assertEqual(orq.call_count, 1)  # a resposta "sim" não passou pelo orquestrador


if __name__ == "__main__":
    unittest.main()
