"""
Testes do SKP (roadmap das skills): programação com Claude (API) e Qwen local como reserva.
Nenhuma chamada real: o HTTP, o relógio, o modelo local e o banco vetorial são simulados.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.skills import Contexto, motor, obter_catalogo  # noqa: E402
from services import logger_service  # noqa: E402
from services.biblioteca_service import BibliotecaService, bloco_de_contexto, dividir  # noqa: E402
from services.claude_service import ClaudeIndisponivelError, ClaudeService, proxima_manha  # noqa: E402


class RespostaHTTP:
    def __init__(self, status, corpo=None, cabecalhos=None):
        self.status_code = status
        self._corpo = corpo or {}
        self.headers = cabecalhos or {}

    def json(self):
        return self._corpo


def sucesso(texto="ok", entrada=1000, saida=500):
    return RespostaHTTP(200, {"content": [{"type": "text", "text": texto}],
                              "usage": {"input_tokens": entrada, "output_tokens": saida}})


def erro(status, tipo="x", mensagem="", cabecalhos=None):
    return RespostaHTTP(status, {"type": "error", "error": {"type": tipo, "message": mensagem}}, cabecalhos)


class Relogio:
    def __init__(self, inicio):
        self.agora = inicio

    def __call__(self):
        return self.agora


class BaseLogs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.pasta = Path(self._tmp.name)
        patcher = mock.patch.object(logger_service.logger, "base_dir", str(self.pasta / "logs"))
        patcher.start()
        self.addCleanup(patcher.stop)


class TestClaudeService(BaseLogs):
    def setUp(self):
        super().setUp()
        self.relogio = Relogio(datetime(2026, 11, 23, 14, 0))
        self.respostas = []
        self.chamadas = []

    def servico(self, chave="sk-teste", limite=5.0):
        def post(url, headers=None, json=None, timeout=None):
            self.chamadas.append({"url": url, "headers": headers, "json": json})
            resposta = self.respostas.pop(0)
            if isinstance(resposta, Exception):
                raise resposta
            return resposta
        return ClaudeService(chave, "claude-sonnet-5-5", "2026-10-21", self.pasta / "estado.json",
                             limite_mensal_usd=limite, agora=self.relogio, post=post)

    def test_sucesso_registra_tokens_e_gasto(self):
        self.respostas = [sucesso("resposta do Claude", 1000, 500)]
        claude = self.servico()
        self.assertEqual(claude.gerar_texto("sistema", "pergunta"), "resposta do Claude")
        chamada = self.chamadas[0]
        self.assertEqual(chamada["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(chamada["headers"]["anthropic-version"], "2026-10-21")
        self.assertEqual(chamada["json"]["system"], "sistema")
        estado = claude.estado()
        self.assertEqual((estado["tokens_entrada"], estado["tokens_saida"]), (1000, 500))
        self.assertAlmostEqual(estado["gasto_usd"], (1000 * 2 + 500 * 10) / 1_000_000)
        self.assertNotIn("sk-teste", (self.pasta / "estado.json").read_text(encoding="utf-8"))

    def test_sem_chave_nao_chama(self):
        claude = self.servico(chave="")
        self.assertFalse(claude.configurado())
        with self.assertRaises(ClaudeIndisponivelError):
            claude.gerar_texto("s", "p")
        self.assertEqual(self.chamadas, [])

    def test_cota_esgotada_desativa_ate_8h_e_retesta(self):
        self.respostas = [erro(429, "rate_limit_error")]
        claude = self.servico()
        with self.assertRaises(ClaudeIndisponivelError) as ctx:
            claude.gerar_texto("s", "p")
        self.assertEqual(ctx.exception.ate, datetime(2026, 11, 24, 8, 0))
        # Antes das 8h do dia seguinte: nem chama a API
        self.relogio.agora = datetime(2026, 11, 24, 7, 59)
        with self.assertRaises(ClaudeIndisponivelError):
            claude.gerar_texto("s", "p")
        self.assertEqual(len(self.chamadas), 1)
        # Primeira solicitação depois das 8h: testa de novo e volta a ser o principal
        self.relogio.agora = datetime(2026, 11, 24, 9, 15)
        self.respostas = [sucesso("voltei")]
        self.assertEqual(claude.gerar_texto("s", "p"), "voltei")
        self.assertNotIn("indisponivel_ate", claude.estado())

    def test_retry_after_espera_so_o_indicado(self):
        self.respostas = [erro(429, "rate_limit_error", cabecalhos={"retry-after": "30"})]
        with self.assertRaises(ClaudeIndisponivelError) as ctx:
            self.servico().gerar_texto("s", "p")
        self.assertEqual(ctx.exception.ate, datetime(2026, 11, 23, 14, 0, 30))

    def test_cobranca_chave_e_limite_de_gasto_desativam(self):
        for resposta in (erro(402, "billing_error"), erro(401, "authentication_error"),
                         erro(400, "invalid_request_error", "You have reached your specified API usage limits")):
            with self.subTest(status=resposta.status_code):
                (self.pasta / "estado.json").unlink(missing_ok=True)
                self.respostas = [resposta]
                with self.assertRaises(ClaudeIndisponivelError) as ctx:
                    self.servico().gerar_texto("s", "p")
                self.assertEqual(ctx.exception.ate, datetime(2026, 11, 24, 8, 0))

    def test_falha_passageira_nao_desativa(self):
        claude = self.servico()
        for resposta in (erro(529, "overloaded_error"), erro(500, "api_error"), erro(400, "invalid_request_error", "bad field"),
                         requests.ConnectionError("rede")):
            with self.subTest(resposta=resposta):
                self.respostas = [resposta]
                with self.assertRaises(ClaudeIndisponivelError) as ctx:
                    claude.gerar_texto("s", "p")
                self.assertIsNone(ctx.exception.ate)
                self.assertNotIn("indisponivel_ate", claude.estado())

    def test_limite_mensal_e_virada_do_mes(self):
        claude = self.servico(limite=0.01)
        self.respostas = [sucesso(entrada=1000, saida=1000)]  # US$ 0,012
        claude.gerar_texto("s", "p")
        with self.assertRaises(ClaudeIndisponivelError) as ctx:
            claude.gerar_texto("s", "p")
        self.assertEqual(ctx.exception.ate, datetime(2026, 12, 1, 8, 0))
        self.relogio.agora = datetime(2026, 12, 1, 8, 30)
        self.respostas = [sucesso("dezembro")]
        self.assertEqual(claude.gerar_texto("s", "p"), "dezembro")

    def test_mensagens_alternadas_comecando_pelo_usuario(self):
        historico = [{"role": "assistant", "content": "a0"}, {"role": "user", "content": "u1"},
                     {"role": "user", "content": "u2"}, {"role": "assistant", "content": "a1"}, {"role": "system", "content": "x"}]
        mensagens = ClaudeService._mensagens(historico, "nova")
        self.assertEqual([m["role"] for m in mensagens], ["user", "assistant", "user"])
        self.assertEqual(mensagens[0]["content"], "u1\n\nu2")
        self.assertEqual(mensagens[-1]["content"], "nova")

    def test_proxima_manha(self):
        self.assertEqual(proxima_manha(datetime(2026, 11, 23, 6, 0), 8), datetime(2026, 11, 23, 8, 0))
        self.assertEqual(proxima_manha(datetime(2026, 11, 23, 8, 0), 8), datetime(2026, 11, 24, 8, 0))


class ClaudeFalso:
    def __init__(self, texto=None, erro=None, configurado=True):
        self.texto, self.erro, self._configurado = texto, erro, configurado
        self.prompts = []

    def configurado(self):
        return self._configurado

    def gerar_texto(self, prompt, texto, historico=None):
        self.prompts.append(prompt)
        if self.erro:
            raise self.erro
        return self.texto


class LocalFalso:
    def __init__(self):
        self.chamadas = 0

    def gerar_texto(self, prompt, texto, historico=None):
        self.chamadas += 1
        return "resposta do Qwen"


class BibliotecaFalsa:
    def buscar(self, pergunta, k=6, score_minimo=0.3):
        return [{"fonte": "Sobre a Versão/03 - Arquitetura Geral.md", "texto": "O runtime fica em app/main.py."}]


class TestRoteiroDeProgramacao(BaseLogs):
    def executar(self, claude=None):
        local = LocalFalso()
        servicos = {"llm_programacao": local, "biblioteca": BibliotecaFalsa(), "historico": []}
        if claude is not None:
            servicos["claude"] = claude
        ctx = Contexto(servicos=servicos, repetir=lambda f, a, **_k: f(*a))
        resposta = motor.executar(obter_catalogo().skill("programacao"), ctx, "onde fica o runtime?", {"acao": "consultar"})
        return resposta, local

    def test_claude_principal_com_trechos_da_biblioteca(self):
        claude = ClaudeFalso("resposta do Claude")
        resposta, local = self.executar(claude)
        self.assertEqual(resposta.texto, "resposta do Claude")
        self.assertEqual(local.chamadas, 0)
        self.assertIn("O runtime fica em app/main.py.", claude.prompts[0])
        self.assertIn("# PAPEL", claude.prompts[0])

    def test_sem_cota_o_qwen_responde_e_diz_o_motivo(self):
        resposta, local = self.executar(ClaudeFalso(erro=ClaudeIndisponivelError("cota do Claude atingida")))
        self.assertTrue(resposta.texto.startswith("resposta do Qwen"))
        self.assertIn("cota do Claude atingida", resposta.texto)
        self.assertEqual(local.chamadas, 1)

    def test_sem_claude_o_qwen_responde_sem_aviso(self):
        for claude in (None, ClaudeFalso(configurado=False)):
            with self.subTest(claude=claude):
                resposta, _ = self.executar(claude)
                self.assertEqual(resposta.texto, "resposta do Qwen")


class TestPoliticaDoClaude(unittest.TestCase):
    def test_so_programacao_recebe_o_claude(self):
        from app import main as app_main
        runtime = app_main.AssistenteRuntime()
        runtime.claude_service = object()
        for skill in obter_catalogo():
            with self.subTest(skill=skill.nome):
                servicos = runtime._contexto_skill(skill).servicos
                self.assertEqual("claude" in servicos, skill.nome == "programacao")
        with mock.patch.object(app_main, "CLAUDE_SKILLS", set()):
            self.assertNotIn("claude", runtime._contexto_skill(obter_catalogo().skill("programacao")).servicos)

    def test_cabecalhos_concordam_com_a_politica(self):
        from core.config import CLAUDE_SKILLS
        declaradas = {s.nome for s in obter_catalogo() if s.privacidade == "claude"}
        self.assertEqual(declaradas, CLAUDE_SKILLS)


class VetorFalso:
    def __init__(self):
        self.docs, self.apagados = {}, []

    def upsert_documents(self, documentos, collection_name=None):
        self.docs.update({d.id: d for d in documentos})
        return True

    def delete_documents(self, ids, collection_name=None):
        self.apagados += ids
        for i in ids:
            self.docs.pop(i, None)
        return True

    def search_similarity(self, pergunta, top_k=5, min_score=0.0, collection_name=None, **_k):
        return [{"content": d.content, "metadata": d.metadata} for d in list(self.docs.values())[:top_k]]


class TestBiblioteca(BaseLogs):
    def test_dividir_por_titulos(self):
        texto = "# A\n\n" + ("x" * 900) + "\n\n" + ("y" * 900) + "\n\n## B\n\ncurto"
        trechos = dividir(texto, tamanho=1000)
        self.assertEqual(len(trechos), 3)
        self.assertTrue(trechos[-1].startswith("## B"))
        self.assertTrue(all(len(t) <= 1000 for t in trechos))

    def test_indexacao_incremental(self):
        raiz = self.pasta / "projeto"
        raiz.mkdir()
        a, b = raiz / "a.md", raiz / "b.md"
        a.write_text("# A\n\nprimeiro", encoding="utf-8")
        b.write_text("# B\n\nsegundo", encoding="utf-8")
        vetor = VetorFalso()
        biblioteca = BibliotecaService(vetor, raiz, self.pasta / "indice.json", fontes=[a, b])
        self.assertEqual(biblioteca.indexar()["atualizados"], 2)
        self.assertEqual(biblioteca.indexar()["atualizados"], 0)  # nada mudou
        a.write_text("# A\n\nalterado", encoding="utf-8")
        biblioteca._fontes = [a]  # b apagado
        contagem = biblioteca.indexar()
        self.assertEqual((contagem["atualizados"], contagem["removidos"]), (1, 2))
        self.assertEqual([d.content for d in vetor.docs.values()], ["# A\n\nalterado"])
        self.assertEqual(list(json.loads((self.pasta / "indice.json").read_text(encoding="utf-8"))), ["projeto/a.md"])
        trechos = biblioteca.buscar("alterado")
        self.assertEqual(trechos, [{"fonte": "projeto/a.md", "texto": "# A\n\nalterado"}])
        self.assertIn("### projeto/a.md", bloco_de_contexto(trechos))
        self.assertEqual(bloco_de_contexto([]), "")

    def test_busca_com_falha_devolve_vazio(self):
        vetor = mock.Mock()
        vetor.search_similarity.side_effect = RuntimeError("chroma fora")
        self.assertEqual(BibliotecaService(vetor, self.pasta, self.pasta / "i.json", fontes=[]).buscar("x"), [])

    def test_fontes_padrao_sem_planejamento(self):
        from services.biblioteca_service import fontes_padrao
        fontes = [str(f) for f in fontes_padrao(ROOT_DIR)]
        self.assertTrue(any("Sobre a Versão" in f for f in fontes))
        self.assertFalse(any("Planejamento" in f for f in fontes))


if __name__ == "__main__":
    unittest.main()
