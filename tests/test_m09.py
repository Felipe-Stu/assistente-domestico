"""Testes do M09: origem de cada registro de compra (tabela entradas)."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from app import main as app_main  # noqa: E402
from core.skills import Contexto, motor, obter_catalogo  # noqa: E402

TEXTO = "Comprei 2 litros de leite por 10 reais no Moreschi"


class BaseM09(fase1.BaseBanco):
    def entradas(self):
        return self.db.executar_consulta("SELECT id, tipo, canal, texto, resposta_json, modelo, versao_prompt, situacao FROM entradas")

    def preparar(self, assistente, canal="chat"):
        return assistente.preparar_compra(TEXTO, canal)


class TestOrigem(BaseM09):
    def test_registro_guarda_a_origem_ligada_a_compra(self):
        assistente = self.assistente({"compras": [fase1.compra()]})
        assistente.llm_provider.modelo = "gemma4:e4b"
        preparada = self.preparar(assistente, canal="voz")
        origem = preparada["origem"]
        self.assertEqual((origem["canal"], origem["texto"], origem["modelo"]), ("voz", TEXTO, "gemma4:e4b"))
        self.assertEqual(len(origem["versao_prompt"]), 8)
        self.assertEqual(json.loads(origem["resposta_json"])["compras"][0]["estabelecimento"], "Moreschi")

        assistente.registrar_compras(preparada["compras"], origem)
        ident, tipo, canal, texto, resposta, modelo, versao, situacao = self.entradas()[0]
        self.assertEqual((tipo, canal, texto, modelo, situacao), ("compra", "voz", TEXTO, "gemma4:e4b", "gravada"))
        self.assertEqual(self.db.executar_consulta_uma_linha("SELECT entrada_id FROM compras")[0], ident)

    def test_versao_do_prompt_nao_muda_com_a_data(self):
        a = self.preparar(self.assistente({"compras": [fase1.compra()]}))["origem"]["versao_prompt"]
        with mock.patch("services.shopping_assistant.datetime") as falso:
            falso.now.return_value.strftime.return_value = "2030-01-01"
            b = self.preparar(self.assistente({"compras": [fase1.compra()]}))["origem"]["versao_prompt"]
        self.assertEqual(a, b)

    def test_desfazer_mantem_a_origem_como_desfeita(self):
        assistente = self.assistente({"compras": [fase1.compra()]})
        preparada = self.preparar(assistente)
        assistente.registrar_compras(preparada["compras"], preparada["origem"])
        assistente.desfazer_ultimo_registro()
        self.assertEqual(self.contar("compras"), 0)
        self.assertEqual(self.entradas()[0][-1], "desfeita")

    def test_sem_origem_continua_gravando(self):
        assistente = self.assistente({"compras": [fase1.compra()]})
        assistente.registrar_compras(self.preparar(assistente)["compras"])
        self.assertEqual(self.contar("entradas"), 0)
        self.assertIsNone(self.db.executar_consulta_uma_linha("SELECT entrada_id FROM compras")[0])


class TestRoteiro(BaseM09):
    def ctx(self, assistente, canal="chat"):
        return Contexto(servicos={"shopping_assistant": assistente, "canal": canal}, repetir=lambda f, a, **_k: f(*a))

    def test_descartada_e_confirmada(self):
        skill = obter_catalogo().skill("compras")
        sem_mercado = {"compras": [{"estabelecimento": None, "itens": [fase1.item()]}]}
        assistente = self.assistente(sem_mercado)
        pedido = motor.executar(skill, self.ctx(assistente), "comprei leite por 10 reais", {"acao": "criar"})
        self.assertIn("origem", pedido.pendencia)
        motor.responder_pendencia(skill, self.ctx(assistente), "não", pedido.pendencia)
        pedido = motor.executar(skill, self.ctx(assistente, "voz"), "comprei leite por 10 reais", {"acao": "criar"})
        motor.responder_pendencia(skill, self.ctx(assistente), "sim", pedido.pendencia)
        self.assertEqual([(e[2], e[-1]) for e in self.entradas()], [("chat", "descartada"), ("voz", "gravada")])
        self.assertEqual(self.contar("compras"), 1)

    def test_pendencia_no_formato_antigo(self):
        skill = obter_catalogo().skill("compras")
        assistente = self.assistente()
        compras = [dict(fase1.compra(), data_compra="2026-11-23", valor_total_compra=10.0)]
        resposta = motor.responder_pendencia(skill, self.ctx(assistente), "sim", compras)
        self.assertIn("Compra registrada", resposta.texto)

    def test_nada_extraido_registra_descartada(self):
        skill = obter_catalogo().skill("compras")
        resposta = motor.executar(skill, self.ctx(self.assistente({"compras": []})), "comprei", {"acao": "criar"})
        self.assertIn("Nada foi registrado", resposta.texto)
        self.assertEqual(self.entradas()[0][-1], "descartada")


class TestCanalNoApp(unittest.TestCase):
    def test_voz_chega_como_canal(self):
        runtime = app_main.AssistenteRuntime()
        with mock.patch.object(runtime, "_executar_pipeline", return_value="ok"):
            runtime._processar_solicitacao("oi", canal="voz")
        self.assertEqual(runtime._contexto_skill().servicos["canal"], "voz")
        with mock.patch.object(runtime, "_executar_pipeline", return_value="ok"):
            runtime._processar_solicitacao("oi")
        self.assertEqual(runtime._contexto_skill().servicos["canal"], "chat")


if __name__ == "__main__":
    unittest.main()
