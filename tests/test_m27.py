"""Testes do M27: configuração e portabilidade."""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


class TestConfiguracao(unittest.TestCase):
    def tearDown(self):
        import core.config
        importlib.reload(core.config)  # volta aos valores do ambiente real

    def test_modelos_e_tempos_vem_do_ambiente(self):
        import core.config
        valores = {"OLLAMA_MODELO_PADRAO": "llama3:8b", "OLLAMA_MODELO_AVANCADO": "deepseek-coder:6.7b",
                   "OLLAMA_TIMEOUT": "45", "OLLAMA_KEEP_ALIVE": "5m", "RETRY_TENTATIVAS": "2", "RETRY_ESPERA_S": "0.5"}
        with mock.patch.dict(os.environ, valores):
            config = importlib.reload(core.config)
        self.assertEqual((config.OLLAMA_MODELO_PADRAO, config.OLLAMA_MODELO_AVANCADO), ("llama3:8b", "deepseek-coder:6.7b"))
        self.assertEqual((config.OLLAMA_TIMEOUT, config.OLLAMA_KEEP_ALIVE), (45.0, "5m"))
        self.assertEqual((config.RETRY_TENTATIVAS, config.RETRY_ESPERA_S), (2, 0.5))

    def test_padroes(self):
        import core.config
        limpo = {k: v for k, v in os.environ.items() if not k.startswith(("OLLAMA_MODELO", "OLLAMA_TIMEOUT", "OLLAMA_KEEP", "RETRY_"))}
        with mock.patch.dict(os.environ, limpo, clear=True):
            config = importlib.reload(core.config)
        self.assertEqual(config.OLLAMA_MODELO_PADRAO, "gemma4:e4b")
        self.assertEqual(config.OLLAMA_MODELO_AVANCADO, "qwen2.5-coder:7b")
        self.assertEqual((config.OLLAMA_TIMEOUT, config.RETRY_TENTATIVAS), (120.0, 3))

    def test_codigo_usa_a_configuracao(self):
        from core import config
        from services import llm_provider
        from app import main as app_main
        self.assertEqual(llm_provider.MODELO_PADRAO, config.OLLAMA_MODELO_PADRAO)
        self.assertEqual(llm_provider.MODELO_AVANCADO, config.OLLAMA_MODELO_AVANCADO)
        self.assertEqual(app_main.MAX_TENTATIVAS, config.RETRY_TENTATIVAS)
        for pasta in ("app", "services"):
            for arquivo in (ROOT_DIR / pasta).rglob("*.py"):
                if "project_analyzer" in arquivo.parts:
                    continue  # recebe o modelo de PROJECT_ANALYZER_MODEL; o padrão do construtor é só documentação
                self.assertNotIn('"gemma4:e4b"', arquivo.read_text(encoding="utf-8"), arquivo)


class TestPortabilidade(unittest.TestCase):
    def test_bip_sem_winsound_nao_falha(self):
        from services.audio_service import AudioService
        with mock.patch.dict(sys.modules, {"winsound": None}):
            AudioService._bip(800, 300)  # ImportError tratado: silêncio

    def test_electron_resolve_o_python_e_trata_falha(self):
        texto = (ROOT_DIR / "main.js").read_text(encoding="utf-8")
        self.assertIn("ASSISTENTE_PYTHON", texto)
        self.assertIn("pythonProcess.on('error'", texto)
        self.assertNotIn("spawn('python'", texto)

    def test_licenca(self):
        self.assertIn("MIT License", (ROOT_DIR / "LICENSE").read_text(encoding="utf-8"))

    def test_fixar_versoes(self):
        sys.path.insert(0, str(ROOT_DIR / "scripts"))
        import fixar_versoes
        from importlib import metadata
        with tempfile.TemporaryDirectory() as pasta:
            origem, destino = Path(pasta) / "req.txt", Path(pasta) / "lock.txt"
            origem.write_text("# comentário\nollama>=0.4.0\nPyYAML>=6.0  # cabeçalhos\nnaoexiste>=1\n", encoding="utf-8")

            def versao(nome):
                if nome == "naoexiste":
                    raise metadata.PackageNotFoundError(nome)
                return {"ollama": "0.6.1", "PyYAML": "6.0.3"}[nome]

            faltando = fixar_versoes.gerar(origem, destino, versao=versao)
            linhas = [l for l in destino.read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
        self.assertEqual(linhas, ["ollama==0.6.1", "PyYAML==6.0.3"])
        self.assertEqual(faltando, ["naoexiste"])


if __name__ == "__main__":
    unittest.main()
