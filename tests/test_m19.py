"""Testes do M19: consultas de gastos (períodos por regra, consultas prontas, formulário do modelo)."""
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from core.skills import Contexto, motor, obter_catalogo  # noqa: E402
from services.consultas_service import ConsultasGastos, Filtro  # noqa: E402
from services.periodos import encontrar_periodos  # noqa: E402

HOJE = date(2026, 11, 23)


class TestPeriodos(unittest.TestCase):
    def datas(self, texto):
        return [(p.inicio_iso, p.fim_iso) for p in encontrar_periodos(texto, HOJE)]

    def test_frases_comuns(self):
        self.assertEqual(self.datas("compras feitas em 2026"), [("2026-01-01", "2026-12-31")])
        self.assertEqual(self.datas("quanto gastei mês passado"), [("2026-10-01", "2026-10-31")])
        self.assertEqual(self.datas("neste mês"), [("2026-11-01", "2026-11-23")])
        self.assertEqual(self.datas("semana passada"), [("2026-11-16", "2026-11-22")])
        self.assertEqual(self.datas("nos últimos 30 dias"), [("2026-10-25", "2026-11-23")])
        self.assertEqual(self.datas("de 01/10 a 15/11"), [("2026-10-01", "2026-11-15")])
        self.assertEqual(self.datas("em março de 2025"), [("2025-03-01", "2025-03-31")])
        self.assertEqual(self.datas("em dezembro"), [("2025-12-01", "2025-12-31")])   # mês ainda não chegou: ano passado

    def test_dois_periodos_e_falsos_positivos(self):
        self.assertEqual(self.datas("gastei mais em outubro ou novembro?"),
                         [("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-30")])
        self.assertEqual(self.datas("quanto paguei no vinho"), [])
        self.assertEqual(self.datas("vou ao mar amanhã, comprei dez pães"), [])


