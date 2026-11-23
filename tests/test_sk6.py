"""Testes do SK6 (roadmap das skills): fábrica de skills e validação."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.skills import carregar_catalogo, obter_catalogo  # noqa: E402
from core.skills.catalogo import PASTA_SKILLS  # noqa: E402
from scripts import avaliar, nova_skill, validar_skills  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.skills = Path(self._tmp.name) / "skills"
        shutil.copytree(PASTA_SKILLS, self.skills, ignore=shutil.ignore_patterns("__pycache__"))


class TestFabrica(Base):
    def test_modelo_nao_e_skill(self):
        self.assertNotIn("_modelo", [s.nome for s in obter_catalogo()])

    def test_cria_skill_valida_que_entra_no_catalogo(self):
        destino = nova_skill.criar_skill("musica", "Toca músicas e playlists no Spotify. Use quando a pessoa pede música.",
                                         pasta_skills=self.skills)
        texto = (destino / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("{{", texto)
        skill = carregar_catalogo(self.skills).skill("musica")
        self.assertEqual((skill.contexto, skill.execucao, skill.privacidade), ("musica", "roteiro", "local"))
        self.assertEqual(validar_skills.validar(self.skills), [])

    def test_recusas(self):
        casos = [
            (("Nome Ruim", "Descrição longa o bastante para passar."), ValueError),
            (("compras", "Descrição longa o bastante para passar."), FileExistsError),
            (("nova", "curta"), ValueError),
            (("nova", "Descrição longa o bastante para passar.", "inventario"), ValueError),  # contexto já usado
        ]
        for argumentos, erro in casos:
            with self.subTest(argumentos=argumentos), self.assertRaises(erro):
                nova_skill.criar_skill(*argumentos, pasta_skills=self.skills)
        self.assertFalse((self.skills / "nova").exists())


class TestValidacao(Base):
    def test_skills_do_projeto_sao_validas(self):
        self.assertEqual(validar_skills.validar(), [])

    def test_aponta_problemas(self):
        destino = nova_skill.criar_skill("exemplo", "Skill de exemplo para testar a validação.", pasta_skills=self.skills)
        (destino / "exemplos.jsonl").write_text('{"frase": "", "acao": "voar"}\nnão é json\n', encoding="utf-8")
        (destino / "prompts").mkdir()
        (destino / "prompts" / "x.md").write_text("Olá {{nome", encoding="utf-8")
        (destino / "roteiro.py").write_text("x = 1\n", encoding="utf-8")
        erros = "\n".join(validar_skills.validar(self.skills))
        for trecho in ("falta 'frase'", "'acao' deve ser", "JSON inválido", "sem fechar", "roteiro.py"):
            self.assertIn(trecho, erros)


class TestAvaliarPorSkill(Base):
    def test_casos_da_skill(self):
        # agenda já tem exemplos.jsonl: o teste não escreve na pasta real das skills
        casos = avaliar.casos_da_skill("agenda")
        self.assertTrue(casos)
        self.assertTrue(all(c["skill"] == "agenda" and c["acoes"] for c in casos))


class TestContextoGenerico(unittest.TestCase):
    def test_toda_skill_recebe_o_modelo_local(self):
        from app import main as app_main
        runtime = app_main.AssistenteRuntime()
        for skill in obter_catalogo():
            self.assertIn("llm_local", runtime._contexto_skill(skill).servicos)


if __name__ == "__main__":
    unittest.main()
