"""Número (Código NF), série (Série NF) e emissão (data e hora da compra) da nota fiscal; desconto lido na foto."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
import test_documentos  # noqa: E402
from test_m34 import Visao  # noqa: E402
from services import nfce_service  # noqa: E402
from services.documentos_service import DocumentosService  # noqa: E402

# Transcrição no formato que o qwen2.5vl:7b devolveu para a NFC-e do Muffato (24/11/2026)
TRANSCRICAO_MUFFATO = """IRMAOS MUFFATO E CIA LTDA
CNPJ: 76.430.438/0097-13
VINHO BENJAMIM NIETO (Código: 97029) Qtde.:2 UN: Un Vl. Unit.: 49,9 Vl. Total 99,80
RODO PRAT CSA UN (Código: 300429) Qtde.:1 UN: Un Vl. Unit.: 46,75 Vl. Total 46,75
LIMP TRIEX 500ML (Código: 304016) Qtde.:1 UN: Un Vl. Unit.: 3,28 Vl. Total 3,28
Qtd. total de itens: 3
Valor total R$: 149,83
Descontos R$: 43,30
Valor a pagar R$: 106,53
Forma de pagamento: Cartão de Crédito 106,53
EMISSÃO NORMAL
Número: 62867 Série: 31 Emissão: 13/11/2026 16:10:51 - Via Consumidor
CONSUMIDOR - CPF: 123.456.789-09
Chave de acesso:
3526 1176 4304 3800 9713 6503 1000 0628 6710 3107 0694"""


class TestIdentificacao(unittest.TestCase):
    def test_formatos(self):
        self.assertEqual(nfce_service.identificacao("Número: 62867 Série: 31 Emissão: 13/11/2026 16:10:51 - Via Consumidor"),
                         {"numero_nf": "62867", "serie_nf": "31", "emissao": "2026-11-13T16:10:51", "data_compra": "2026-11-13"})
        self.assertEqual(nfce_service.identificacao(test_documentos.TEXTO_NFE)["emissao"], "2026-11-06T15:23:12")
        self.assertEqual(nfce_service.identificacao("Número NF-e 000.000.758 Série 1")["numero_nf"], "758")

    def test_via_consumidor_fica_e_cpf_sai(self):
        texto = nfce_service.ocultar_consumidor(TRANSCRICAO_MUFFATO)
        self.assertIn("Emissão: 13/11/2026 16:10:51 - Via Consumidor", texto)
        self.assertNotIn("123.456.789-09", texto)

    def test_leitores_exatos(self):
        html = nfce_service.ler_nfce(test_documentos.NOTA.read_text(encoding="utf-8", errors="replace"))
        self.assertEqual((html["numero_nf"], html["serie_nf"], html["data_compra"]), ("62867", "31", "2026-11-13"))
        nfe = nfce_service.ler_nfe_texto(test_documentos.TEXTO_NFE)
        self.assertEqual((nfe["numero_nf"], nfe["serie_nf"]), ("758", "1"))


class TestFotoMuffato(fase1.BaseBanco):
    def test_emissao_vira_data_desconto_aplicado_e_tudo_gravado(self):
        compras = self.assistente()
        foto = Path(self._tmp.name) / "NF Teste 2.png"
        foto.write_bytes(b"png")
        docs = DocumentosService(self.db, compras, Path(self._tmp.name) / "anexos", llm_visao=Visao(TRANSCRICAO_MUFFATO))
        # caminho do modelo de texto (gemma4): data de hoje e sem desconto, como no teste do usuário
        extraida = {"compras": [dict(fase1.compra(
            fase1.item("VINHO BENJAMIM NIETO", 2, "un", 49.9, 99.8), fase1.item("RODO PRAT CSA UN", 1, "un", 46.75, 46.75),
            fase1.item("LIMP TRIEX 500ML", 1, "un", 3.28, 3.28), estabelecimento="IRMAOS MUFFATO E CIA LTDA"),
            data_compra="2026-11-24", valor_total_compra=149.83)], "duvidas": [], "origem": {}}
        with mock.patch.object(nfce_service, "parece_nfce_texto", return_value=False), \
                mock.patch.object(compras, "preparar_compra", return_value=extraida):
            preparada = docs.importar(foto, "app")
        compra = preparada["compras"][0]
        self.assertEqual((compra["data_compra"], compra["numero_nf"], compra["serie_nf"], compra["emissao"]),
                         ("2026-11-13", "62867", "31", "2026-11-13T16:10:51"))
        self.assertEqual((compra["valor_total_compra"], compra["desconto"]), (106.53, 43.3))
        resumo = docs.resumo(preparada)
        self.assertIn("🧾 NF 62867 série 31, emitida em 13/11/2026 às 16:10", resumo)
        self.assertIn("Desconto de R$ 43,30", resumo)
        compras.registrar_compras(preparada["compras"], preparada["origem"])
        self.assertEqual(self.db.executar_consulta_uma_linha(
            "SELECT data_compra, numero_nf, serie_nf, emissao, total_centavos FROM compras"),
            ("2026-11-13", "62867", "31", "2026-11-13T16:10:51", 10653))

    def test_transcricao_no_formato_da_nfce_usa_o_leitor_exato(self):
        compras = self.assistente()
        foto = Path(self._tmp.name) / "nf.png"
        foto.write_bytes(b"png")
        docs = DocumentosService(self.db, compras, Path(self._tmp.name) / "anexos", llm_visao=Visao(TRANSCRICAO_MUFFATO))
        compra = docs.importar(foto, "app")["compras"][0]
        self.assertEqual((compra["data_compra"], compra["numero_nf"], compra["valor_total_compra"]), ("2026-11-13", "62867", 106.53))


if __name__ == "__main__":
    unittest.main()
