"""Testes do M08: dinheiro em centavos inteiros."""
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from services.dinheiro import formatar, formatar_reais, para_centavos, para_reais  # noqa: E402


class TestConversao(unittest.TestCase):
    def test_para_centavos(self):
        casos = {12.9: 1290, "27,90": 2790, "1.234,56": 123456, 0.1: 10, 2.675: 268, 2.665: 267, None: 0, "abc": 0, 53.08: 5308}
        for valor, esperado in casos.items():
            with self.subTest(valor=valor):
                self.assertEqual(para_centavos(valor), esperado)

    def test_soma_sem_erro_de_ponto_flutuante(self):
        self.assertNotEqual(0.1 + 0.2, 0.3)
        self.assertEqual(para_centavos(0.1) + para_centavos(0.2), para_centavos(0.3))

    def test_formatacao(self):
        self.assertEqual(formatar(1234567), "R$ 12.345,67")
        self.assertEqual(formatar(5), "R$ 0,05")
        self.assertEqual(formatar(-250), "-R$ 2,50")
        self.assertEqual(formatar_reais(53.075), "R$ 53,08")
        self.assertEqual(para_reais(1290), 12.9)


class TestNoBanco(fase1.BaseBanco):
    def test_grava_centavos_junto_dos_valores_antigos(self):
        itens = [fase1.item("arroz", 1, "un", 0.1, 0.1), fase1.item("feijao", 1, "un", 0.2, 0.2)]
        assistente = self.assistente({"compras": [fase1.compra(*itens)]})
        preparada = assistente.preparar_compra("comprei arroz e feijão no Moreschi")
        self.assertEqual(preparada["compras"][0]["valor_total_compra"], 0.3)
        assistente.registrar_compras(preparada["compras"])
        self.assertEqual(self.db.executar_consulta_uma_linha("SELECT total_gasto, total_centavos FROM compras"), (0.3, 30))
        self.assertEqual(self.db.executar_consulta("SELECT valor_unitario_centavos, valor_total_centavos FROM itens_compra ORDER BY id"),
                         [(10, 10), (20, 20)])


if __name__ == "__main__":
    unittest.main()
