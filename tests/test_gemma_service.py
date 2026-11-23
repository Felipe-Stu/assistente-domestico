"""
Testes do orquestrador: comandos do Modo Qwen, inatividade e prompt de programação.
Não acessam o Ollama (troca de modelo e provedor são simulados).

Executar na raiz do assistente:
    python -m unittest discover -s tests -v
"""
import sys
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from services import gemma_service, llm_provider  # noqa: E402


class ProvedorFalso:
    """Simula o LocalLLMProvider devolvendo uma classificação válida."""

    def gerar_json(self, *_args, **_kwargs):
        # Serve aos dois modos do orquestrador: catálogo (skill) e contextos (contexto)
        return {"skill": "conversa-geral", "dificuldade": "facil", "mudanca_de_contexto": False,
                "contexto": "geral", "acao": "consultar"}


class BaseOrquestrador(unittest.TestCase):
    def setUp(self):
        for patcher in (
            mock.patch.object(llm_provider, "alternar_modelo_vram"),
            mock.patch.object(llm_provider, "pre_carregar_modelo_background"),
            mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False),
            mock.patch.object(llm_provider, "ULTIMA_ATIVIDADE_TIMESTAMP", time.time()),
            mock.patch.object(gemma_service, "obter_provedor_local", lambda temperatura=0.1: ProvedorFalso()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class TestComandosQwen(BaseOrquestrador):
    def test_comandos_de_desativacao_retornam_ao_gemma(self):
        for comando in ["desativar qwen", "Desativar Qwen", "desativar modo qwen", "voltar gemma", "modo normal", "sair do qwen"]:
            with self.subTest(comando=comando):
                llm_provider.MODO_QWEN_ATIVO = True
                decisao = gemma_service.orquestrar_requisicao(comando)
                self.assertFalse(llm_provider.MODO_QWEN_ATIVO)
                self.assertIn("desativado", decisao["resposta_direta"])

    def test_comandos_de_ativacao_ligam_o_qwen(self):
        for comando in ["ativar qwen", "modo qwen", "modo programador", "chamar qwen", "usar qwen"]:
            with self.subTest(comando=comando):
                llm_provider.MODO_QWEN_ATIVO = False
                decisao = gemma_service.orquestrar_requisicao(comando)
                self.assertTrue(llm_provider.MODO_QWEN_ATIVO)
                self.assertIn("ativado", decisao["resposta_direta"])


class TestInatividade(BaseOrquestrador):
    def test_inatividade_acima_do_limite_desativa_o_qwen(self):
        llm_provider.MODO_QWEN_ATIVO = True
        llm_provider.ULTIMA_ATIVIDADE_TIMESTAMP = time.time() - llm_provider.TEMPO_TIMEOUT_INATIVIDADE - 1
        gemma_service.orquestrar_requisicao("bom dia, tudo bem?")
        self.assertFalse(llm_provider.MODO_QWEN_ATIVO)

    def test_atividade_recente_mantem_o_qwen(self):
        llm_provider.MODO_QWEN_ATIVO = True
        llm_provider.ULTIMA_ATIVIDADE_TIMESTAMP = time.time() - llm_provider.TEMPO_TIMEOUT_INATIVIDADE + 60
        gemma_service.orquestrar_requisicao("bom dia, tudo bem?")
        self.assertTrue(llm_provider.MODO_QWEN_ATIVO)

    def test_solicitacao_renova_o_horario_de_atividade(self):
        llm_provider.ULTIMA_ATIVIDADE_TIMESTAMP = time.time() - 600
        gemma_service.orquestrar_requisicao("bom dia, tudo bem?")
        self.assertLess(time.time() - llm_provider.ULTIMA_ATIVIDADE_TIMESTAMP, 5)


class TestPromptProgramacao(unittest.TestCase):
    def test_caminho_do_projeto_preservado_no_prompt(self):
        from core.skills import obter_catalogo
        prompt = obter_catalogo().skill("programacao").prompt("sistema")
        self.assertIn(r"E:\Agente IA\assistente-domestico\Sobre a Versão", prompt)

    def test_modulo_compila_sem_escape_invalido(self):
        codigo = Path(gemma_service.__file__).read_text(encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(codigo, "gemma_service.py", "exec")


if __name__ == "__main__":
    unittest.main()
