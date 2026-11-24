"""Observações em compras e itens, ajustes somados durante a confirmação e aviso de compra repetida."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
import test_m10  # noqa: E402
from core.skills import Contexto, motor  # noqa: E402
from services.consultas_service import ConsultasGastos, Filtro  # noqa: E402

FRASE_USUARIO = 'Adicione uma observação nessa compra, adicione na observação "JAVEP | Royal Enfield | Classic 650"'


class TestObservacoes(test_m10.BaseEdicao):
    def test_frase_do_usuario_sem_modelo(self):
        ctx, resposta = self.corrigir(FRASE_USUARIO, erro=ConnectionError("ollama"))
        self.assertIn("20/11/2026 · Moreschi", resposta.texto)   # "nessa compra" = a última registrada
        self.assertIn("📝 JAVEP | Royal Enfield | Classic 650", resposta.texto)
        motor.responder_pendencia(self.skill, ctx, "sim", resposta.pendencia)
        self.assertEqual(self.linha("SELECT observacao FROM compras WHERE id = 2"), ("JAVEP | Royal Enfield | Classic 650",))

    def test_observacao_num_item_e_apagar(self):
        form = {"loja_da_compra": "Muffato", "alteracoes": [{"campo": "observacao", "item": "vinho", "valor": "presente da Ana", "modo": "acrescentar"}]}
        ctx, resposta = self.corrigir('Na compra do Muffato, no vinho anote "presente da Ana"', form)
        self.assertIn("vinho tinto: 1 un × R$ 40,00 = R$ 40,00 📝 presente da Ana", resposta.texto)
        motor.responder_pendencia(self.skill, ctx, "sim", resposta.pendencia)
        self.assertEqual(self.linha("SELECT observacao FROM itens_compra WHERE produto = 'vinho tinto'"), ("presente da Ana",))
        self.assertEqual(self.linha("SELECT observacao FROM compras WHERE id = 1"), (None,))
        ctx, resposta = self.corrigir("apague a observação do item vinho da compra do Muffato", erro=ConnectionError("x"))
        motor.responder_pendencia(self.skill, ctx, "sim", resposta.pendencia)
        self.assertEqual(self.linha("SELECT observacao FROM itens_compra WHERE produto = 'vinho tinto'"), (None,))

    def test_texto_inventado_pelo_modelo_e_trocado_pela_regra(self):
        form = {"loja_da_compra": None, "alteracoes": [{"campo": "observacao", "item": None, "valor": "Moto nova", "modo": "acrescentar"}]}
        _, resposta = self.corrigir(FRASE_USUARIO, form)
        self.assertIn("JAVEP | Royal Enfield | Classic 650", resposta.texto)
        self.assertNotIn("Moto nova", resposta.texto)

    def test_pedidos_se_somam_enquanto_espera_o_sim(self):
        ctx, resposta = self.corrigir("o vinho custou 35", erro=ConnectionError("x"))
        resposta = motor.responder_pendencia(self.skill, ctx, 'adicione a observação "promoção de Natal"', resposta.pendencia)
        self.assertIn("vinho tinto: valor R$ 40,00 → R$ 35,00", resposta.texto)   # a primeira correção continua
        self.assertIn("observação da compra: promoção de Natal", resposta.texto)
        motor.responder_pendencia(self.skill, ctx, "sim", resposta.pendencia)
        self.assertEqual(self.linha("SELECT total_centavos, observacao FROM compras WHERE id = 1"), (4100, "promoção de Natal"))

    def test_consulta_mostra_a_observacao(self):
        ctx, resposta = self.corrigir('obs: "pago no Pix" na compra do Moreschi', erro=ConnectionError("x"))
        motor.responder_pendencia(self.skill, ctx, "sim", resposta.pendencia)
        texto = ConsultasGastos(self.db).listar(Filtro()).texto
        self.assertIn("Moreschi: R$ 25,00 (1 item(ns)) 📝 pago no Pix", texto)


class TestAjusteAntesDeGravar(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        import test_documentos
        self.docs = test_documentos
        self.compras = self.assistente()

    def ctx(self, documentos):
        modelo = mock.Mock(modelo="gemma4:e4b")
        modelo.gerar_json.side_effect = ConnectionError("ollama")
        return Contexto(servicos={"shopping_assistant": self.compras, "documentos": documentos, "db_service": self.db,
                                  "llm_local": modelo, "canal": "chat"}, repetir=lambda f, a, **_k: f(*a))

    def servico(self):
        from services.documentos_service import DocumentosService
        return DocumentosService(self.db, self.compras, Path(self._tmp.name) / "anexos")

    def test_observacao_durante_a_pergunta_do_nome_e_antes_do_sim(self):
        from core.skills import obter_catalogo
        skill = obter_catalogo().skill("compras")
        ctx = self.ctx(self.servico())
        resposta = motor.executar(skill, ctx, self.docs.TEXTO_NFE, {"acao": "criar"})
        self.assertIn("Qual produto você comprou", resposta.texto)
        resposta = motor.responder_pendencia(skill, ctx, FRASE_USUARIO, resposta.pendencia)
        self.assertIn("Ajustei", resposta.texto)
        self.assertIn("Qual produto você comprou", resposta.texto)   # a pergunta continua de pé
        resposta = motor.responder_pendencia(skill, ctx, "Moto Royal Enfield Classic 650", resposta.pendencia)
        self.assertIn("📝 JAVEP | Royal Enfield | Classic 650", resposta.texto)
        motor.responder_pendencia(skill, ctx, "sim", resposta.pendencia)
        self.assertEqual(self.db.executar_consulta_uma_linha("SELECT c.observacao, i.produto FROM compras c JOIN itens_compra i ON i.compra_id = c.id"),
                         ("JAVEP | Royal Enfield | Classic 650", "moto royal enfield classic 650"))

    def test_aviso_de_compra_repetida(self):
        from core.skills import obter_catalogo
        skill = obter_catalogo().skill("compras")
        ctx = self.ctx(self.servico())
        resposta = motor.executar(skill, ctx, self.docs.TEXTO_NFE, {"acao": "criar"})
        resposta = motor.responder_pendencia(skill, ctx, "pular", resposta.pendencia)
        motor.responder_pendencia(skill, ctx, "sim", resposta.pendencia)
        visao = mock.Mock(modelo="gemma3:4b")
        visao.gerar_json_imagem.return_value = {"compras": [{"estabelecimento": "VAGA MOTORS", "data_compra": "2026-11-24",
            "valor_total_compra": 32990.0, "itens": [{"produto": "C.C. 1000", "quantidade": 1, "unidade": "un",
                                                      "valor_unitario": 32990.0, "valor_total": 32990.0, "categoria": "outros"}]}]}
        from services.documentos_service import DocumentosService
        foto = Path(self._tmp.name) / "moto.png"
        foto.write_bytes(b"png")
        preparada = DocumentosService(self.db, self.compras, Path(self._tmp.name) / "anexos", llm_visao=visao).importar(foto, "app")
        self.assertTrue(any("Pode ser repetida: a compra #1 (06/11/2026" in d for d in preparada["duvidas"]))


if __name__ == "__main__":
    unittest.main()
