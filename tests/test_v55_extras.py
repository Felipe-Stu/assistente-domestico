"""V5.5: resumo do painel (I06), dados da demonstração (I07), consultas do servidor MCP (I05) e formatação (M28)."""
import os
import shutil
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402


def gravar(assistente, data, loja, itens):
    lista = [fase1.item(n, q, "un", v, round(v * q, 2), categoria=c) for n, q, v, c in itens]
    assistente.registrar_compras([dict(fase1.compra(*lista, estabelecimento=loja), data_compra=data,
                                       valor_total_compra=sum(i["valor_total"] for i in lista))])


class TestPainelEMcp(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        a = self.assistente()
        gravar(a, "2026-10-05", "Muffato", [("vinho", 1, 40.0, "bebidas"), ("detergente", 2, 3.0, "limpeza")])
        gravar(a, "2026-11-10", "Moreschi", [("arroz", 1, 25.0, "mercearia")])

    def test_resumo_do_painel(self):
        from services.consultas_service import resumo_para_painel
        r = resumo_para_painel(self.db, 3, hoje=date(2026, 11, 24))
        self.assertEqual([m["mes"] for m in r["por_mes"]], ["2026-09", "2026-10", "2026-11"])
        self.assertEqual([m["centavos"] for m in r["por_mes"]], [0, 4600, 2500])
        self.assertEqual((r["total_centavos"], r["compras"]), (7100, 2))
        self.assertEqual(r["por_categoria"][0], {"categoria": "Bebidas", "centavos": 4000})
        self.assertEqual(r["ultimas"][0]["loja"], "Moreschi")

    def test_detalhe_categorias_grupos_e_itens(self):
        from services.consultas_service import detalhe_gastos
        gravar(self.assistente(), "2026-11-12", "Moreschi", [("peito de frango", 1, 20.0, "carnes"), ("picanha bovina", 1, 80.0, "carnes"),
                                                            ("filé de tilápia", 1, 50.0, "carnes"), ("coxa de frango", 2, 10.0, "carnes")])
        hoje = date(2026, 11, 24)
        r = detalhe_gastos(self.db, mes="2026-11", hoje=hoje)
        self.assertEqual(r["nivel"], "categorias")
        self.assertEqual(r["trilha"][0]["rotulo"], "Novembro de 2026")
        self.assertEqual(r["linhas"][0]["chave"], "carnes")
        self.assertEqual((r["total_centavos"], r["compras"]), (19500, 2))
        r = detalhe_gastos(self.db, mes="2026-11", categoria="carnes", hoje=hoje)
        self.assertEqual([(l["rotulo"], l["centavos"], l["itens"]) for l in r["linhas"]],
                         [("Bovina", 8000, 1), ("Peixes e frutos do mar", 5000, 1), ("Frango", 4000, 2)])
        r = detalhe_gastos(self.db, mes="2026-11", categoria="carnes", grupo="Frango", hoje=hoje)
        self.assertEqual(r["nivel"], "itens")
        self.assertEqual([t["rotulo"] for t in r["trilha"]], ["Novembro de 2026", "Carnes e peixes", "Frango"])
        self.assertEqual(sorted(i["produto"] for i in r["itens"]), ["coxa de frango", "peito de frango"])
        # sem mês: período inteiro; outubro entra
        r = detalhe_gastos(self.db, meses=3, hoje=hoje)
        self.assertEqual(r["total_centavos"], 24100)
        self.assertEqual(detalhe_gastos(self.db, mes="2026-09", hoje=hoje)["linhas"], [])

    def test_subgrupos(self):
        from services.consultas_service import subgrupo
        self.assertEqual(subgrupo("Contra-filé bovino", "carnes"), "Bovina")
        self.assertEqual(subgrupo("Linguiça toscana", "carnes"), "Suína")
        self.assertEqual(subgrupo("refrigerante guaraná 2L", "bebidas"), "Refrigerantes")
        self.assertEqual(subgrupo("banana prata", "hortifruti"), "Frutas")
        self.assertEqual(subgrupo("detergente 500ml", "limpeza"), "Detergente 500ml")

    def test_consultas_do_mcp(self):
        import app.mcp_casa as mcp_casa
        with mock.patch.object(mcp_casa, "_db", self.db):
            self.assertIn("R$ 6,00", mcp_casa.total_de_gastos(categoria="limpeza"))
            self.assertIn("Muffato", mcp_casa.listar_compras())
            self.assertIn("Vinho", mcp_casa.preco_de_produto("vinho"))
            with mock.patch("services.periodos.date") as d:
                d.today.return_value = date(2026, 11, 24)
                d.side_effect = lambda *a, **k: date(*a, **k)
                self.assertIn("Gastou mais em outubro", mcp_casa.comparar_periodos("outubro", "novembro"))
        self.assertEqual(len(mcp_casa.FERRAMENTAS), 6)


class TestDemo(unittest.TestCase):
    def test_compras_ficticias_sao_estaveis_e_inventadas(self):
        antes = os.environ.get("ASSISTENTE_DEMO")
        sys.path.insert(0, str(ROOT_DIR / "scripts"))
        try:
            import criar_demo
        finally:
            if antes is None:
                os.environ.pop("ASSISTENTE_DEMO", None)
            else:
                os.environ["ASSISTENTE_DEMO"] = antes
        a = criar_demo.compras_ficticias(hoje=date(2026, 11, 24))
        b = criar_demo.compras_ficticias(hoje=date(2026, 11, 24))
        self.assertEqual(a, b)                              # mesma semente, mesmos dados (vídeos repetíveis)
        self.assertGreater(len(a), 50)
        self.assertTrue({c["estabelecimento"] for c in a} <= set(criar_demo.LOJAS))
        arroz = [i for c in a for i in c["itens"] if i["produto"].startswith("arroz")]
        self.assertTrue(arroz and all(i["unidade"] == "un" for i in arroz))

    def test_demo_usa_pastas_proprias(self):
        codigo = ("import core.config as c; print(c.DEMO, c.DB_DIR.name, c.DB_PATH.parent.name, c.TOKEN_LOCAL_ARQUIVO.parent.name, "
                  "repr(c.TELEGRAM_BOT_TOKEN), c.ANEXOS_DIR.parent.name)")
        env = dict(os.environ, ASSISTENTE_DEMO="1", TELEGRAM_BOT_TOKEN="123:abc")
        saida = subprocess.run([sys.executable, "-c", codigo], cwd=ROOT_DIR, env=env, capture_output=True, text=True).stdout.split()
        self.assertEqual(saida, ["True", "demo", "demo", "database", "''", "demo"])


@unittest.skipUnless(shutil.which("node"), "node ausente")
class TestFormatacao(unittest.TestCase):
    def test_markdown_seguro_e_botoes(self):
        script = ("const F=require('./web/formatar.js');"
                  "console.log(F.formatarMensagem('**ok**\\n- a\\n<script>x</script>'));"
                  "console.log(JSON.stringify(F.botoesDeResposta('Responda \"sim\" ou \"não\"')));")
        saida = subprocess.run(["node", "-e", script], cwd=ROOT_DIR, capture_output=True, text=True).stdout
        self.assertIn("<strong>ok</strong>", saida)
        self.assertIn("<li>a</li>", saida)
        self.assertIn("&lt;script&gt;", saida)
        self.assertNotIn("<script>", saida)
        self.assertIn('"envio":"sim"', saida)


if __name__ == "__main__":
    unittest.main()
