"""
Testes do SK1 (roadmap das skills): formato, catálogo e equivalência com o comportamento anterior.

tests/dados/roteador_referencia.json guarda as decisões do roteador por regras ANTES da mudança
para skills (168 casos). Se um gatilho for editado e alguma decisão mudar, este teste aponta qual.
Mudança intencional: atualize a referência no mesmo commit e explique no CHANGELOG.

Executar na raiz do assistente:
    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core import skills as modulo_skills  # noqa: E402
from core.skills import SkillInvalidaError, carregar_catalogo, obter_catalogo  # noqa: E402
from services import gemma_service, intent_router, logger_service  # noqa: E402

REFERENCIA = ROOT_DIR / "tests" / "dados" / "roteador_referencia.json"


def cabecalho(nome="exemplo", **campos):
    base = {
        "name": nome,
        "description": "Skill de exemplo usada nos testes do catálogo.",
        "contextos": f"[{nome}]",
        "estado": "ativa",
        "privacidade": "local",
        "versao": "1",
    }
    base.update(campos)
    return "\n".join(f"{k}: {v}" for k, v in base.items() if v is not None)


class BaseTemporaria(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.pasta = Path(self._tmp.name)
        patcher = mock.patch.object(logger_service.logger, "base_dir", os.path.join(self._tmp.name, "logs"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def criar(self, nome, cabecalho_texto, corpo="# Exemplo\n\nInstruções.", gatilhos="", prompts=None):
        pasta = self.pasta / nome
        pasta.mkdir()
        (pasta / "SKILL.md").write_text(f"---\n{cabecalho_texto}\n{gatilhos}---\n\n{corpo}\n", encoding="utf-8")
        for arquivo, texto in (prompts or {}).items():
            (pasta / "prompts").mkdir(exist_ok=True)
            (pasta / "prompts" / arquivo).write_text(texto, encoding="utf-8")
        return pasta


class TestCatalogoDoProjeto(unittest.TestCase):
    def setUp(self):
        self.catalogo = obter_catalogo()

    def test_skills_do_projeto(self):
        self.assertEqual(
            [s.nome for s in self.catalogo],
            ["agenda", "compras", "conversa-geral", "documentar-projeto", "estoque", "programacao"],
        )

    def test_todo_contexto_do_orquestrador_tem_uma_skill(self):
        for contexto in gemma_service.VALORES_PERMITIDOS["contexto"]:
            with self.subTest(contexto=contexto):
                self.assertIsNotNone(self.catalogo.por_contexto(contexto))

    def test_privacidade_declarada_concorda_com_a_politica_do_nucleo(self):
        from app import main as app_main
        permitidos = {c for s in self.catalogo if s.privacidade == "nuvem-permitida" for c in s.contextos}
        self.assertEqual(permitidos, app_main.AssistenteRuntime.CONTEXTOS_NUVEM)

    def test_prompts_usados_pelo_codigo_existem(self):
        self.assertIn("# PAPEL", gemma_service.PROMPT_PROGRAMACAO)
        extracao = self.catalogo.skill("compras").prompt("extracao", data_atual="2026-01-31")
        self.assertIn('"data_compra": "2026-01-31"', extracao)
        self.assertNotIn("{{", extracao)
        self.assertEqual(self.catalogo.skill("conversa-geral").prompt("sistema"), "Você é um assistente pessoal prestativo.")


class TestEquivalenciaDoRoteador(unittest.TestCase):
    def test_decisoes_iguais_a_referencia(self):
        casos = json.loads(REFERENCIA.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(casos), 150)
        for caso in casos:
            with self.subTest(frase=caso["frase"], contexto_atual=caso["contexto_atual"]):
                self.assertEqual(intent_router.rotear_por_regras(caso["frase"], caso["contexto_atual"]), caso["decisao"])


class TestFormato(BaseTemporaria):
    def test_skill_valida(self):
        self.criar("exemplo", cabecalho(entradas="[texto, pdf]", saidas="[relatorio]"),
                   gatilhos="gatilhos:\n  - acao: consultar\n    prioridade: 5\n    padrao:\n      - '\\bteste\\b'\n")
        skill = carregar_catalogo(self.pasta).skill("exemplo")
        self.assertEqual((skill.entradas, skill.saidas), (("texto", "pdf"), ("relatorio",)))
        self.assertEqual(skill.instrucoes, "# Exemplo\n\nInstruções.")
        self.assertTrue(skill.gatilhos[0].casa("um teste aqui"))

    def test_erros_de_cabecalho(self):
        casos = {
            "sem_campo": cabecalho(versao=None),
            "nome_diferente_da_pasta": cabecalho(nome="outro-nome", contextos="[x]"),
            "privacidade_invalida": cabecalho(privacidade="publica"),
            "estado_invalido": cabecalho(estado="talvez"),
            "entrada_desconhecida": cabecalho(entradas="[telepatia]"),
            "descricao_curta": cabecalho(description="curta"),
            "yaml_quebrado": cabecalho(contextos="[aberto"),
        }
        for nome_caso, texto in casos.items():
            with self.subTest(caso=nome_caso):
                for pasta in self.pasta.iterdir():
                    for arquivo in pasta.iterdir():
                        arquivo.unlink()
                    pasta.rmdir()
                self.criar("exemplo", texto)
                with self.assertRaises(SkillInvalidaError):
                    carregar_catalogo(self.pasta)

    def test_regex_invalida_e_acao_desconhecida(self):
        for gatilho in ("  - acao: consultar\n    prioridade: 1\n    padrao: ['(aberto']\n",
                        "  - acao: voar\n    prioridade: 1\n    padrao: ['x']\n"):
            with self.subTest(gatilho=gatilho):
                pasta = self.criar("exemplo", cabecalho(), gatilhos="gatilhos:\n" + gatilho)
                with self.assertRaises(SkillInvalidaError):
                    carregar_catalogo(self.pasta)
                for arquivo in pasta.iterdir():
                    arquivo.unlink()
                pasta.rmdir()

    def test_contexto_e_prioridade_repetidos_sao_recusados(self):
        g = "gatilhos:\n  - acao: consultar\n    prioridade: 1\n    padrao: ['x']\n"
        self.criar("uma", cabecalho("uma"), gatilhos=g)
        self.criar("outra", cabecalho("outra"), gatilhos=g)
        with self.assertRaises(SkillInvalidaError):
            carregar_catalogo(self.pasta)

        tmp2 = Path(tempfile.mkdtemp(dir=self._tmp.name))
        for nome in ("uma", "outra"):
            (tmp2 / nome).mkdir()
            (tmp2 / nome / "SKILL.md").write_text(f"---\n{cabecalho(nome, contextos='[mesmo]')}\n---\n", encoding="utf-8")
        with self.assertRaises(SkillInvalidaError):
            carregar_catalogo(tmp2)

    def test_prompt_com_marcadores(self):
        self.criar("exemplo", cabecalho(), prompts={"sistema.md": "Hoje é {{ data }}. Não troque { chaves } de JSON.\n"})
        skill = carregar_catalogo(self.pasta).skill("exemplo")
        self.assertEqual(skill.prompt("sistema", data="31/01"), "Hoje é 31/01. Não troque { chaves } de JSON.")
        with self.assertRaises(SkillInvalidaError):
            skill.prompt("sistema")
        with self.assertRaises(SkillInvalidaError):
            skill.prompt("inexistente")

    def test_sem_interrogacao(self):
        self.criar("exemplo", cabecalho(),
                   gatilhos="gatilhos:\n  - acao: criar\n    prioridade: 1\n    sem_interrogacao: true\n    padrao: ['comprei']\n")
        gatilho = carregar_catalogo(self.pasta).gatilhos[0]
        self.assertTrue(gatilho.casa("comprei pao"))
        self.assertFalse(gatilho.casa("comprei pao?"))


class TestSkillNovaSemMexerNoNucleo(BaseTemporaria):
    """A promessa das skills: uma capacidade nova é uma pasta nova."""

    def test_pasta_nova_entra_no_catalogo_e_no_roteador(self):
        for skill in obter_catalogo():
            destino = self.pasta / skill.nome
            destino.mkdir()
            for arquivo in skill.pasta.rglob("*"):
                if arquivo.is_file():
                    alvo = destino / arquivo.relative_to(skill.pasta)
                    alvo.parent.mkdir(parents=True, exist_ok=True)
                    alvo.write_bytes(arquivo.read_bytes())
        self.criar("musica", cabecalho("musica", contextos="[musica]", entradas="[texto, voz]"),
                   gatilhos="gatilhos:\n  - acao: criar\n    prioridade: 100\n    padrao:\n      - '\\btoca\\b.{0,40}\\bplaylist\\b'\n")
        catalogo = carregar_catalogo(self.pasta)
        self.assertIn("musica", [s.nome for s in catalogo])
        with mock.patch.object(intent_router, "obter_catalogo", return_value=catalogo):
            decisao = intent_router.rotear_por_regras("Toca minha playlist na sala")
            self.assertEqual((decisao["contexto"], decisao["acao"]), ("musica", "criar"))
            # As skills existentes continuam com a mesma decisão
            self.assertEqual(intent_router.rotear_por_regras("Comprei arroz")["contexto"], "compras")


class TestCacheDoCatalogo(unittest.TestCase):
    def test_recarregar(self):
        primeiro = modulo_skills.obter_catalogo()
        self.assertIs(primeiro, modulo_skills.obter_catalogo())
        self.assertIsNot(primeiro, modulo_skills.recarregar_catalogo())


if __name__ == "__main__":
    unittest.main()
