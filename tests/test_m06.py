"""Testes do M06: compras alimentam o estoque (P1)."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from app import main as app_main  # noqa: E402
from services import llm_provider  # noqa: E402
from services.estoque_service import nome_exibicao, quantidade_base  # noqa: E402
from services.inventory_assistant import InventoryAssistant  # noqa: E402

HOJE = date.today()


class TestUnidades(unittest.TestCase):
    def test_quantidade_base(self):
        self.assertEqual(quantidade_base(2, "litro"), (2.0, "litro"))
        self.assertEqual(quantidade_base(500, "ml"), (0.5, "litro"))
        self.assertEqual(quantidade_base(0.484, "kg"), (0.484, "kg"))
        self.assertEqual(quantidade_base(2, "un", 5, "kg"), (10.0, "kg"))
        self.assertEqual(quantidade_base(3, "un"), (3.0, "un"))
        self.assertEqual(quantidade_base(1, "un", 6, "un"), (1.0, "un"))  # embalagem sem peso/volume: conta as embalagens

    def test_nome(self):
        self.assertEqual(nome_exibicao("Leite 1L"), "leite")
        self.assertEqual(nome_exibicao("Feijão carioca 1 kg"), "feijão carioca")


class BaseEstoque(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        self.estoque = InventoryAssistant(self.db, voice_service=mock.Mock(), audio_service=mock.Mock())

    def comprar(self, produto, quantidade, unidade, dias_atras=0, **extra):
        item = fase1.item(produto, quantidade, unidade, 5.0, 5.0 * quantidade, **extra)
        compra = dict(fase1.compra(item), data_compra=(HOJE - timedelta(days=dias_atras)).isoformat(), valor_total_compra=5.0)
        assistente = self.assistente()
        assistente.registrar_compras([compra])
        return assistente

    def linha(self, produto):
        return self.db.executar_consulta_uma_linha(
            "SELECT quantidade_comprada, quantidade_residual_confirmada, tempo_medio_calculado, unidade, status_estoque "
            "FROM controle_consumo WHERE produto_nome = ?", (produto,))


class TestCompraAlimentaEstoque(BaseEstoque):
    def test_criterio_de_pronto(self):
        self.comprar("leite", 2, "litro", categoria="laticinios")
        resposta = self.estoque.consultar_estoque("Ainda tenho leite?")
        self.assertIn("leite: cerca de 2,0 litros", resposta)

    def test_embalagem_vira_peso(self):
        self.comprar("Arroz 5kg", 2, "un", embalagem_quantidade=5, embalagem_unidade="kg")
        self.assertIn("arroz: cerca de 10,0 kg", self.estoque.consultar_estoque("tem arroz?"))

    def test_mesma_data_soma(self):
        self.comprar("leite", 2, "litro")
        self.comprar("Leite 1L", 1, "litro")
        self.assertEqual(self.linha("leite")[:2], (1.0, 2.0))  # 1 da compra nova + 2 que sobraram
        self.assertIn("3,0 litros", self.estoque.consultar_estoque("leite"))

    def test_recompra_aprende_o_ritmo(self):
        self.comprar("café", 1, "un", dias_atras=10)
        self.comprar("café", 1, "un", dias_atras=0)
        comprada, sobra, ritmo, unidade, ativo = self.linha("café")
        self.assertEqual((comprada, sobra, ritmo, unidade, ativo), (1.0, 0.0, 10.0, "un", 1))  # 10 dias por unidade

    def test_ritmo_conhecido_desconta_o_consumo(self):
        self.comprar("café", 1, "un", dias_atras=20)
        self.comprar("café", 2, "un", dias_atras=10)   # aprende 10 dias por unidade
        self.assertIn("café: cerca de 1,0 unidade", self.estoque.consultar_estoque("café"))  # 2 - 10 dias / 10

    def test_desfazer_tira_do_estoque(self):
        self.comprar("leite", 2, "litro")
        assistente = self.comprar("leite", 1, "litro")
        assistente.desfazer_ultimo_registro()
        self.assertIn("2,0 litros", self.estoque.consultar_estoque("leite"))
        self.assistente().db_service.remover_compras([1])
        self.assertIn("vazio", self.estoque.consultar_estoque("leite"))

    def test_consulta_sem_acento(self):
        self.comprar("feijão", 1, "kg")
        self.assertIn("feijão", self.estoque.consultar_estoque("ainda tenho feijao?"))


class TestPeloApp(BaseEstoque):
    def test_registrar_e_consultar_pelo_chat(self):
        for patcher in (mock.patch.object(app_main, "emitir_electron", lambda *a, **k: None),
                        mock.patch.object(app_main, "TEMPO_RETRY", 0),
                        mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        runtime = app_main.AssistenteRuntime()
        runtime.db_service = self.db
        runtime.memory_service = mock.Mock()
        runtime.ai_service = mock.Mock()
        leite = fase1.compra(fase1.item("leite", 2, "litro", 5.0, 10.0, categoria="laticinios"))
        runtime.shopping_assistant = self.assistente({"compras": [leite]})
        runtime.inventory_assistant = self.estoque
        self.assertIn("Compra registrada", runtime._processar_solicitacao("Comprei 2 litros de leite por 10 reais no Moreschi"))
        self.assertIn("leite: cerca de 2,0 litros", runtime._processar_solicitacao("Ainda tenho leite?"))


if __name__ == "__main__":
    unittest.main()
