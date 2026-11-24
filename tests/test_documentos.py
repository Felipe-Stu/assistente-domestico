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

    def test_foto_sem_itens_explica_e_sugere_html(self):
        visao = mock.Mock(modelo="gemma4:e4b")
        visao.gerar_json_imagem.return_value = {"compras": [{"estabelecimento": "Loja", "itens": []}]}
        (self.entrada / "tela.png").write_bytes(b"png")
        with self.assertRaises(DocumentoError) as ctx:
            self.servico(visao=visao).importar(self.entrada / "tela.png", "app")
        self.assertIn("HTML", str(ctx.exception))

    def test_pdf_digitalizado_vai_para_o_leitor_de_imagem(self):
        try:
            import pypdf  # noqa: F401
            from PIL import Image
        except ImportError:
            self.skipTest("pypdf ou Pillow ausente")
        Image.new("RGB", (300, 120), "white").save(self.entrada / "moto.pdf")
        visao = mock.Mock(modelo="gemma4:e4b")
        visao.gerar_json_imagem.return_value = {"compras": [fase1.compra(fase1.item("moto", 1, "un", 100, 100, categoria="outros"))]}
        preparada = self.servico(visao=visao).importar(self.entrada / "moto.pdf", "app")
        self.assertEqual(preparada["compras"][0]["itens"][0]["produto"], "moto")
        imagens = visao.gerar_json_imagem.call_args[0][2]
        self.assertEqual(len(imagens), 1)
        self.assertTrue(Path(imagens[0]).exists())

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


TEXTO_COLADO = ("IRMAOS MUFFATO E CIA LTDA CNPJ: 76.430.438/0097-13 AVENIDA SAO DOMINGOS , 1491 , , Vila Guzzo , Catanduva , SP "
                "VINHO BENJAMIM NIETO (Código: 97029 ) Qtde.:2   UN: Un   Vl. Unit.:   49,9 \tVl. Total 99,80 "
                "RODO PRAT CSA UN (Código: 300429 ) Qtde.:1   UN: Un   Vl. Unit.:   46,75 \tVl. Total 46,75 "
                "LIMP TRIEX 500ML (Código: 304016 ) Qtde.:1   UN: Un   Vl. Unit.:   3,28 \tVl. Total 3,28 "
                "Qtd. total de itens:3 Valor total R$:149,83 Descontos R$:43,30 Valor a pagar R$:106,53 "
                "Forma de pagamento:Valor pago R$: Cartão de Crédito106,53 TrocoNaN")


# NF-e (modelo 55) copiada da consulta da Sefaz; destinatário fictício
TEXTO_NFE = ("Dados da NFe Natureza da operação VENDA MERC. ADQ. REC. TERC. REG. SUBST. TRIB.  Tipo da operação 1 - Saída  "
             "Chave de acesso 35-2611-13773688000194-55-001-000000758-159608157-4  Modelo 55  Série 1  Número 758  "
             "Data/Hora da emissão 06/11/2026 15:23:12-03:00  Emitente CNPJ 13.773.688/0001-94  IE 157839135112  "
             "Nome/Razão Social Naga Motors Comercio de Motos Ltda. Bauru  Município BAURU  UF SP  "
             "Destinatário CPF ***.**0.000-00  Nome/Razão Social FULANO***  Município CIDADE  UF SP  País BRASIL  "
             "Produtos Descrição\tQuantidade\tUnid. Com.\tValor Unit.\tValor Prod. 1\tC...\t1,0000\tUN\t32.990,000\t32.990,000 "
             "Valor total\t32.990,000 Eventos e Serviços Evento\tProtocolo\tData autorização Autorização de Uso\t"
             "135264751561912\t06/11/2026 às 15:23:31 Digest Value XYZ=")


