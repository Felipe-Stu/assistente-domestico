"""Testes da entrada de documentos: NFC-e (HTML), PDF, foto, pasta de entrada e Telegram."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from app import main as app_main  # noqa: E402
from services import llm_provider  # noqa: E402
from services.documentos_service import DocumentoError, DocumentosService  # noqa: E402
from services.inventory_assistant import InventoryAssistant  # noqa: E402
from services.nfce_service import distribuir_desconto, embalagem_pelo_nome, ler_nfce, nome_estabelecimento  # noqa: E402
from services.pasta_entradas_service import PastaEntradas  # noqa: E402
from services.telegram_service import TelegramService  # noqa: E402

NOTA = ROOT_DIR / "tests" / "dados" / "nfce_sp_exemplo.html"


class LLMNomes:
    modelo = "gemma4:e4b"

    def __init__(self, erro=None):
        self.erro = erro

    def gerar_json(self, **_k):
        if self.erro:
            raise self.erro
        return {"itens": [{"codigo": "97029", "produto": "Vinho Benjamin Nieto", "categoria": "bebidas"},
                          {"codigo": "300429", "produto": "Rodo prático casa", "categoria": "limpeza"},
                          {"codigo": "304016", "produto": "Limpador Triex 500 ml", "categoria": "limpeza"}]}


class TestLeitorNFCe(unittest.TestCase):
    def test_le_a_nota_real(self):
        nota = ler_nfce(NOTA.read_text(encoding="utf-8"))
        self.assertEqual((nota["estabelecimento"], nota["data_compra"], nota["forma_pagamento"]),
                         ("Irmaos Muffato", "2026-11-13", "Cartão de Crédito"))
        self.assertEqual((nota["valor_bruto"], nota["desconto"], nota["valor_total_compra"]), (149.83, 43.3, 106.53))
        self.assertEqual(len(nota["chave_acesso"]), 44)
        self.assertEqual([(i["codigo"], i["quantidade"], i["valor_bruto"], i["valor_total"]) for i in nota["itens"]],
                         [("97029", 2.0, 99.8, 70.96), ("300429", 1.0, 46.75, 33.24), ("304016", 1.0, 3.28, 2.33)])
        self.assertEqual(round(sum(i["valor_total"] for i in nota["itens"]), 2), 106.53)

    def test_nao_le_dados_do_consumidor(self):
        nota = json.dumps(ler_nfce(NOTA.read_text(encoding="utf-8")), ensure_ascii=False)
        self.assertNotIn("CPF", nota)
        self.assertNotIn("000.000.000-00", nota)
        self.assertNotIn("Cliente NFCe", nota)

    def test_auxiliares(self):
        self.assertEqual(distribuir_desconto([9980, 4675, 328], 4330), [7096, 3324, 233])
        self.assertEqual(sum(distribuir_desconto([100, 100, 100], 100)), 200)
        self.assertEqual(embalagem_pelo_nome("LIMP TRIEX 500ML"), (0.5, "litro"))
        self.assertEqual(embalagem_pelo_nome("ARROZ TIO JOAO 5KG"), (5.0, "kg"))
        self.assertEqual(embalagem_pelo_nome("RODO PRAT"), (None, None))
        self.assertEqual(nome_estabelecimento("SUPERMERCADO TAUSTE S/A"), "Supermercado Tauste")

    def test_arquivo_que_nao_e_nota(self):
        with self.assertRaises(ValueError):
            ler_nfce("<html><body>outra coisa</body></html>")


class BaseDocs(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        self.anexos = Path(self._tmp.name) / "Anexos"
        self.entrada = Path(self._tmp.name) / "Entradas"
        self.entrada.mkdir()
        self.compras = self.assistente()

    def servico(self, nomes=None, visao=None):
        return DocumentosService(self.db, self.compras, self.anexos, llm_nomes=nomes, llm_visao=visao)

    def copiar_nota(self, nome="nota.html"):
        destino = self.entrada / nome
        destino.write_bytes(NOTA.read_bytes())
        return destino


class TestImportacao(BaseDocs):
    def test_nfce_com_nomes_legiveis_e_confirmacao(self):
        docs = self.servico(nomes=LLMNomes())
        preparada = docs.importar(self.copiar_nota(), "pasta")
        compra = preparada["compras"][0]
        self.assertEqual([(i["produto"], i["categoria"]) for i in compra["itens"]],
                         [("vinho benjamin nieto", "bebidas"), ("rodo prático casa", "limpeza"), ("limpador triex 500 ml", "limpeza")])
        self.assertEqual(compra["valor_total_compra"], 106.53)
        self.assertIn("Desconto de R$ 43,30", docs.resumo(preparada))
        origem = preparada["origem"]
        self.assertEqual((origem["tipo"], origem["canal"], origem["versao_prompt"]), ("nota", "pasta", "nfce-v1"))
        self.assertTrue(Path(origem["anexo"]).is_file())
        self.compras.registrar_compras(preparada["compras"], origem)
        self.assertEqual(self.db.executar_consulta_uma_linha("SELECT total_centavos, data_compra, nome_comercio FROM compras"),
                         (10653, "2026-11-13", "Irmaos Muffato"))
        with self.assertRaisesRegex(DocumentoError, "já foi registrada"):
            docs.importar(self.copiar_nota("de-novo.html"), "pasta")

    def test_sem_ollama_ficam_os_nomes_do_cupom(self):
        compra = self.servico(nomes=LLMNomes(erro=ConnectionError())).importar(self.copiar_nota(), "pasta")["compras"][0]
        self.assertEqual(compra["itens"][2]["produto"], "limp triex 500ml")

    def test_formatos(self):
        docs = self.servico()
        (self.entrada / "planilha.xlsx").write_bytes(b"x")
        with self.assertRaisesRegex(DocumentoError, "Formato não suportado"):
            docs.importar(self.entrada / "planilha.xlsx")
        (self.entrada / "foto.jpg").write_bytes(b"jpg")
        with self.assertRaisesRegex(DocumentoError, "modelo para ler imagens"):
            docs.importar(self.entrada / "foto.jpg")

    def test_foto_passa_pela_revisao(self):
        visao = mock.Mock(modelo="gemma4:e4b")
        visao.gerar_json_imagem.return_value = {"compras": [fase1.compra(fase1.item("pão", 6, "un", 0.8, 4.8, categoria="padaria"))]}
        (self.entrada / "cupom.jpg").write_bytes(b"jpg")
        preparada = self.servico(visao=visao).importar(self.entrada / "cupom.jpg", "telegram")
        self.assertIn("foto", preparada["duvidas"][0])
        self.assertEqual(preparada["origem"]["versao_prompt"], "foto-v1")
        self.assertEqual(visao.gerar_json_imagem.call_args[0][2], [preparada["origem"]["anexo"]])

    def test_pdf_sem_texto_ou_sem_biblioteca(self):
        (self.entrada / "nota.pdf").write_bytes(b"%PDF-1.4")
        with self.assertRaises(DocumentoError):
            self.servico().importar(self.entrada / "nota.pdf")

    def test_pdf_com_texto_vai_para_a_extracao(self):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("pypdf não instalado")
        texto = "Supermercado Moreschi  Arroz 5kg 1 un 27,90  Total 27,90"
        conteudo = f"BT /F1 12 Tf 20 700 Td ({texto}) Tj ET".encode("latin-1")
        objetos = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
                   b"<< /Length %d >>stream\n" % len(conteudo) + conteudo + b"\nendstream",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        pdf, posicoes = b"%PDF-1.4\n", []
        for n, obj in enumerate(objetos, 1):
            posicoes.append(len(pdf))
            pdf += b"%d 0 obj\n" % n + obj + b"\nendobj\n"
        xref = len(pdf)
        pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1) + b"".join(b"%010d 00000 n \n" % p for p in posicoes)
        pdf += b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objetos) + 1, xref)
        (self.entrada / "nota.pdf").write_bytes(pdf)
        self.compras.preparar_compra = mock.Mock(return_value={"compras": [fase1.compra()], "duvidas": [], "origem": {}})
        preparada = self.servico().importar(self.entrada / "nota.pdf", "pasta")
        self.assertIn("Arroz 5kg", self.compras.preparar_compra.call_args[0][0])
        self.assertIn("PDF", preparada["duvidas"][-1])


class TestPastaEntradas(BaseDocs):
    def test_entrega_quando_a_copia_termina_e_move(self):
        achados = []
        pasta = PastaEntradas(self.entrada, lambda caminho, canal: achados.append((caminho.name, canal)))
        pasta.preparar()
        self.copiar_nota("telegram_42_nota.html")
        self.assertEqual(pasta.verificar(), 0)   # primeira vez: guarda o tamanho
        self.assertEqual(pasta.verificar(), 1)   # tamanho estável: entrega
        self.assertEqual(pasta.verificar(), 0)   # não entrega de novo
        self.assertEqual(achados, [("telegram_42_nota.html", "telegram")])
        destino = pasta.mover(self.entrada / "telegram_42_nota.html", ok=True)
        self.assertEqual(destino.parent.name, "processados")


class TestPeloApp(BaseDocs):
    def test_nota_vira_compra_e_estoque(self):
        mensagens = []
        for patcher in (mock.patch.object(app_main, "emitir_electron", lambda tipo, p=None: mensagens.append(p)),
                        mock.patch.object(app_main, "TEMPO_RETRY", 0),
                        mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        runtime = app_main.AssistenteRuntime()
        runtime.db_service = self.db
        runtime.memory_service = mock.Mock()
        runtime.shopping_assistant = self.compras
        runtime.inventory_assistant = InventoryAssistant(self.db, voice_service=mock.Mock(), audio_service=mock.Mock())
        runtime.documentos = self.servico(nomes=LLMNomes())
        runtime.pasta_entradas = PastaEntradas(self.entrada, lambda *_: None)
        texto = runtime._importar_documento(str(self.copiar_nota()), "pasta")
        self.assertIn("Nota fiscal recebida", texto)
        self.assertTrue((self.entrada / "processados" / "nota.html").exists())
        self.assertIn("Compra registrada", runtime._processar_solicitacao("sim"))
        estoque = runtime._processar_solicitacao("ainda tenho limpador?")
        self.assertIn("0,5 litro", estoque)

    def test_telegram_baixa_para_a_pasta(self):
        enviados = []
        respostas = {"getUpdates": {"ok": True, "result": [{"update_id": 1, "message": {
            "message_id": 7, "chat": {"id": 42}, "document": {"file_id": "F1", "file_name": "nota muffato.html", "file_size": 11000}}}]},
            "getFile": {"ok": True, "result": {"file_path": "documents/x.html"}}}

        def get(url, **_k):
            if "/file/bot" in url:
                return SimpleNamespace(content=NOTA.read_bytes())
            return SimpleNamespace(json=lambda: respostas[url.rsplit("/", 1)[1]])

        def post(url, json=None, **_k):
            enviados.append(json["text"])
            return SimpleNamespace(json=lambda: {"ok": True, "result": {}})

        with mock.patch.object(app_main.config_app, "ENTRADAS_DIR", self.entrada):
            runtime = app_main.AssistenteRuntime.__new__(app_main.AssistenteRuntime)
            runtime.telegram = TelegramService("1:T", {42}, Path(self._tmp.name) / "o.json",
                                               ao_receber_arquivo=runtime._receber_arquivo_telegram, get=get, post=post)
            runtime.telegram.processar_uma_vez()
        self.assertTrue((self.entrada / "telegram_42_nota_muffato.html").is_file())
        self.assertIn("Recebi o arquivo", enviados[0])
        self.assertEqual(app_main.AssistenteRuntime._chat_do_arquivo(Path("telegram_42_nota_muffato.html")), 42)


if __name__ == "__main__":
    unittest.main()
