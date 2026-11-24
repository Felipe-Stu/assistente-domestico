"""Testes do M34: foto de nota em duas etapas (transcrição + leitura), imagem preparada e conferência com o usuário."""
import io
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
import test_documentos  # noqa: E402
from core.skills import Contexto, motor, obter_catalogo  # noqa: E402
from services import imagem_service  # noqa: E402
from services.documentos_service import DocumentosService, data_suspeita, limpar_transcricao  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


class TestPreparo(unittest.TestCase):
    def salvar(self, pasta, w, h):
        caminho = Path(pasta) / f"img_{w}x{h}.png"
        im = Image.new("RGB", (w, h), "white")
        im.paste(Image.new("RGB", (w - 40, h - 40), "black"), (20, 20))
        im.save(caminho)
        return caminho

    @unittest.skipIf(Image is None, "Pillow ausente")
    def test_cupom_comprido_vira_faixas_e_pequena_e_ampliada(self):
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            faixas = imagem_service.preparar(self.salvar(pasta, 600, 3000))
            self.assertGreater(len(faixas), 2)
            larga = imagem_service.preparar(self.salvar(pasta, 1812, 812))
            self.assertEqual(len(larga), 1)
            pequena = Image.open(io.BytesIO(imagem_service.preparar(self.salvar(pasta, 300, 200))[0]))
            self.assertGreaterEqual(max(pequena.size), imagem_service.LADO_MINIMO)

    def test_limpeza_e_data_suspeita(self):
        self.assertEqual(limpar_transcricao("Total 10,00\n(C/" + "C/" * 40 + ")"), "Total 10,00\n(C/)")
        hoje = date(2026, 11, 24)
        self.assertTrue(data_suspeita("2020-11-06", hoje))
        self.assertTrue(data_suspeita("2026-12-25", hoje))
        self.assertTrue(data_suspeita(None, hoje))
        self.assertFalse(data_suspeita("2026-11-06", hoje))


class Visao:
    modelo = "gemma3:4b"

    def __init__(self, transcricao=None, erro=None, json_direto=None):
        self.transcricao, self.erro, self.json_direto = transcricao, erro, json_direto
        self.chamadas = []

    def gerar_texto_imagem(self, prompt, mensagem, imagens, max_tokens=1500):
        self.chamadas.append(imagens)
        if self.erro:
            raise self.erro
        return self.transcricao

    def gerar_json_imagem(self, prompt, mensagem, imagens, esquema=None):
        return self.json_direto or {"compras": []}


class TestFoto(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        self.compras = self.assistente()
        self.foto = Path(self._tmp.name) / "nota.png"
        self.foto.write_bytes(b"png")

    def servico(self, visao):
        return DocumentosService(self.db, self.compras, Path(self._tmp.name) / "anexos", llm_visao=visao,
                                 agora=lambda: __import__("datetime").datetime(2026, 11, 24, 12, 0))

    def test_transcricao_de_nfe_usa_o_leitor_exato(self):
        preparada = self.servico(Visao(test_documentos.TEXTO_NFE)).importar(self.foto, "app")
        compra = preparada["compras"][0]
        self.assertEqual((compra["data_compra"], compra["valor_total_compra"]), ("2026-11-06", 32990.0))
        self.assertEqual(preparada["origem"]["versao_prompt"], "foto-transcricao-nota-v1")
        self.assertEqual(compra["_conferir"], ["loja"])          # loja lida: sempre conferida em foto
        self.assertIn("Transcrição da foto", preparada["origem"]["texto"])

    def test_transcricao_livre_vai_ao_modelo_de_texto_e_data_errada_e_perguntada(self):
        extraida = {"compras": [dict(fase1.compra(fase1.item("arroz", 1, "un", 25.9, 25.9), estabelecimento="Vaga Motors"),
                                     data_compra="2020-11-06", valor_total_compra=25.9)], "duvidas": [], "origem": {"texto": "x"}}
        with mock.patch.object(self.compras, "preparar_compra", return_value=extraida) as preparar:
            docs = self.servico(Visao("VAGA MOTORS\nARROZ 25,90\n06/11/2020"))
            preparada = docs.importar(self.foto, "app")
        self.assertIn("ARROZ 25,90", preparar.call_args.args[0])
        self.assertEqual(preparada["compras"][0]["_conferir"], ["loja", "data"])
        # No chat: confere a loja, corrige a data e grava
        skill = obter_catalogo().skill("compras")
        ctx = Contexto(servicos={"shopping_assistant": self.compras, "db_service": self.db, "canal": "app"},
                       repetir=lambda f, a, **_k: f(*a))
        from services import perguntas_compra
        aberta = perguntas_compra.abrir("📄 Nota", "resumo", preparada["compras"], preparada["origem"], preparada["duvidas"])
        self.assertIn('Li a loja como "Vaga Motors"', aberta["texto"])
        resposta = motor.responder_pendencia(skill, ctx, "Naga Motors", aberta["pendencia"])
        self.assertIn("Li a data como 06/11/2020", resposta.texto)
        resposta = motor.responder_pendencia(skill, ctx, "sim", resposta.pendencia)   # sim numa conferência = manter
        self.assertIn("Ficou assim", resposta.texto)
        motor.responder_pendencia(skill, ctx, "sim", resposta.pendencia)
        self.assertEqual(self.db.executar_consulta_uma_linha("SELECT nome_comercio, data_compra FROM compras"),
                         ("Naga Motors", "2020-11-06"))

    def test_data_corrigida_na_conferencia(self):
        from services import perguntas_compra
        compras = [dict(fase1.compra(estabelecimento="Loja X"), data_compra="2020-11-06", _conferir=["data"],
                        valor_total_compra=10.0)]
        skill = obter_catalogo().skill("compras")
        ctx = Contexto(servicos={"shopping_assistant": self.compras, "db_service": self.db}, repetir=lambda f, a, **_k: f(*a))
        aberta = perguntas_compra.abrir("Nota", "resumo", compras, None)
        resposta = motor.responder_pendencia(skill, ctx, "06/11/2026", aberta["pendencia"])
        self.assertIn("06/11/2026", resposta.texto)

    def test_sem_transcricao_cai_na_leitura_direta(self):
        direto = {"compras": [dict(fase1.compra(), data_compra="2026-11-20", valor_total_compra=10.0)]}
        preparada = self.servico(Visao("", json_direto=direto)).importar(self.foto, "app")
        self.assertEqual(preparada["origem"]["versao_prompt"], "foto-v1")

    def test_ollama_fora_explica(self):
        from services.documentos_service import DocumentoError
        with self.assertRaises(DocumentoError) as ctx:
            self.servico(Visao(erro=ConnectionError("x"))).importar(self.foto, "app")
        self.assertIn("Ollama", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
