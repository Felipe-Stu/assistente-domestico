"""
Testes do SK0 (roadmap das skills): conjunto de avaliação, protótipo do seletor e relatório.
Não chamam o Ollama: o avaliador é simulado.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.skills import obter_catalogo, seletor  # noqa: E402
from scripts import avaliar  # noqa: E402
from services import gemma_service, llm_provider, logger_service  # noqa: E402


class BaseSemLogs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.object(logger_service.logger, "base_dir", os.path.join(self._tmp.name, "logs"))
        patcher.start()
        self.addCleanup(patcher.stop)


class TestConjuntoDeAvaliacao(unittest.TestCase):
    def test_casos_validos_e_cobrindo_todas_as_skills(self):
        casos = avaliar.carregar_casos()
        self.assertGreaterEqual(len(casos), 40)
        self.assertEqual({c["skill"] for c in casos}, {s.nome for s in obter_catalogo()})
        self.assertTrue(any(c.get("grupo") == "futuro" for c in casos))
        acoes_validas = {"criar", "corrigir", "consultar", "delegar"}
        for caso in casos:
            self.assertLessEqual(set(caso.get("acoes", [])), acoes_validas, caso["id"])

    def test_skill_inexistente_e_recusada(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"id": "x1", "frase": "oi", "skill": "voar"}) + "\n")
        self.addCleanup(os.unlink, f.name)
        with self.assertRaises(ValueError):
            avaliar.carregar_casos(Path(f.name))

    def test_casos_de_compras(self):
        casos = avaliar.ler_jsonl(avaliar.ARQUIVO_COMPRAS)
        self.assertGreaterEqual(len(casos), 8)
        for caso in casos:
            self.assertTrue({"frase", "mercado", "itens", "total", "embalagem"} <= set(caso))

    def test_regras_resolvem_as_frases_sem_nota_de_modelo(self):
        """As frases marcadas como 'depende do modelo' não podem estar sendo resolvidas por regra por acaso."""
        from services.intent_router import rotear_por_regras
        for caso in avaliar.carregar_casos():
            if "depende do modelo" in caso.get("nota", ""):
                with self.subTest(frase=caso["frase"]):
                    self.assertIsNone(rotear_por_regras(caso["frase"]))


class TestPontuacao(unittest.TestCase):
    def test_acertou(self):
        caso = {"skill": "compras", "acoes": ["criar"], "aceita": ["conversa-geral"]}
        self.assertTrue(avaliar.acertou(caso, "compras", "criar"))
        self.assertFalse(avaliar.acertou(caso, "compras", "consultar"))
        self.assertTrue(avaliar.acertou(caso, "compras"))
        self.assertTrue(avaliar.acertou(caso, "conversa-geral", "consultar"))
        self.assertFalse(avaliar.acertou(caso, "estoque"))

    def test_conferir_extracao(self):
        caso = {"mercado": "tauste", "itens": 2, "total": 29.37, "embalagem": True}
        preparada = {"compras": [{"estabelecimento": "Tauste", "itens": [
            {"valor_total": 7.47, "embalagem_quantidade": 170}, {"valor_total": 21.90}]}], "duvidas": []}
        checagens = avaliar.conferir_extracao(caso, preparada)
        self.assertTrue(all(v for k, v in checagens.items() if not k.startswith("_")))
        caso_sem_mercado = {"mercado": None, "itens": 0, "total": 0, "embalagem": False}
        self.assertTrue(avaliar.conferir_extracao(caso_sem_mercado, {"compras": [], "duvidas": ["Loja não informada."]})["mercado"])


class TestSeletor(unittest.TestCase):
    def test_prompt_e_esquema_com_todas_as_skills(self):
        catalogo = obter_catalogo()
        prompt = seletor.prompt_catalogo(catalogo)
        for skill in catalogo:
            self.assertIn(f"- {skill.nome}: {skill.descricao}", prompt)
        self.assertEqual(seletor.esquema_catalogo(catalogo)["properties"]["skill"]["enum"], [s.nome for s in catalogo])
        self.assertEqual(len(seletor.ferramentas_nativas(catalogo)), len(catalogo))

    def test_leitura_da_chamada_nativa(self):
        catalogo = obter_catalogo()
        como_dict = {"message": {"tool_calls": [{"function": {"name": "skill_documentar_projeto", "arguments": {}}}]}}
        self.assertEqual(seletor.skill_da_chamada_nativa(como_dict, catalogo), "documentar-projeto")
        como_objeto = SimpleNamespace(message=SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name="skill_compras"))]))
        self.assertEqual(seletor.skill_da_chamada_nativa(como_objeto, catalogo), "compras")
        self.assertIsNone(seletor.skill_da_chamada_nativa({"message": {"content": "oi"}}, catalogo))
        self.assertIsNone(seletor.skill_da_chamada_nativa({"message": {"tool_calls": [{"function": {"name": "outra"}}]}}, catalogo))


class AvaliadorFalso(avaliar.Avaliador):
    def _escolher_catalogo(self, frase, modelo):
        regra = self._por_regra(frase)
        if regra:
            return regra
        if "erro" in frase:
            raise RuntimeError("falhou")
        return "conversa-geral", None, "modelo", {"tokens_gerados": 10}


class TestAvaliacaoERelatorio(BaseSemLogs):
    def test_avaliar_e_gravar_relatorio(self):
        casos = [
            {"id": "a", "frase": "Comprei arroz", "skill": "compras", "acoes": ["criar"], "grupo": "atual"},
            {"id": "b", "frase": "Qual a capital da França?", "skill": "conversa-geral", "grupo": "atual"},
            {"id": "c", "frase": "Toca música", "skill": "conversa-geral", "grupo": "futuro"},
            {"id": "d", "frase": "isto dá erro", "skill": "programacao", "grupo": "atual"},
        ]
        resultados = avaliar.avaliar_roteamento(casos, ["catalogo"], ["modelo-x"], avaliador=AvaliadorFalso(), log=lambda *_: None)
        por_id = {r["id"]: r for r in resultados}
        self.assertEqual(por_id["a"]["caminho"], "regra")
        self.assertTrue(por_id["a"]["acerto"] and por_id["b"]["acerto"] and por_id["c"]["acerto"])
        self.assertFalse(por_id["d"]["acerto"])
        self.assertIn("RuntimeError", por_id["d"]["erro"])

        [resumo] = avaliar.resumir_roteamento(resultados)
        self.assertEqual((resumo["acerto"], resumo["acerto_pelo_modelo"], resumo["acerto_futuras"]), ("3/4", "2/2", "1/1"))

        dados = {"data": "23/11/2026 10:00", "modelos": ["modelo-x"], "usar_regras": True, "repeticoes": 1,
                 "roteamento": resultados, "extracao": [], "troca": None}
        base = avaliar.gravar_relatorio(dados, Path(self._tmp.name) / "medicoes")
        md = base.with_suffix(".md").read_text(encoding="utf-8")
        self.assertIn("| catalogo | modelo-x | 3/4 |", md)
        self.assertIn("Erros de escolha", md)
        self.assertEqual(json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))["modelos"], ["modelo-x"])

    def test_m13_historico_campos_e_versoes(self):
        pasta = Path(self._tmp.name) / "medicoes"
        extracao = [{"modelo": "m", "raciocinio": "nao", "acerto": False, "segundos": 1.0, "metricas": {},
                     "checagens": {"itens": True, "total": False, "mercado": True, "embalagem": True}},
                    {"modelo": "m", "raciocinio": "nao", "acerto": True, "segundos": 2.0, "metricas": {},
                     "checagens": {"itens": True, "total": True, "mercado": True, "embalagem": True}}]
        [linha] = avaliar.resumir_extracao(extracao)
        self.assertEqual((linha["itens"], linha["total"], linha["acerto"]), ("2/2", "1/2", "1/2"))
        versoes = avaliar.versoes_dos_prompts()
        self.assertEqual({len(v) for v in versoes.values()}, {8})
        for hora in ("10:00", "11:00"):
            dados = {"data": f"23/11/2026 {hora}", "modelos": ["m"], "usar_regras": True, "repeticoes": 1,
                     "roteamento": None, "extracao": extracao, "troca": None, "prompts": versoes}
            base = avaliar.gravar_relatorio(dados, pasta)
        historico = avaliar.ler_historico(pasta)
        self.assertEqual([h["data"] for h in historico], ["23/11/2026 10:00", "23/11/2026 11:00"])
        md = base.with_suffix(".md").read_text(encoding="utf-8")
        self.assertIn("## Histórico (últimas medições)", md)
        self.assertIn(versoes["extracao"], md)
        self.assertIn("| m | nao | 1/2 | 2/2 | 1/2 |", md)

    def test_modo_atual_troca_o_modelo_e_desliga_regras(self):
        modelos_usados = []

        def orquestrar(frase, contexto_atual=None):
            modelos_usados.append(llm_provider.obter_modelo_ativo())
            llm_provider.ULTIMA_CHAMADA.update({"tokens_gerados": 5})
            self.assertIsNone(gemma_service.rotear_por_regras("Comprei arroz"))
            return {"contexto": "compras", "acao": "criar"}

        with mock.patch.object(gemma_service, "orquestrar_requisicao", orquestrar):
            skill, acao, caminho, _ = avaliar.Avaliador(usar_regras=False).escolher("atual", "Comprei arroz", "qwen2.5:7b")
        self.assertEqual((skill, acao, caminho, modelos_usados), ("compras", "criar", "modelo", ["qwen2.5:7b"]))


if __name__ == "__main__":
    unittest.main()
