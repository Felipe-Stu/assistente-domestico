"""Testes do M07: catálogo de produtos e categorias fechadas."""
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from services.esquemas import ESQUEMA_COMPRAS  # noqa: E402
from services.produtos_service import CATEGORIAS, chave_produto, normalizar_categoria  # noqa: E402
from core.skills import obter_catalogo  # noqa: E402


class TestCategorias(unittest.TestCase):
    def test_lista_fechada(self):
        self.assertEqual(len(CATEGORIAS), 15)
        self.assertIn("outros", CATEGORIAS)

    def test_normalizacao(self):
        casos = {"carne": "carnes", "Carnes": "carnes", "Guloseima": "doces_lanches", "passeios": "lazer",
                 "petshop": "pet", "Hortifrúti": "hortifruti", "Laticínios e frios": "laticinios",
                 "alimentação fora de casa": "alimentacao_fora", "confeitaria": "doces_lanches", "qualquer coisa": "outros",
                 None: "outros", "": "outros"}
        for valor, esperado in casos.items():
            with self.subTest(valor=valor):
                self.assertEqual(normalizar_categoria(valor), esperado)

    def test_esquema_e_prompt_usam_a_lista(self):
        item = ESQUEMA_COMPRAS["properties"]["compras"]["items"]["properties"]["itens"]["items"]
        self.assertEqual(item["properties"]["categoria"]["enum"], list(CATEGORIAS))
        prompt = obter_catalogo().skill("compras").prompt("extracao", data_atual="2026-11-23")
        for slug in CATEGORIAS:
            self.assertIn(slug, prompt)


class TestInferencia(unittest.TestCase):
    def test_nome_decide_na_migracao_e_quando_outros(self):
        from services.produtos_service import inferir_categoria
        self.assertEqual(inferir_categoria("chocolates kitkat", "confeitaria", nome_primeiro=True), "doces_lanches")
        self.assertEqual(inferir_categoria("chips elma", "alimentacao", nome_primeiro=True), "doces_lanches")
        self.assertEqual(inferir_categoria("almoço de família", "passeios", nome_primeiro=True), "alimentacao_fora")
        self.assertEqual(inferir_categoria("chiclete", "outros"), "doces_lanches")
        self.assertEqual(inferir_categoria("chiclete", "mercearia"), "mercearia")  # compra nova: vale a escolha do modelo
        self.assertEqual(inferir_categoria("parafuso", "xyz"), "outros")


class TestChave(unittest.TestCase):
    def test_chave(self):
        self.assertEqual(chave_produto("Coca-Cola 2L"), "coca cola")
        self.assertEqual(chave_produto("Leite Integral 1 litro"), "leite integral")
        self.assertEqual(chave_produto("Pães franceses"), "paes franceses")
        self.assertEqual(chave_produto("Arroz 5kg"), "arroz")


class TestCatalogoNoBanco(fase1.BaseBanco):
    def gravar(self, *itens):
        compras = [dict(fase1.compra(*itens), data_compra="2026-11-23", valor_total_compra=10.0)]
        self.assistente().registrar_compras(compras)

    def produtos(self):
        return self.db.executar_consulta("SELECT nome, chave, categoria FROM produtos ORDER BY id")

    def test_mesmo_produto_reconhecido(self):
        self.gravar(fase1.item("Leite 1L", categoria="laticinios"))
        self.gravar(fase1.item("leite", categoria="laticinios"), fase1.item("Coca-Cola 2L", categoria="bebida"))
        self.gravar(fase1.item("leites", categoria="laticinios"))
        self.assertEqual(self.produtos(), [("leite 1l", "leite", "laticinios"), ("coca-cola 2l", "coca cola", "bebidas")])
        ids = self.db.executar_consulta("SELECT DISTINCT produto_id FROM itens_compra WHERE produto LIKE 'leite%'")
        self.assertEqual(len(ids), 1)

    def test_validacao_converte_categoria_livre(self):
        assistente = self.assistente({"compras": [fase1.compra(fase1.item("chiclete", categoria="guloseima"))]})
        preparada = assistente.preparar_compra("comprei chiclete por 2 reais no Moreschi")
        self.assertEqual(preparada["compras"][0]["itens"][0]["categoria"], "doces_lanches")


if __name__ == "__main__":
    unittest.main()
