"""Testes do M10: corrigir compras já gravadas (com confirmação, contas refeitas e estoque acompanhando)."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from core.skills import Contexto, motor, obter_catalogo  # noqa: E402
from services import edicao_compra  # noqa: E402
from services.intent_router import rotear_por_regras  # noqa: E402


class BaseEdicao(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        self.assistente_compras = self.assistente()
        self.gravar("2026-11-10", "Irmãos Muffato", [("vinho tinto", 1, "un", 40.0, "bebidas"),
                                                     ("detergente", 2, "un", 3.0, "limpeza")])
        self.gravar("2026-11-20", "Moreschi", [("leite", 5, "litro", 5.0, "laticinios")])
        self.skill = obter_catalogo().skill("compras")

    def gravar(self, data, loja, itens):
        lista = [fase1.item(n, q, u, v, round(v * q, 2), categoria=c) for n, q, u, v, c in itens]
        self.assistente_compras.registrar_compras([dict(fase1.compra(*lista, estabelecimento=loja), data_compra=data,
                                                        valor_total_compra=sum(i["valor_total"] for i in lista))])

    def ctx(self, form=None, erro=None):
        modelo = mock.Mock(modelo="gemma4:e4b")
        if erro:
            modelo.gerar_json.side_effect = erro
        else:
            modelo.gerar_json.return_value = form or {}
        return Contexto(servicos={"db_service": self.db, "llm_local": modelo, "shopping_assistant": self.assistente_compras,
                                  "canal": "chat"}, repetir=lambda f, a, **_k: f(*a))

    def corrigir(self, texto, form=None, erro=None):
        ctx = self.ctx(form, erro)
        return ctx, motor.executar(self.skill, ctx, texto, {"acao": "corrigir"})

    def linha(self, sql, params=()):
        return self.db.executar_consulta_uma_linha(sql, params)


class TestRegras(unittest.TestCase):
    def test_frases_sem_modelo(self):
        r = edicao_compra.mudancas_por_regra
        self.assertEqual(r("o vinho custou 35"), [{"campo": "valor_total", "item": "vinho", "valor": "35"}])
        self.assertEqual(r("Renomeie c... para Moto Royal Enfield")[0]["campo"], "produto")
        self.assertEqual(r("eram 2 litros de leite e não 5"), [{"campo": "quantidade", "item": "leite", "valor": "2"}])
        self.assertEqual(r("a loja era o Moreschi")[0]["valor"], "Moreschi")
        self.assertEqual(r("tire o detergente da última compra")[0]["campo"], "remover_item")
        self.assertEqual(edicao_compra.ler_numero("R$ 1.234,50"), 1234.5)

    def test_roteamento(self):
        for frase in ("Corrija o valor do vinho", "renomeie c... para moto", "Na verdade o leite custou 4,99",
                      "tire o detergente da última compra"):
            self.assertEqual((rotear_por_regras(frase, None) or {}).get("acao"), "corrigir", frase)
        self.assertEqual(rotear_por_regras("desfazer última compra", None)["acao"], "corrigir")


class TestCorrecao(BaseEdicao):
    def test_valor_do_item_com_confirmacao(self):
        ctx, resposta = self.corrigir("O vinho custou 35, não 40",
                                      {"loja_da_compra": None, "alteracoes": [{"campo": "valor_total", "item": "vinho", "valor": "35"}]})
        self.assertIn("vinho tinto: valor R$ 40,00 → R$ 35,00", resposta.texto)
        self.assertIn("total R$ 41,00", resposta.texto)
        self.assertEqual(self.linha("SELECT total_centavos FROM compras WHERE id = 1"), (4600,))   # nada gravado ainda
        final = motor.responder_pendencia(self.skill, ctx, "sim", resposta.pendencia)
        self.assertIn("Compra corrigida", final.texto)
        self.assertEqual(self.linha("SELECT total_centavos, total_gasto FROM compras WHERE id = 1"), (4100, 41.0))
        self.assertEqual(self.linha("SELECT valor_total_centavos, valor_unitario_centavos FROM itens_compra WHERE produto = 'vinho tinto'"),
                         (3500, 3500))
        entrada = self.linha("SELECT tipo, situacao, versao_prompt, resposta_json FROM entradas WHERE tipo = 'edicao'")
        self.assertEqual(entrada[:3], ("edicao", "gravada", "edicao-v2"))
        self.assertEqual(json.loads(entrada[3])["antes"]["valor_total_compra"], 46.0)

    def test_quantidade_acerta_o_estoque(self):
        estoque = lambda: self.linha("SELECT quantidade_comprada FROM controle_consumo WHERE produto_nome LIKE 'leite%'")[0]
        self.assertEqual(estoque(), 5.0)
        ctx, resposta = self.corrigir("eram 2 litros de leite e não 5", erro=ConnectionError("ollama"))   # sem modelo: regra
        self.assertIn("quantidade 5 → 2", resposta.texto)
        motor.responder_pendencia(self.skill, ctx, "sim", resposta.pendencia)
        self.assertEqual(estoque(), 2.0)
        self.assertEqual(self.linha("SELECT total_centavos FROM compras WHERE id = 2"), (1000,))

    def test_renomear_loja_data_e_remover(self):
        form = {"loja_da_compra": "Muffato", "alteracoes": [
            {"campo": "produto", "item": "vinho tinto", "valor": "Vinho Benjamin Nieto"},
            {"campo": "data", "item": None, "valor": "13/11/2026"},
            {"campo": "remover_item", "item": "detergente", "valor": None},
            {"campo": "loja", "item": None, "valor": "Muffato Max"}]}
        ctx, resposta = self.corrigir("Na compra do Muffato: o vinho é Benjamin Nieto, foi dia 13/11/2026, tire o detergente e a loja é Muffato Max", form)
        self.assertIn("Correção da compra de 10/11/2026 · Irmãos Muffato", resposta.texto)
        motor.responder_pendencia(self.skill, ctx, "sim", resposta.pendencia)
        self.assertEqual(self.linha("SELECT data_compra, nome_comercio, total_centavos FROM compras WHERE id = 1"),
                         ("2026-11-13", "Muffato Max", 4000))
        self.assertEqual(self.db.executar_consulta("SELECT produto FROM itens_compra WHERE compra_id = 1"), [("vinho benjamin nieto",)])
        self.assertIsNotNone(self.linha("SELECT id FROM produtos WHERE chave = 'vinho benjamin nieto'"))

    def test_nao_mantem_e_erros_explicam(self):
        ctx, resposta = self.corrigir("o vinho custou 35", erro=ConnectionError("x"))
        final = motor.responder_pendencia(self.skill, ctx, "não", resposta.pendencia)
        self.assertIn("continua como estava", final.texto)
        self.assertEqual(self.linha("SELECT total_centavos FROM compras WHERE id = 1"), (4600,))
        _, resposta = self.corrigir("o picanha custou 80", erro=ConnectionError("x"))
        self.assertIn("Não achei a compra", resposta.texto)
        _, resposta = self.corrigir("corrija a compra", {"loja_da_compra": None, "alteracoes": []})
        self.assertIn("Nada foi alterado", resposta.texto)
        _, resposta = self.corrigir("tire o leite da última compra", erro=ConnectionError("x"))
        self.assertIn("único item", resposta.texto)

    def test_numero_inventado_pelo_modelo_e_descartado(self):
        _, resposta = self.corrigir("corrija o valor do vinho",
                                    {"loja_da_compra": None, "alteracoes": [{"campo": "valor_total", "item": "vinho", "valor": "35"}]})
        self.assertNotIn("R$ 35,00", resposta.texto)
        self.assertIn("Nada foi alterado", resposta.texto)

    def test_compra_por_numero_e_ultima_por_padrao(self):
        _, resposta = self.corrigir("na compra 1 o detergente custou 7", erro=ConnectionError("x"))
        self.assertIn("Irmãos Muffato", resposta.texto)
        _, resposta = self.corrigir("a loja era o Moreschi Centro", erro=ConnectionError("x"))
        self.assertIn("20/11/2026 · Moreschi", resposta.texto)   # sem pista: a última compra


if __name__ == "__main__":
    unittest.main()
