"""
Testes do SK2 (roadmap das skills): o orquestrador escolhe a skill pelo catálogo.
O modelo é simulado; a medição real fica com scripts/avaliar.py.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.skills import obter_catalogo, seletor  # noqa: E402
from services import gemma_service, llm_provider, logger_service  # noqa: E402
from services.resilience_service import InvalidOrchestratorOutputException  # noqa: E402


class Espiao:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = []

    def gerar_json(self, prompt_sistema, mensagem_usuario, historico=None, esquema=None, raciocinio=None):
        self.chamadas.append({"prompt": prompt_sistema, "mensagem": mensagem_usuario, "esquema": esquema, "raciocinio": raciocinio})
        return self.resposta


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        for patcher in (
            mock.patch.object(logger_service.logger, "base_dir", os.path.join(self._tmp.name, "logs")),
            mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def orquestrar(self, texto, resposta, contexto_atual=None):
        espiao = Espiao(resposta)
        with mock.patch.object(gemma_service, "obter_provedor_local", return_value=espiao):
            decisao = gemma_service.orquestrar_requisicao(texto, contexto_atual)
        return decisao, espiao


class TestOrquestradorPeloCatalogo(Base):
    def test_decisao_no_formato_do_app(self):
        decisao, espiao = self.orquestrar("Me ajuda com um erro de Python",
                                          {"skill": "programacao", "acao": "delegar", "dificuldade": "facil"})
        self.assertEqual(decisao, {"dificuldade": "facil", "mudanca_de_contexto": False, "contexto": "programacao",
                                   "acao": "delegar", "skill": "programacao"})
        gemma_service._validar_schema_orquestrador(decisao)
        chamada = espiao.chamadas[0]
        self.assertEqual(chamada["mensagem"], "Me ajuda com um erro de Python")
        self.assertIs(chamada["raciocinio"], False)
        self.assertEqual(chamada["esquema"]["properties"]["skill"]["enum"], [s.nome for s in obter_catalogo()])

    def test_prompt_fixo_sem_a_frase_do_usuario(self):
        _, a = self.orquestrar("frase um", {"skill": "conversa-geral", "acao": "consultar", "dificuldade": "facil"})
        _, b = self.orquestrar("outra frase", {"skill": "conversa-geral", "acao": "consultar", "dificuldade": "facil"}, "compras")
        self.assertEqual(a.chamadas[0]["prompt"], b.chamadas[0]["prompt"])
        self.assertNotIn("frase um", a.chamadas[0]["prompt"])
        # Bem menor que o prompt por contextos (≈ 1.600 tokens na medição do SK0)
        self.assertLess(len(a.chamadas[0]["prompt"]), 2500)

    def test_p10_programacao_e_projetos_podem_ser_escolhidos(self):
        for skill, contexto in (("programacao", "programacao"), ("documentar-projeto", "projetos")):
            with self.subTest(skill=skill):
                decisao, _ = self.orquestrar("pedido", {"skill": skill, "acao": "consultar", "dificuldade": "facil"})
                self.assertEqual(decisao["contexto"], contexto)

    def test_mudanca_de_contexto(self):
        resposta = {"skill": "conversa-geral", "acao": "consultar", "dificuldade": "facil"}
        self.assertFalse(self.orquestrar("x", resposta)[0]["mudanca_de_contexto"])
        self.assertFalse(self.orquestrar("x", resposta, "outro")[0]["mudanca_de_contexto"])
        self.assertTrue(self.orquestrar("x", resposta, "compras")[0]["mudanca_de_contexto"])

    def test_resposta_invalida_vira_erro_recuperavel(self):
        for resposta in ({"skill": "voar", "acao": "consultar", "dificuldade": "facil"},
                         {"skill": "compras", "acao": "explodir", "dificuldade": "facil"},
                         ["não", "é", "objeto"]):
            with self.subTest(resposta=resposta), self.assertRaises(InvalidOrchestratorOutputException):
                self.orquestrar("x", resposta)

    def test_dificuldade_desconhecida_vira_facil(self):
        decisao, _ = self.orquestrar("x", {"skill": "conversa-geral", "acao": "consultar", "dificuldade": "?"})
        self.assertEqual(decisao["dificuldade"], "facil")

    def test_regras_e_comandos_continuam_antes_do_modelo(self):
        with mock.patch.object(gemma_service, "obter_provedor_local") as provedor:
            self.assertEqual(gemma_service.orquestrar_requisicao("Comprei arroz")["contexto"], "compras")
            self.assertEqual(gemma_service.orquestrar_requisicao("Pesquise na internet o preço do frango e compare três mercados")["contexto"], "compras")
        provedor.assert_not_called()

    def test_contexto_de_skill_nova_e_aceito_pela_validacao(self):
        """SK5: os contextos válidos vêm do catálogo; uma skill nova escolhida pelo modelo não é recusada."""
        from core.skills import carregar_catalogo
        tmp = Path(self._tmp.name) / "skills"
        for skill in obter_catalogo():
            destino = tmp / skill.nome
            for arquivo in skill.pasta.rglob("*"):
                if arquivo.is_file() and "__pycache__" not in arquivo.parts:
                    alvo = destino / arquivo.relative_to(skill.pasta)
                    alvo.parent.mkdir(parents=True, exist_ok=True)
                    alvo.write_bytes(arquivo.read_bytes())
        (tmp / "musica").mkdir()
        (tmp / "musica" / "SKILL.md").write_text(
            "---\nname: musica\ndescription: Toca músicas e playlists no Spotify da casa.\ncontextos: [musica]\n"
            "estado: ativa\nprivacidade: local\nversao: 1\n---\n", encoding="utf-8")
        catalogo = carregar_catalogo(tmp)
        with mock.patch.object(gemma_service, "obter_catalogo", return_value=catalogo):
            decisao, _ = self.orquestrar("toca algo animado", {"skill": "musica", "acao": "criar", "dificuldade": "facil"})
        self.assertEqual(decisao["contexto"], "musica")


class TestM16(unittest.TestCase):
    def test_prompt_e_esquema_sem_dificuldade(self):
        catalogo = obter_catalogo()
        self.assertNotIn("dificuldade", seletor.prompt_decisao(catalogo))
        self.assertNotIn("dificuldade", seletor.esquema_decisao(catalogo)["properties"])
        decisao = seletor.converter_decisao({"skill": "conversa-geral", "acao": "consultar"}, catalogo, None)
        self.assertEqual(decisao["dificuldade"], "facil")

    def test_pedidos_de_nuvem(self):
        from services.intent_router import pede_nuvem
        for frase in ("Pergunta pro Gemini quem foi Santos Dumont", "pesquisa na internet o preço do arroz",
                      "procura no Google a previsão", "busca online receitas de bolo"):
            self.assertTrue(pede_nuvem(frase), frase)
        for frase in ("Quem foi Santos Dumont?", "Comprei arroz no Moreschi", "o que tenho na agenda"):
            self.assertFalse(pede_nuvem(frase), frase)


class TestConversao(unittest.TestCase):
    def test_converter_decisao(self):
        catalogo = obter_catalogo()
        decisao = seletor.converter_decisao({"skill": "estoque", "acao": "corrigir", "dificuldade": "medio_dificil"}, catalogo, "inventario")
        self.assertEqual((decisao["contexto"], decisao["acao"], decisao["dificuldade"], decisao["mudanca_de_contexto"]),
                         ("inventario", "corrigir", "medio_dificil", False))
        with self.assertRaises(seletor.DecisaoInvalidaError):
            seletor.converter_decisao({"skill": None, "acao": "criar"}, catalogo, None)


if __name__ == "__main__":
    unittest.main()