class TestTextoColado(BaseDocs):
    def test_nfe_modelo_55(self):
        from services.nfce_service import ler_nfe_texto, parece_nfce_texto, parece_nfe_texto
        self.assertTrue(parece_nfe_texto(TEXTO_NFE))
        self.assertFalse(parece_nfce_texto(TEXTO_NFE))
        self.assertFalse(parece_nfe_texto(TEXTO_COLADO))
        nota = ler_nfe_texto(TEXTO_NFE)
        self.assertEqual((nota["estabelecimento"], nota["cnpj"], nota["data_compra"], nota["valor_total_compra"]),
                         ("Naga Motors Motos Bauru", "13.773.688/0001-94", "2026-11-06", 32990.0))
        self.assertEqual(nota["chave_acesso"], "35261113773688000194550010000007581596081574")
        self.assertEqual(len(nota["itens"]), 1)
        self.assertTrue(nota["itens"][0]["nome_cortado"])
        self.assertNotIn("FULANO", str(nota))

    def test_nfe_colada_pede_confirmacao_e_nao_inventa_nome(self):
        nomes = mock.Mock(modelo="gemma4:e4b")
        nomes.gerar_json.return_value = {"itens": []}
        preparada = self.servico(nomes=nomes).importar_texto(TEXTO_NFE, "chat")
        compra = preparada["compras"][0]
        self.assertEqual(compra["data_compra"], "2026-11-06")
        self.assertEqual(compra["itens"][0]["produto"], "c...")
        self.assertTrue(any("cortada" in d for d in preparada["duvidas"]))
        self.assertEqual(preparada["origem"]["versao_prompt"], "nfe-texto-v1")

    def test_leitor_do_texto(self):
        from services.nfce_service import ler_nfce_texto, parece_nfce_texto
        self.assertTrue(parece_nfce_texto(TEXTO_COLADO))
        self.assertFalse(parece_nfce_texto("Comprei leite por 10 reais no Moreschi"))
        nota = ler_nfce_texto(TEXTO_COLADO)
        self.assertEqual((nota["estabelecimento"], nota["forma_pagamento"], nota["valor_total_compra"]),
                         ("Irmaos Muffato", "Cartão de Crédito", 106.53))
        self.assertEqual([i["produto"] for i in nota["itens"]], ["VINHO BENJAMIM NIETO", "RODO PRAT CSA UN", "LIMP TRIEX 500ML"])
        frase = ler_nfce_texto("Fiz a seguinte compra:" + TEXTO_COLADO.split(" SP ", 1)[1])
        self.assertEqual(frase["itens"][0]["produto"], "VINHO BENJAMIM NIETO")
        self.assertEqual(frase["estabelecimento"], "Não informado")

    def test_skill_compras_usa_o_leitor_e_pede_confirmacao(self):
        from core.skills import Contexto, motor, obter_catalogo
        skill = obter_catalogo().skill("compras")
        ctx = Contexto(servicos={"shopping_assistant": self.compras, "documentos": self.servico(), "canal": "chat"},
                       repetir=lambda f, a, **_k: f(*a))
        resposta = motor.executar(skill, ctx, TEXTO_COLADO, {"acao": "criar"})
        self.assertIn("Nota fiscal reconhecida", resposta.texto)
        self.assertIn("data da compra não veio", resposta.texto)
        self.assertEqual(self.contar("compras"), 0)  # nada gravado antes do "sim"
        motor.responder_pendencia(skill, ctx, "sim", resposta.pendencia)
        self.assertEqual(self.db.executar_consulta_uma_linha("SELECT total_centavos, nome_comercio FROM compras"), (10653, "Irmaos Muffato"))
        self.assertEqual(self.db.executar_consulta_uma_linha("SELECT tipo, versao_prompt FROM entradas"), ("nota", "nfce-texto-v1"))


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
                        mock.patch.object(app_main.config_app, "ENTRADAS_DIR", self.entrada),
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

    def test_anexo_do_app_fica_onde_estava(self):
        mensagens = []
        for patcher in (mock.patch.object(app_main, "emitir_electron", lambda tipo, p=None: mensagens.append((tipo, p))),
                        mock.patch.object(app_main.config_app, "ENTRADAS_DIR", self.entrada)):
            patcher.start()
            self.addCleanup(patcher.stop)
        runtime = app_main.AssistenteRuntime.__new__(app_main.AssistenteRuntime)
        runtime.pendencia = None
        runtime.telegram = None
        runtime.documentos = self.servico(nomes=LLMNomes())
        runtime.pasta_entradas = PastaEntradas(self.entrada, lambda *_: None)
        outra = Path(self._tmp.name) / "Downloads"
        outra.mkdir()
        nota = outra / "nota.html"
        nota.write_bytes(NOTA.read_bytes())
        texto = runtime._importar_documento(str(nota), "app")
        self.assertIn("Nota fiscal recebida", texto)
        self.assertTrue(nota.exists())
        self.assertFalse((self.entrada / "processados").exists())
        estados = [p["state"] for tipo, p in mensagens if tipo == "state_changed"]
        self.assertEqual(estados, ["PROCESSING", "WAITING_INPUT"])

    def test_anexo_com_confirmacao_pendente_avisa_uma_vez(self):
        mensagens = []
        with mock.patch.object(app_main, "emitir_electron", lambda tipo, p=None: mensagens.append(p)), \
                mock.patch.object(app_main.threading, "Timer") as timer:
            runtime = app_main.AssistenteRuntime.__new__(app_main.AssistenteRuntime)
            runtime.pendencia = ("compras", {})
            self.assertIsNone(runtime._importar_documento("x.pdf", "app"))
            self.assertIsNone(runtime._importar_documento("x.pdf", "app", aguardando=True))
        self.assertEqual(len(mensagens), 1)
        self.assertIn("confirmação atual", mensagens[0]["text"])
        self.assertEqual(timer.call_count, 2)

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