class BaseConsultas(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        assistente = self.assistente()
        compras = [
            ("2026-10-05", "Muffato", [("vinho", 1, 40.0, "bebidas"), ("detergente", 2, 3.0, "limpeza")]),
            ("2026-10-20", "Moreschi", [("arroz 5kg", 1, 25.0, "mercearia")]),
            ("2026-11-10", "Irmãos Muffato", [("vinho tinto", 1, 35.0, "bebidas"), ("sabão em pó", 1, 20.0, "limpeza")]),
            ("2025-12-01", "Moreschi", [("arroz", 1, 22.0, "mercearia")]),
        ]
        for data, loja, itens in compras:
            lista = [fase1.item(nome, q, "un", v, v * q, categoria=cat) for nome, q, v, cat in itens]
            assistente.registrar_compras([dict(fase1.compra(*lista, estabelecimento=loja), data_compra=data)])
        self.consultas = ConsultasGastos(self.db)

    def periodo(self, texto):
        return encontrar_periodos(texto, HOJE)


class TestConsultas(BaseConsultas):
    def test_listar_e_total(self):
        r = self.consultas.listar(Filtro(periodo=self.periodo("em 2026")[0]))
        self.assertEqual(r.dados["total_centavos"], 4000 + 600 + 2500 + 3500 + 2000)
        self.assertIn("3 compra(s) em 2026", r.texto)
        self.assertTrue(r.texto.splitlines()[1].startswith("- 10/11/2026"))   # mais recente primeiro
        r = self.consultas.total(Filtro(periodo=self.periodo("outubro")[0], categoria="limpeza"))
        self.assertEqual(r.dados["total_centavos"], 600)
        self.assertIn("R$ 6,00", r.texto)

    def test_loja_sem_acento_e_parcial(self):
        r = self.consultas.total(Filtro(loja="muffato"))
        self.assertEqual(r.dados, {"total_centavos": 4000 + 600 + 3500 + 2000, "compras": 2})

    def test_por_categoria_e_por_loja(self):
        r = self.consultas.por_categoria(Filtro(periodo=self.periodo("2026")[0]))
        self.assertEqual(r.dados["ranking"][0], ("bebidas", 7500))
        r = self.consultas.por_loja(Filtro())
        self.assertEqual(r.dados["ranking"][0][0], "Irmãos Muffato")

    def test_preco_produto(self):
        r = self.consultas.preco_produto(Filtro(produto="vinho"))
        self.assertEqual((r.dados["itens"], r.dados["ultimo_centavos"], r.dados["menor_centavos"], r.dados["media_centavos"]),
                         (2, 3500, 3500, 3750))
        self.assertIn("Irmãos Muffato", r.texto)
        self.assertIn("Não encontrei", self.consultas.preco_produto(Filtro(produto="picanha")).texto)

    def test_comparar(self):
        r = self.consultas.comparar(Filtro(categoria="bebidas"), self.periodo("outubro ou novembro"))
        self.assertEqual(r.dados["totais"], [("em outubro", 4000), ("em novembro", 3500)])
        self.assertIn("Gastou mais em outubro: R$ 5,00", r.texto)


class TestSkill(BaseConsultas):
    def perguntar(self, texto, form=None, erro=None):
        modelo = mock.Mock()
        if erro:
            modelo.gerar_json.side_effect = erro
        else:
            modelo.gerar_json.return_value = form
        ctx = Contexto(servicos={"db_service": self.db, "llm_local": modelo, "shopping_assistant": self.assistente()},
                       repetir=lambda f, a, **_k: f(*a))
        with mock.patch("services.periodos.date") as data:
            data.today.return_value = HOJE
            data.side_effect = lambda *a, **k: date(*a, **k)
            return motor.executar(obter_catalogo().skill("compras"), ctx, texto, {"acao": "consultar"}).texto

    def test_pergunta_do_usuario(self):
        texto = self.perguntar("Me informe as compras feitas em 2026",
                               {"tipo": "listar", "categoria": None, "loja": None, "produto": None})
        self.assertIn("3 compra(s) em 2026", texto)

    def test_loja_inventada_pelo_modelo_e_ignorada(self):
        texto = self.perguntar("quanto gastei em outubro?", {"tipo": "total", "categoria": None, "loja": "Muffato", "produto": None})
        self.assertIn("R$ 71,00", texto)   # outubro inteiro, não só o Muffato

    def test_sem_modelo_a_regra_decide(self):
        texto = self.perguntar("gastei mais em outubro ou novembro?", erro=ConnectionError("ollama"))
        self.assertIn("Comparação", texto)
        texto = self.perguntar("quanto gastei este mês?", erro=ConnectionError("ollama"))
        self.assertIn("R$ 55,00", texto)

    def test_comparar_sem_dois_periodos_vira_total(self):
        texto = self.perguntar("gastei mais em novembro?", {"tipo": "comparar", "categoria": None, "loja": None, "produto": None})
        self.assertIn("Você gastou R$ 55,00 em novembro", texto)


class TestAvaliacao(unittest.TestCase):
    def test_conferir_formulario(self):
        sys.path.insert(0, str(ROOT_DIR / "scripts"))
        import avaliar
        caso = {"tipo": "total", "categoria": "limpeza", "loja": "moreschi", "produto": None}
        certo = avaliar.conferir_consulta(caso, {"tipo": "total", "categoria": "limpeza", "loja": "Moreschi", "produto": None})
        self.assertTrue(all(certo.values()))
        errado = avaliar.conferir_consulta(caso, {"tipo": "listar", "categoria": None, "loja": "Muffato", "produto": "sabão"})
        self.assertEqual(errado, {"tipo": False, "categoria": False, "loja": False, "produto": False})
        casos = avaliar.ler_jsonl(avaliar.ARQUIVO_CONSULTAS)
        self.assertGreaterEqual(len(casos), 15)


if __name__ == "__main__":
    unittest.main()
