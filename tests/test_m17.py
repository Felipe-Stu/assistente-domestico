"""
Testes do M17: falhar rápido quando o Ollama está fechado.
Não acessam o Ollama real: o cliente é simulado.

Executar na raiz do assistente:
    python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from services import llm_provider, logger_service  # noqa: E402
from services.resilience_service import OllamaIndisponivelException  # noqa: E402

RESPOSTA = {"message": {"content": '{"ok": true}'}}


class ClienteFalso:
    def __init__(self, saude_ok=True, erro_chat=None):
        self.saude_ok = saude_ok
        self.erro_chat = erro_chat
        self.listas = 0
        self.chats = 0

    def list(self):
        self.listas += 1
        if not self.saude_ok:
            raise ConnectionError("Failed to connect to Ollama")
        return {"models": []}

    def chat(self, **_kwargs):
        self.chats += 1
        if self.erro_chat:
            raise self.erro_chat
        return RESPOSTA


class TestSaudeOllama(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        for patcher in (
            mock.patch.object(logger_service.logger, "base_dir", os.path.join(tmp.name, "logs")),
            mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False),
            mock.patch.object(llm_provider, "OLLAMA_RACIOCINIO", None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        llm_provider.invalidar_saude_ollama()
        self.addCleanup(llm_provider.invalidar_saude_ollama)

    def chamar(self, cliente, metodo="gerar_json"):
        with mock.patch.object(llm_provider.ollama, "Client", return_value=cliente) as construtor:
            provedor = llm_provider.LocalLLMProvider(modelo="modelo-teste")
            resultado = getattr(provedor, metodo)("sistema", "usuario")
        return resultado, construtor

    def test_ollama_fechado_falha_antes_de_chamar_o_modelo(self):
        cliente = ClienteFalso(saude_ok=False)
        with self.assertRaises(OllamaIndisponivelException):
            self.chamar(cliente)
        self.assertEqual((cliente.listas, cliente.chats), (1, 0))

    def test_verificacao_usa_timeout_curto(self):
        cliente = ClienteFalso()
        _, construtor = self.chamar(cliente)
        self.assertEqual(construtor.call_args_list[0].kwargs["timeout"], llm_provider.OLLAMA_TIMEOUT_SAUDE)
        self.assertLessEqual(llm_provider.OLLAMA_TIMEOUT_SAUDE, 2.0)

    def test_resultado_positivo_fica_em_cache(self):
        cliente = ClienteFalso()
        self.chamar(cliente)
        self.chamar(cliente)
        self.assertEqual((cliente.listas, cliente.chats), (1, 2))

    def test_erro_de_conexao_no_chat_vira_indisponivel_e_invalida_o_cache(self):
        cliente = ClienteFalso(erro_chat=ConnectionError("Failed to connect to Ollama"))
        with self.assertRaises(OllamaIndisponivelException):
            self.chamar(cliente)
        cliente.erro_chat = None
        self.chamar(cliente)
        self.assertEqual(cliente.listas, 2)

    def test_gerar_texto_tambem_verifica(self):
        cliente = ClienteFalso(saude_ok=False)
        with self.assertRaises(OllamaIndisponivelException):
            self.chamar(cliente, "gerar_texto")
        self.assertEqual(cliente.chats, 0)

    def test_json_invalido_continua_recuperavel(self):
        cliente = ClienteFalso()
        cliente.chat = lambda **_k: {"message": {"content": "não é json"}}
        with self.assertRaises(llm_provider.InvalidOrchestratorOutputException):
            self.chamar(cliente)

    def test_indisponivel_e_erro_de_conexao(self):
        self.assertTrue(issubclass(OllamaIndisponivelException, ConnectionError))


if __name__ == "__main__":
    unittest.main()
