"""M28: cartão da compra aguardando confirmação (services/cartao_compra.py)."""
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from services import cartao_compra as cartao  # noqa: E402
from services.perguntas_compra import PEDIR_CONFIRMACAO  # noqa: E402
from services.shopping_assistant import ShoppingAssistant  # noqa: E402

COMPRA = {"estabelecimento": "Irmãos Muffato", "data_compra": "2026-11-22", "valor_total_compra": 50.7,
          "numero_nf": "62867", "serie_nf": "31", "observacao": "Natal",
          "itens": [{"produto": "arroz", "marca": "Tio João", "quantidade": 1, "unidade": "un", "valor_unitario": 26.9,
                     "valor_total": 26.9, "embalagem_quantidade": 5, "embalagem_unidade": "kg"},
                    {"produto": "queijo <b>", "quantidade": 2, "unidade": "un", "valor_unitario": 11.9, "valor_total": 23.8,
                     "observacao": "presente"}]}


class TestCartao(unittest.TestCase):
    def texto(self):
        return f"📄 Nota fiscal recebida (nota.html):\n{ShoppingAssistant.formatar_resumo([COMPRA])}\n\n{PEDIR_CONFIRMACAO}"

    def test_cartao_tira_o_resumo_do_texto_e_leva_os_dados(self):
        p = cartao.payload(self.texto(), ("compras", {"compras": [COMPRA], "origem": None, "perguntas": []}))
        self.assertEqual(p["text"], self.texto())                      # telas antigas, Telegram e voz seguem com o texto todo
        c = p["cartao"]
        self.assertTrue(c["confirmar"])
        self.assertEqual(c["texto"], f"📄 Nota fiscal recebida (nota.html):\n\n{PEDIR_CONFIRMACAO}")
        self.assertEqual((c["antes"], c["depois"]), ("📄 Nota fiscal recebida (nota.html):", PEDIR_CONFIRMACAO))
        compra = c["compras"][0]
        self.assertEqual((compra["loja"], compra["total_centavos"], compra["numero_nf"], compra["obs"]), ("Irmãos Muffato", 5070, "62867", "Natal"))
        self.assertEqual(compra["itens"][0]["produto"], "arroz Tio João (5 kg)")
        self.assertEqual((compra["itens"][1]["total_centavos"], compra["itens"][1]["obs"]), (2380, "presente"))

    def test_com_pergunta_pendente_os_botoes_sao_da_pergunta(self):
        c = cartao.montar(self.texto(), ("compras", {"compras": [COMPRA], "perguntas": [{"tipo": "loja"}]}))
        self.assertFalse(c["confirmar"])

    def test_sem_cartao_quando_nao_ha_compra_ou_resumo(self):
        self.assertNotIn("cartao", cartao.payload("Compra registrada.", None))
        self.assertIsNone(cartao.montar("Qual é a loja?", ("compras", {"compras": [COMPRA]})))
        self.assertIsNone(cartao.montar(self.texto(), ("compras", {"edicao": {}, "compras": [COMPRA]})))
        self.assertIsNone(cartao.montar(self.texto(), ("agenda", {"compras": [COMPRA]})))


if __name__ == "__main__":
    unittest.main()
