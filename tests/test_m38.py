"""M38: detalhe de uma compra e referência a "essa compra" (a compra em foco na conversa)."""
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

from test_m10 import BaseEdicao  # noqa: E402
from core.skills import Contexto, motor  # noqa: E402
from services import edicao_compra  # noqa: E402
from services.intent_router import rotear_por_regras  # noqa: E402


class TestDetalhe(BaseEdicao):
    def setUp(self):
        super().setUp()
        self.foco = {"id": None}

    def ctx(self, form=None, erro=None):
        base = super().ctx(form, erro)
        return Contexto(servicos=dict(base.servicos, foco_compra=self.foco), repetir=base.repetir)

    def consultar(self, texto, form=None):
        return motor.executar(self.skill, self.ctx(form), texto, {"acao": "consultar"})

    def id_de(self, loja):
        return self.linha("SELECT id FROM compras WHERE nome_comercio = ?", (loja,))[0]

    def test_ultima_compra_mostra_itens_e_cartao_mesmo_com_modelo_dizendo_listar(self):
        r = self.consultar("Consulte a última compra", {"tipo": "listar", "categoria": None, "loja": None, "produto": None})
        self.assertIn("Moreschi", r.texto)
        self.assertIn("leite", r.texto)
        self.assertNotIn("Muffato", r.texto)   # antes devolvia a lista de todas as compras (teste do usuário, 24/11)
        self.assertEqual(r.cartao["compras"][0]["loja"], "Moreschi")
        self.assertFalse(r.cartao["confirmar"])
        self.assertEqual(self.foco["id"], self.id_de("Moreschi"))

    def test_o_que_comprei_na_loja_e_itens_dessa_compra(self):
        r = self.consultar("o que eu comprei no muffato?", {})
        self.assertIn("vinho tinto", r.texto)
        self.assertEqual(self.foco["id"], self.id_de("Irmãos Muffato"))
        r = self.consultar("me cite os itens dessa compra", {"tipo": "listar"})
        self.assertIn("detergente", r.texto)          # "dessa compra" = a do Muffato, mesmo não sendo a última
        self.assertNotIn("leite", r.texto)

    def test_o_que_comprei_no_mes_continua_lista(self):
        r = self.consultar("o que comprei em novembro de 2026?", {"tipo": "listar", "categoria": None, "loja": None, "produto": None})
        self.assertIsNone(r.cartao)
        self.assertIn("Moreschi", r.texto)
        self.assertIn("Muffato", r.texto)

    def test_correcao_dessa_compra_usa_a_compra_em_foco(self):
        self.consultar("o que eu comprei no muffato?", {})
        r = motor.executar(self.skill, self.ctx({}), "tire o detergente dessa compra", {"acao": "corrigir"})
        self.assertIn("Irmãos Muffato", r.texto)
        self.assertIn("detergente", r.texto)
        self.assertEqual(r.pendencia["edicao"]["compra_id"], self.id_de("Irmãos Muffato"))

    def test_a_compra_da_loja_mostra_o_detalhe(self):
        ctx = self.ctx({})
        self.gravar("2026-11-24", "Max Atacadista", [("arroz", 1, "un", 25.0, "mercearia")])   # gravada fora do roteiro
        self.assertIsNone(self.foco["id"])
        r = motor.executar(self.skill, ctx, "me mostre a compra do max", {"acao": "consultar"})
        self.assertIn("arroz", r.texto)
        self.assertEqual(self.foco["id"], self.id_de("Max Atacadista"))

    def test_grafico_na_conversa_por_categoria(self):
        r = self.consultar("com o que mais gastei em novembro de 2026?",
                           {"tipo": "por_categoria", "categoria": None, "loja": None, "produto": None})
        g = r.cartao
        self.assertEqual(g["tipo"], "grafico")
        self.assertEqual(g["painel"], {"mes": "2026-11"})        # o atalho abre o painel nesse mês
        self.assertEqual(g["linhas"][0]["rotulo"], "Bebidas")     # nome da categoria, não a chave
        self.assertEqual(sum(l["centavos"] for l in g["linhas"]), g["total_centavos"])
        self.assertIn("Gastos por categoria", g["antes"])

    def test_regras_e_roteamento(self):
        self.assertEqual(edicao_compra.mudancas_por_regra("tire o detergente dessa compra")[0]["campo"], "remover_item")
        self.assertEqual((rotear_por_regras("tire o detergente dessa compra", None) or {}).get("acao"), "corrigir")
        for frase in ("me cite os itens dessa compra", "mostre a última compra", "detalhes da compra 3"):
            self.assertEqual((rotear_por_regras(frase, None) or {}).get("acao"), "consultar", frase)


if __name__ == "__main__":
    unittest.main()
