"""
Testes da Fase 1 (base confiável): roteamento, política da nuvem, compras e banco.
Não acessam o Ollama nem o Gemini (LLM, Gemini e banco vetorial são simulados).

Executar na raiz do assistente:
    python -m unittest discover -s tests -v
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from services import db_service as modulo_db  # noqa: E402
from services import gemma_service, llm_provider  # noqa: E402
from services import logger_service  # noqa: E402
from services.ai_service import AIService, TokenExhaustedException  # noqa: E402
from services.db_service import DatabaseService  # noqa: E402
from services.intent_router import rotear_por_regras  # noqa: E402
from services.resilience_service import MaxRetriesExceededException, execute_with_retry  # noqa: E402
from services.shopping_assistant import ShoppingAssistant  # noqa: E402
import app.main as app_main  # noqa: E402


class VetorFalso:
    def __init__(self):
        self.upserts = []
        self.removidos = []

    def upsert_documents(self, documentos):
        self.upserts.extend(documentos)
        return True

    def delete_documents(self, ids):
        self.removidos.extend(ids)
        return True


class LLMFalso:
    def __init__(self, resposta=None, erro=None):
        self.resposta = resposta
        self.erro = erro

    def gerar_json(self, **_kwargs):
        if self.erro:
            raise self.erro
        return self.resposta


def item(produto="leite", quantidade=2.0, unidade="un", valor_unitario=5.0, valor_total=10.0, **extra):
    return {"produto": produto, "quantidade": quantidade, "unidade": unidade, "valor_unitario": valor_unitario,
            "valor_total": valor_total, "categoria": "mercearia", **extra}


def compra(*itens, estabelecimento="Moreschi"):
    return {"estabelecimento": estabelecimento, "itens": list(itens) or [item()]}


class BaseBanco(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        for patcher in (
            mock.patch.object(modulo_db, "DB_PATH", Path(self._tmp.name) / "teste.db"),
            mock.patch.object(logger_service.logger, "base_dir", os.path.join(self._tmp.name, "logs")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.db = DatabaseService()
        self.vetor = VetorFalso()

    def assistente(self, resposta=None, erro=None):
        return ShoppingAssistant(self.db, llm_provider=LLMFalso(resposta, erro), vector_store=self.vetor)

    def contar(self, tabela):
        return self.db.executar_consulta_uma_linha(f"SELECT COUNT(*) FROM {tabela}")[0]


class TestRoteador(unittest.TestCase):
    def test_frases_conhecidas(self):
        casos = [
            ("Comprei 2 litros de leite por 12 reais no Moreschi", "compras", "criar"),
            ("Fui no Moreschi e comprei arroz", "compras", "criar"),
            ("Quanto gastei no Moreschi este mês?", "compras", "consultar"),
            ("O que eu tenho comprado ultimamente?", "compras", "consultar"),
            ("O que preciso comprar esta semana?", "compras", "consultar"),
            ("Qual mercado está com o frango mais barato?", "compras", "consultar"),
            ("Ainda tenho leite em casa?", "inventario", "consultar"),
            ("Acabou o detergente", "inventario", "corrigir"),
            ("O detergente acabou", "inventario", "corrigir"),
            ("Me lembre de pagar a conta de luz amanhã", "agenda", "criar"),
            ("Escreva a documentação do sistema de inventário do MOBA", "projetos", "consultar"),
            ("Desfazer última compra", "compras", "corrigir"),
        ]
        for frase, contexto, acao in casos:
            with self.subTest(frase=frase):
                decisao = rotear_por_regras(frase)
                self.assertEqual((decisao["contexto"], decisao["acao"]), (contexto, acao))
                self.assertEqual(decisao["dificuldade"], "facil")
                gemma_service._validar_schema_orquestrador(decisao)

    def test_frases_ambiguas_seguem_para_o_llm(self):
        for frase in ["Vou programar agora", "Bom dia, tudo bem?", "Qual a capital da França?", ""]:
            with self.subTest(frase=frase):
                self.assertIsNone(rotear_por_regras(frase))

    def test_mudanca_de_contexto(self):
        self.assertFalse(rotear_por_regras("Comprei arroz")["mudanca_de_contexto"])
        self.assertFalse(rotear_por_regras("Comprei arroz", "compras")["mudanca_de_contexto"])
        self.assertTrue(rotear_por_regras("Comprei arroz", "geral")["mudanca_de_contexto"])

    def test_regra_dispensa_o_llm(self):
        with mock.patch.object(gemma_service, "obter_provedor_local") as provedor:
            decisao = gemma_service.orquestrar_requisicao("Quanto gastei este mês?")
        provedor.assert_not_called()
        self.assertEqual(decisao["contexto"], "compras")


class TestDatas(BaseBanco):
    HOJE = date(2026, 11, 3)  # terça-feira

    def resolver(self, texto):
        return self.assistente()._resolver_data(texto, hoje=self.HOJE)

    def test_datas_resolvidas(self):
        casos = {
            "comprei arroz": "2026-11-03",
            "comprei arroz hoje": "2026-11-03",
            "comprei arroz ontem": "2026-11-02",
            "comprei arroz anteontem": "2026-11-01",
            "comprei arroz há 5 dias": "2026-10-29",
            "comprei arroz no sábado": "2026-10-31",
            "comprei arroz na terça": "2026-10-27",
            "comprei arroz dia 28": "2026-10-28",
            "comprei arroz dia 12 de agosto": "2026-08-12",
            "comprei arroz em 15/10": "2026-10-15",
            "comprei arroz em 15/12": "2025-12-15",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(self.resolver(texto), (esperado, None))

    def test_meia_unidade_nao_e_data(self):
        self.assertEqual(self.resolver("comprei 1/2 kg de queijo"), ("2026-11-03", None))

    def test_datas_vagas_ou_conflitantes_geram_duvida(self):
        for texto in ["comprei arroz semana passada", "comprei arroz ontem e feijão anteontem", "comprei arroz dia 31/02"]:
            with self.subTest(texto=texto):
                self.assertIsNotNone(self.resolver(texto)[1])


class TestPreparacaoCompra(BaseBanco):
    TEXTO_ARROZ = "Fui no Moreschi e comprei um pacote de arroz de 5 kg por 27,90"

    def preparar(self, resposta, texto="Comprei leite por 10 reais no Moreschi"):
        return self.assistente(resposta).preparar_compra(texto)

    def test_compra_consistente_nao_gera_duvida(self):
        preparada = self.preparar({"compras": [compra()]})
        self.assertEqual(preparada["duvidas"], [])
        self.assertEqual(self.contar("compras"), 0)

    def test_preco_de_embalagem_interpretado_como_quilo_gera_duvida(self):
        errado = item("arroz", 5.0, "kg", 27.90, 139.50)
        preparada = self.preparar({"compras": [compra(errado)]}, self.TEXTO_ARROZ)
        self.assertTrue(any("arroz" in d and "embalagem" in d for d in preparada["duvidas"]))

    def test_embalagem_correta_grava_sem_duvida(self):
        correto = item("arroz", 1.0, "un", 27.90, 27.90, embalagem_quantidade=5.0, embalagem_unidade="kg")
        preparada = self.preparar({"compras": [compra(correto)]}, self.TEXTO_ARROZ)
        self.assertEqual(preparada["duvidas"], [])
        self.assertEqual(preparada["compras"][0]["valor_total_compra"], 27.90)

    def test_preco_por_quilo_nao_gera_duvida(self):
        frango = item("frango", 3.124, "kg", 16.99, 53.08)
        texto = "No Moreschi comprei frango por r$ 16,99 o quilo, comprei 3 kg 124 g"
        self.assertEqual(self.preparar({"compras": [compra(frango)]}, texto)["duvidas"], [])

    def test_total_divergente_e_mantido_com_duvida(self):
        preparada = self.preparar({"compras": [compra(item(valor_total=99.0))]})
        self.assertTrue(any("total diferente" in d for d in preparada["duvidas"]))
        self.assertEqual(preparada["compras"][0]["itens"][0]["valor_total"], 99.0)

    def test_mercado_e_preco_ausentes_geram_duvida(self):
        preparada = self.preparar({"compras": [compra(item(valor_unitario=0, valor_total=0), estabelecimento="Não informado")]})
        self.assertIn("Loja não informada.", preparada["duvidas"])
        self.assertIn("Compra com total zero.", preparada["duvidas"])
        self.assertTrue(any("preço não informado" in d for d in preparada["duvidas"]))

    def test_resposta_sem_itens_nao_gera_compra(self):
        for resposta in ({}, {"compras": []}, {"compras": [{"itens": [{"produto": None}]}]}):
            with self.subTest(resposta=resposta):
                self.assertEqual(self.preparar(resposta)["compras"], [])

    def test_data_do_texto_prevalece_sobre_o_llm(self):
        dados = compra()
        dados["data_compra"] = "1999-01-01"
        preparada = self.preparar({"compras": [dados]}, "Comprei leite no Moreschi hoje")
        self.assertNotEqual(preparada["compras"][0]["data_compra"], "1999-01-01")


class TestGravacao(BaseBanco):
    def preparadas(self, *compras):
        for c in compras:
            c["data_compra"] = "2026-11-03"
            c["valor_total_compra"] = sum(i["valor_total"] for i in c["itens"])
        return list(compras)

    def test_transacao_unica_nao_grava_parcialmente(self):
        invalida = compra(estabelecimento="B")
        invalida["itens"][0]["quantidade"] = "invalida"
        with self.assertRaises(ValueError):
            self.assistente().registrar_compras(self.preparadas(compra(estabelecimento="A"), invalida))
        self.assertEqual(self.contar("compras"), 0)
        self.assertEqual(self.contar("itens_compra"), 0)

    def test_retry_da_preparacao_nao_duplica(self):
        chamadas = []

        class LLMInstavel:
            def gerar_json(self, **_kwargs):
                chamadas.append(1)
                if len(chamadas) < 3:
                    raise ConnectionError("Ollama indisponível")
                return {"compras": [compra()]}

        assistente = ShoppingAssistant(self.db, llm_provider=LLMInstavel(), vector_store=self.vetor)
        preparada = execute_with_retry(assistente.preparar_compra, args=("Comprei leite",), max_tentativas=3, tempo_espera=0)
        self.assertEqual(self.contar("compras"), 0)
        assistente.registrar_compras(preparada["compras"])
        self.assertEqual(len(chamadas), 3)
        self.assertEqual(self.contar("compras"), 1)

    def test_embalagem_gravada(self):
        dados = compra(item("arroz", 1.0, "un", 27.9, 27.9, embalagem_quantidade=5.0, embalagem_unidade="kg"))
        self.assistente().registrar_compras(self.preparadas(dados))
        linha = self.db.executar_consulta_uma_linha("SELECT embalagem_quantidade, embalagem_unidade FROM itens_compra")
        self.assertEqual(linha, (5.0, "kg"))

    def test_desfazer_remove_todo_o_ultimo_registro(self):
        assistente = self.assistente()
        assistente.registrar_compras(self.preparadas(compra(estabelecimento="Antiga")))
        assistente.registrar_compras(self.preparadas(compra(estabelecimento="A"), compra(item(), item("pão", 1, "un", 8, 8), estabelecimento="B")))

        mensagem = assistente.desfazer_ultimo_registro()

        self.assertIn("2 registro(s)", mensagem)
        self.assertEqual([c[0] for c in self.db.executar_consulta("SELECT nome_comercio FROM compras")], ["Antiga"])
        self.assertEqual(self.contar("itens_compra"), 1)
        self.assertIn("purchase_item_live_3_2", self.vetor.removidos)

    def test_desfazer_nao_remove_duas_vezes(self):
        assistente = self.assistente()
        assistente.registrar_compras(self.preparadas(compra(estabelecimento="A")))
        assistente.registrar_compras(self.preparadas(compra(estabelecimento="B")))
        assistente.desfazer_ultimo_registro()
        self.assertIn("Não há compra", assistente.desfazer_ultimo_registro())
        self.assertEqual(self.contar("compras"), 1)


class TestMigracao(BaseBanco):
    def test_migra_banco_v1_preservando_dados(self):
        caminho = Path(self._tmp.name) / "v1.db"
        conn = sqlite3.connect(caminho)
        conn.executescript("""
            CREATE TABLE compras (id INTEGER PRIMARY KEY AUTOINCREMENT, data_compra TEXT NOT NULL,
                                  nome_comercio TEXT, total_gasto REAL NOT NULL);
            CREATE TABLE itens_compra (id INTEGER PRIMARY KEY AUTOINCREMENT, compra_id INTEGER NOT NULL,
                                       produto TEXT NOT NULL, marca TEXT, quantidade REAL NOT NULL, unidade TEXT,
                                       valor_unitario REAL NOT NULL, valor_total REAL NOT NULL, categoria TEXT);
            INSERT INTO compras VALUES (1, '2026-08-10', 'Moreschi', 10.0);
            INSERT INTO itens_compra VALUES (1, 1, 'leite', '', 2, 'un', 5, 10, 'laticinio');
            PRAGMA user_version = 1;
        """)
        conn.close()

        with mock.patch.object(modulo_db, "DB_PATH", caminho):
            db = DatabaseService()
            DatabaseService()  # A segunda inicialização deve ser inofensiva

        self.assertEqual(db.executar_consulta_uma_linha("PRAGMA user_version")[0], 9)  # v3 entradas, v4 produtos, v5 centavos, v6 estoque, v7 chave do documento, v8 contexto do histórico, v9 observações
        self.assertEqual(db.executar_consulta_uma_linha("SELECT total_centavos FROM compras")[0], 1000)
        # M07: o item antigo entrou no catálogo, com a categoria convertida para a lista fechada
        self.assertEqual(db.executar_consulta("SELECT p.nome, p.categoria FROM itens_compra i JOIN produtos p ON p.id = i.produto_id"),
                         [("leite", "laticinios")])
        self.assertEqual(db.executar_consulta_uma_linha("SELECT categoria FROM itens_compra")[0], "laticinio")  # original preservado
        self.assertEqual(db.executar_consulta_uma_linha("SELECT produto, embalagem_quantidade FROM itens_compra"), ("leite", None))


class TestGemini(unittest.TestCase):
    def test_inicia_sem_chave(self):
        ambiente = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
        with mock.patch.dict(os.environ, ambiente, clear=True):
            self.assertFalse(AIService().disponivel())

    def test_prompt_geral_com_historico_legivel(self):
        servico = AIService()
        with mock.patch.object(servico, "chamar_llm", return_value="ok") as chamar:
            servico.processar_requisicao_complexa("Qual a capital da França?", [{"role": "user", "content": "Oi"}])
        prompt = chamar.call_args.args[0]
        self.assertNotIn("compras", prompt)
        self.assertIn("Usuário: Oi", prompt)
        self.assertFalse(chamar.call_args.kwargs["json_output"])

    def test_excecao_fatal_nao_repete(self):
        chamadas = []

        def falhar():
            chamadas.append(1)
            raise TokenExhaustedException("cota")

        with self.assertRaises(TokenExhaustedException):
            execute_with_retry(falhar, max_tentativas=3, tempo_espera=0, excecoes_fatais=(TokenExhaustedException,))
        self.assertEqual(len(chamadas), 1)


class TestRuntime(BaseBanco):
    def setUp(self):
        super().setUp()
        self.emissoes = []
        for patcher in (
            mock.patch.object(app_main, "emitir_electron", lambda tipo, payload=None: self.emissoes.append((tipo, payload))),
            mock.patch.object(app_main, "TEMPO_RETRY", 0),
            mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        self.runtime = app_main.AssistenteRuntime()
        self.runtime.db_service = self.db
        self.runtime.ai_service = mock.Mock()
        self.runtime.ai_service.disponivel.return_value = True
        self.runtime.ai_service.processar_requisicao_complexa.return_value = "Resposta da nuvem"
        self.runtime.shopping_assistant = self.assistente({"compras": [compra()]})
        self.runtime.inventory_assistant = mock.Mock()
        self.runtime.context_retrieval = mock.Mock()
        self.runtime.context_retrieval.montar_contexto_recuperado.return_value = ""
        self.runtime.memory_service = mock.Mock()
        self.gemini = self.runtime.ai_service.processar_requisicao_complexa

    def decidir(self, contexto, dificuldade="facil", acao="consultar"):
        decisao = {"dificuldade": dificuldade, "mudanca_de_contexto": False, "contexto": contexto, "acao": acao}
        return mock.patch.object(app_main, "orquestrar_requisicao", return_value=decisao)

    def local_indisponivel(self):
        return mock.patch.object(app_main, "orquestrar_requisicao", side_effect=ConnectionError("Ollama parado"))

    def responder(self, texto):
        return self.runtime._processar_solicitacao(texto)

    def test_registro_sem_duvida_grava_direto(self):
        resposta = self.responder("Comprei leite por 10 reais no Moreschi")
        self.assertIn("Compra registrada", resposta)
        self.assertEqual(self.contar("compras"), 1)

    def test_m26_requisicao_registra_etapas_com_o_mesmo_id(self):
        self.responder("Comprei leite por 10 reais no Moreschi")
        pasta = logger_service.logger.base_dir
        eventos = []
        for nome in sorted(os.listdir(pasta)):
            if nome.startswith(logger_service.PREFIXO_ARQUIVO):
                with open(os.path.join(pasta, nome), encoding="utf-8") as arquivo:
                    eventos += [json.loads(linha) for linha in arquivo if linha.strip()]
        inicio = next(e for e in eventos if e["evento"] == "requisicao_inicio")
        da_requisicao = [e for e in eventos if e.get("req") == inicio["req"]]
        etapas = {e["etapa"] for e in da_requisicao if e["evento"] == "etapa"}
        self.assertTrue({"extracao_compras", "banco"} <= etapas, etapas)
        self.assertEqual(da_requisicao[-1]["evento"], "requisicao_fim")
        self.assertEqual(da_requisicao[-1]["status"], "ok")

    def test_consulta_de_compras_nao_grava(self):
        resposta = self.responder("O que eu tenho comprado ultimamente?")
        self.assertIn("Não encontrei compras nos últimos 30 dias", resposta)   # M19: consulta de verdade
        self.assertEqual(self.contar("compras"), 0)

    def test_confirmacao_positiva_grava(self):
        self.runtime.shopping_assistant = self.assistente({"compras": [compra(estabelecimento="Não informado")]})
        resposta = self.responder("Comprei leite")
        self.assertIn("Responda", resposta)
        self.assertEqual(self.contar("compras"), 0)
        self.assertIn("Compra registrada", self.responder("Sim!"))
        self.assertEqual(self.contar("compras"), 1)
        self.assertIsNone(self.runtime.compra_pendente)

    def test_confirmacao_negativa_descarta(self):
        self.runtime.shopping_assistant = self.assistente({"compras": [compra(estabelecimento="Não informado")]})
        self.responder("Comprei leite")
        self.assertIn("descartada", self.responder("não"))
        self.assertEqual(self.contar("compras"), 0)

    def test_resposta_indefinida_mantem_pendencia(self):
        self.runtime.shopping_assistant = self.assistente({"compras": [compra(estabelecimento="Não informado")]})
        self.assertIn("Em qual loja", self.responder("Comprei leite"))
        self.assertIn("Ficou assim", self.responder("Moreschi"))     # a resposta preenche a loja
        self.assertIn("aguardando confirmação", self.responder("talvez"))
        self.assertIsNotNone(self.runtime.compra_pendente)
        self.assertEqual(self.contar("compras"), 0)

    def test_desfazer_pelo_chat(self):
        self.responder("Comprei leite por 10 reais no Moreschi")
        self.assertIn("desfeita", self.responder("Desfazer última compra"))
        self.assertEqual(self.contar("compras"), 0)

    def test_contextos_restritos_nao_vao_a_nuvem(self):
        for contexto in ("compras", "inventario", "agenda", "programacao"):
            with self.subTest(contexto=contexto), self.decidir(contexto, "medio_dificil"), \
                    mock.patch.object(app_main, "executar_assistente_local", return_value="local"):
                self.responder("Pergunte ao Gemini: pedido difícil")
        self.gemini.assert_not_called()

    def test_ollama_parado_nao_envia_frase_desconhecida_a_nuvem(self):
        with self.local_indisponivel():
            resposta = self.responder("Frase qualquer sem regra")
        self.assertEqual(resposta, app_main.MSG_IA_LOCAL_INDISPONIVEL)
        self.gemini.assert_not_called()

    # M17 — Ollama fechado: resposta imediata, sem repetições e com "Tentar de novo"
    def ollama_fora(self):
        return llm_provider.OllamaIndisponivelException("O Ollama não respondeu em 2 s.")

    def test_ollama_fora_no_orquestrador_responde_sem_repetir(self):
        with mock.patch.object(app_main, "orquestrar_requisicao", side_effect=self.ollama_fora()) as orq, \
                mock.patch.object(app_main, "TEMPO_RETRY", 5):
            inicio = time.perf_counter()
            resposta = self.responder("Frase qualquer sem regra")
            duracao = time.perf_counter() - inicio
        self.assertEqual(resposta, app_main.MSG_OLLAMA_FORA)
        self.assertEqual(orq.call_count, 1)
        self.assertLess(duracao, 1.0)  # antes: 3 tentativas com 2 esperas de TEMPO_RETRY
        self.gemini.assert_not_called()
        self.assertIn(("assistant_message", {"text": app_main.MSG_OLLAMA_FORA, "tentar_novamente": "Frase qualquer sem regra"}),
                      self.emissoes)

    def test_ollama_fora_em_compras_nao_grava_nem_vai_a_nuvem(self):
        self.runtime.shopping_assistant = self.assistente(erro=self.ollama_fora())
        with self.decidir("compras", acao="criar"):
            resposta = self.responder("Comprei leite por 10 reais")
        self.assertEqual(resposta, app_main.MSG_OLLAMA_FORA)
        self.assertEqual(self.contar("compras"), 0)
        self.gemini.assert_not_called()

    def test_ollama_fora_em_pergunta_geral_usa_a_nuvem(self):
        with self.decidir("geral"), mock.patch.object(app_main, "executar_assistente_local", side_effect=self.ollama_fora()) as local:
            self.assertEqual(self.responder("Conte uma curiosidade"), "Resposta da nuvem")
        self.assertEqual(local.call_count, 1)

    def test_falha_local_em_compras_nao_vai_a_nuvem(self):
        self.runtime.shopping_assistant = self.assistente(erro=ConnectionError("Ollama parado"))
        resposta = self.responder("Comprei leite por 10 reais")
        self.assertEqual(resposta, app_main.MSG_IA_LOCAL_INDISPONIVEL)
        self.assertEqual(self.contar("compras"), 0)
        self.gemini.assert_not_called()

    def test_pergunta_geral_vai_a_nuvem_quando_pedida(self):
        with self.decidir("geral"):
            self.assertEqual(self.responder("Pergunte ao Gemini quem ganhou a Copa de 2022"), "Resposta da nuvem")

    def test_m16_dificil_sem_pedido_fica_local(self):
        with self.decidir("geral", "medio_dificil"), mock.patch.object(app_main, "executar_assistente_local", return_value="local"):
            self.assertEqual(self.responder("Compare a economia do Brasil e da Argentina"), "local")
        self.gemini.assert_not_called()

    def test_falha_local_em_pergunta_geral_usa_a_nuvem(self):
        with self.decidir("geral"), mock.patch.object(app_main, "executar_assistente_local", side_effect=ConnectionError()):
            self.assertEqual(self.responder("Conte uma curiosidade"), "Resposta da nuvem")

    def test_sem_chave_pergunta_geral_fica_local(self):
        self.runtime.ai_service.disponivel.return_value = False
        with self.decidir("geral", "medio_dificil"), mock.patch.object(app_main, "executar_assistente_local", return_value="local"):
            self.assertEqual(self.responder("Pesquise na internet algo"), "local")
        self.gemini.assert_not_called()

    def test_modo_qwen_nao_usa_a_nuvem(self):
        llm_provider.MODO_QWEN_ATIVO = True
        with self.decidir("geral", "medio_dificil"), mock.patch.object(app_main, "executar_assistente_local", return_value="local"):
            self.assertEqual(self.responder("Pergunte ao Gemini: analise este código"), "local")
        self.gemini.assert_not_called()

    def test_nuvem_nao_recebe_historico_nem_memoria_restritos(self):
        self.runtime.sessao.contexto_ativo = "compras"
        self.runtime.sessao.historico = [{"role": "user", "content": "Comprei remédio"}]
        with self.decidir("geral"):
            self.responder("Pesquise na internet algo")
        self.assertEqual(self.gemini.call_args.args[1], [])
        filtro = self.runtime.context_retrieval.montar_contexto_recuperado.call_args.kwargs["assistant"]
        self.assertEqual(filtro, ["geral", "outro"])

    def test_cota_esgotada_informa_sem_repetir(self):
        self.gemini.side_effect = TokenExhaustedException("cota")
        with self.decidir("geral"):
            self.assertIn("limite de uso", self.responder("Pesquise na internet algo"))
        self.assertEqual(self.gemini.call_count, 1)

    def test_agenda_nao_exibe_json(self):
        resposta = self.responder("Me lembre de pagar a conta de luz amanhã")
        self.assertNotIn("{", resposta)
        self.assertNotIn('"titulo"', resposta)

    def test_documentacao_sem_caminho_pede_a_pasta(self):
        resposta = self.responder("Escreva a documentação do sistema de inventário do MOBA")
        self.assertIn("Informe o caminho", resposta)
        self.gemini.assert_not_called()


if __name__ == "__main__":
    unittest.main()
