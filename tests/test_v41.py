"""
Testes da V4.1: saída estruturada por JSON Schema (M03) e carga do modelo de
embeddings em segundo plano (M04). Não acessam o Ollama, o ChromaDB nem o
SentenceTransformers reais: os três são simulados.

Executar na raiz do assistente:
    python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from services import esquemas, gemma_service, llm_provider, logger_service  # noqa: E402
from services.shopping_assistant import ShoppingAssistant  # noqa: E402
from services.vector import embedding_service as modulo_emb  # noqa: E402
from services.vector import vector_store_service as modulo_vs  # noqa: E402
from services.vector.embedding_service import EmbeddingService  # noqa: E402
from services.vector.vector_store_service import VectorDocument, VectorStoreService  # noqa: E402
import app.main as app_main  # noqa: E402

CLASSIFICACAO = '{"dificuldade": "facil", "mudanca_de_contexto": false, "contexto": "geral", "acao": "consultar"}'


class BaseSemLogs(unittest.TestCase):
    """Redireciona os logs em arquivo para uma pasta temporária."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.object(logger_service.logger, "base_dir", os.path.join(self._tmp.name, "logs"))
        patcher.start()
        self.addCleanup(patcher.stop)
        llm_provider.invalidar_saude_ollama()
        self.addCleanup(llm_provider.invalidar_saude_ollama)


# =============================================================================
# M03 — Saída estruturada
# =============================================================================

class ClienteOllamaFalso:
    """Registra o `format` de cada chamada; pode recusar esquemas como uma biblioteca antiga."""

    def __init__(self, recusar_esquema=False):
        self.formatos = []
        self.recusar_esquema = recusar_esquema

    def list(self):
        return {"models": []}

    def chat(self, **kwargs):
        self.formatos.append(kwargs.get("format"))
        self.ultimo = kwargs
        if self.recusar_esquema and isinstance(kwargs.get("format"), dict):
            raise TypeError("format deve ser '' ou 'json'")
        return {"message": {"content": CLASSIFICACAO}}


class TestEsquemas(unittest.TestCase):
    def test_enums_do_orquestrador_sao_aceitos_pela_validacao(self):
        propriedades = esquemas.ESQUEMA_ORQUESTRADOR["properties"]
        for campo, permitidos in gemma_service.VALORES_PERMITIDOS.items():
            self.assertTrue(set(propriedades[campo]["enum"]) <= permitidos, campo)

    def test_campos_obrigatorios_do_orquestrador(self):
        self.assertEqual(
            set(esquemas.ESQUEMA_ORQUESTRADOR["required"]),
            {"dificuldade", "mudanca_de_contexto", "contexto", "acao"},
        )

    def test_item_de_compra_exige_os_campos_usados_na_validacao(self):
        item = esquemas.ESQUEMA_COMPRAS["properties"]["compras"]["items"]["properties"]["itens"]["items"]
        self.assertEqual(
            set(item["required"]), {"produto", "quantidade", "unidade", "valor_unitario", "valor_total"}
        )
        self.assertIn("null", item["properties"]["marca"]["type"])


class TestProvedorLocal(BaseSemLogs):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def gerar(self, cliente, esquema, ligado=True):
        with mock.patch.object(llm_provider.ollama, "Client", return_value=cliente), \
                mock.patch.object(llm_provider, "OLLAMA_SAIDA_ESTRUTURADA", ligado):
            provedor = llm_provider.LocalLLMProvider(modelo="modelo-teste")
            return provedor.gerar_json("sistema", "usuario", esquema=esquema)

    def test_esquema_vai_no_parametro_format(self):
        cliente = ClienteOllamaFalso()
        dados = self.gerar(cliente, esquemas.ESQUEMA_ORQUESTRADOR)
        self.assertEqual(cliente.formatos, [esquemas.ESQUEMA_ORQUESTRADOR])
        self.assertEqual(dados["contexto"], "geral")

    def test_sem_esquema_usa_json_simples(self):
        cliente = ClienteOllamaFalso()
        self.gerar(cliente, None)
        self.assertEqual(cliente.formatos, ["json"])

    def test_opcao_desligada_ignora_o_esquema(self):
        cliente = ClienteOllamaFalso()
        self.gerar(cliente, esquemas.ESQUEMA_ORQUESTRADOR, ligado=False)
        self.assertEqual(cliente.formatos, ["json"])

    def test_biblioteca_antiga_recai_em_json_simples(self):
        cliente = ClienteOllamaFalso(recusar_esquema=True)
        dados = self.gerar(cliente, esquemas.ESQUEMA_ORQUESTRADOR)
        self.assertEqual(cliente.formatos, [esquemas.ESQUEMA_ORQUESTRADOR, "json"])
        self.assertEqual(dados["acao"], "consultar")

    def test_erro_de_conexao_nao_dispara_segunda_chamada(self):
        cliente = ClienteOllamaFalso()
        cliente.chat = mock.Mock(side_effect=ConnectionError("Ollama parado"))
        with self.assertRaises(llm_provider.OllamaIndisponivelException):
            self.gerar(cliente, esquemas.ESQUEMA_ORQUESTRADOR)
        self.assertEqual(cliente.chat.call_count, 1)


class TestRaciocinio(BaseSemLogs):
    def gerar(self, raciocinio, env=None):
        cliente = ClienteOllamaFalso()
        with mock.patch.object(llm_provider.ollama, "Client", return_value=cliente), \
                mock.patch.object(llm_provider, "OLLAMA_RACIOCINIO", env):
            llm_provider.LocalLLMProvider(modelo="modelo-teste").gerar_json("s", "u", raciocinio=raciocinio)
        return cliente.ultimo

    def test_sem_preferencia_nao_envia_think(self):
        self.assertNotIn("think", self.gerar(None))

    def test_raciocinio_desligado_envia_think_false(self):
        self.assertIs(self.gerar(False)["think"], False)

    def test_env_prevalece_sobre_o_codigo(self):
        self.assertIs(self.gerar(False, env=True)["think"], True)

    def test_modelo_sem_suporte_repete_sem_think(self):
        cliente = ClienteOllamaFalso()
        original = cliente.chat
        chamadas = []

        def chat(**kwargs):
            chamadas.append(dict(kwargs))
            if "think" in kwargs:
                raise llm_provider.ollama.ResponseError('"modelo-teste" does not support thinking')
            return original(**kwargs)
        cliente.chat = chat
        with mock.patch.object(llm_provider.ollama, "Client", return_value=cliente), \
                mock.patch.object(llm_provider, "OLLAMA_RACIOCINIO", None):
            dados = llm_provider.LocalLLMProvider(modelo="modelo-teste").gerar_json("s", "u", raciocinio=False)
        self.assertEqual(len(chamadas), 2)
        self.assertNotIn("think", chamadas[1])
        self.assertEqual(dados["contexto"], "geral")


class ProvedorEspiao:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = []

    def gerar_json(self, *args, **kwargs):
        self.chamadas.append(kwargs)
        return self.resposta


class TestUsoDosEsquemas(BaseSemLogs):
    def test_orquestrador_envia_o_esquema(self):
        espiao = ProvedorEspiao(
            {"dificuldade": "facil", "mudanca_de_contexto": False, "contexto": "geral", "acao": "consultar"}
        )
        with mock.patch.object(gemma_service, "obter_provedor_local", return_value=espiao), \
                mock.patch.object(gemma_service, "ORQUESTRADOR_MODO", "contextos"), \
                mock.patch.object(llm_provider, "MODO_QWEN_ATIVO", False):
            gemma_service.orquestrar_requisicao("Qual é a capital da França?")
        self.assertIs(espiao.chamadas[0]["esquema"], esquemas.ESQUEMA_ORQUESTRADOR)
        self.assertIs(espiao.chamadas[0]["raciocinio"], False)

    def test_extracao_de_compras_envia_o_esquema(self):
        espiao = ProvedorEspiao({"compras": []})
        assistente = ShoppingAssistant(mock.Mock(), llm_provider=espiao, vector_store=mock.Mock())
        assistente.preparar_compra("Comprei leite por 10 reais no Moreschi")
        self.assertIs(espiao.chamadas[0]["esquema"], esquemas.ESQUEMA_COMPRAS)


# =============================================================================
# M04 — Embeddings em segundo plano
# =============================================================================

class ModeloFalso:
    def encode(self, entrada, **_kwargs):
        vetor = mock.Mock()
        vetor.tolist.return_value = [0.1, 0.2] if isinstance(entrada, str) else [[0.1, 0.2] for _ in entrada]
        return vetor


class BaseEmbeddings(BaseSemLogs):
    """Isola o estado de classe do EmbeddingService e simula o SentenceTransformers."""

    def setUp(self):
        super().setUp()
        self.liberar_carga = threading.Event()
        self.liberar_carga.set()
        self.cargas = 0
        self.falhar = False

        self.argumentos_carga = []

        def construir(_nome, **kwargs):
            self.argumentos_carga.append(kwargs)
            self.liberar_carga.wait(timeout=5)
            self.cargas += 1
            if self.falhar:
                raise OSError("modelo ausente")
            return ModeloFalso()

        modulo_falso = types.ModuleType("sentence_transformers")
        modulo_falso.SentenceTransformer = construir
        for patcher in (
            mock.patch.dict(sys.modules, {"sentence_transformers": modulo_falso}),
            mock.patch.object(EmbeddingService, "_instancia_modelo", None),
            mock.patch.object(EmbeddingService, "_thread_carga", None),
            mock.patch.object(EmbeddingService, "_erro_carga", None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.liberar_carga.set)


class TestEmbeddingService(BaseEmbeddings):
    def test_construtor_nao_carrega_o_modelo(self):
        EmbeddingService()
        self.assertEqual(self.cargas, 0)
        self.assertFalse(EmbeddingService.pronto())

    def test_primeiro_uso_carrega_uma_unica_vez(self):
        servico = EmbeddingService()
        self.assertEqual(servico.gerar_embedding("café"), [0.1, 0.2])
        self.assertEqual(len(servico.gerar_embeddings_em_lote(["a", "b"])), 2)
        self.assertEqual(self.cargas, 1)
        self.assertTrue(EmbeddingService.pronto())

    def test_carga_em_segundo_plano_avisa_ao_concluir(self):
        avisos = []
        thread = EmbeddingService().carregar_em_segundo_plano(lambda ok, erro: avisos.append((ok, erro)))
        thread.join(timeout=5)
        self.assertEqual(avisos, [(True, None)])
        self.assertTrue(EmbeddingService.pronto())
        self.assertFalse(EmbeddingService.carregando())

    def test_segunda_chamada_reaproveita_a_carga_em_andamento(self):
        self.liberar_carga.clear()
        servico = EmbeddingService()
        primeira = servico.carregar_em_segundo_plano()
        segunda = servico.carregar_em_segundo_plano()
        self.assertIs(primeira, segunda)
        self.assertTrue(EmbeddingService.carregando())
        self.liberar_carga.set()
        primeira.join(timeout=5)
        self.assertEqual(self.cargas, 1)

    def test_falha_de_carga_nao_e_repetida_a_cada_chamada(self):
        self.falhar = True
        avisos = []
        servico = EmbeddingService()
        servico.carregar_em_segundo_plano(lambda ok, erro: avisos.append((ok, erro))).join(timeout=5)
        self.assertEqual(avisos[0][0], False)
        self.assertIn("modelo ausente", avisos[0][1])
        self.assertEqual(servico.gerar_embedding("café"), [])
        # Uma única carga com falha = tentativa no cache local + tentativa com rede; nada é repetido depois
        self.assertEqual(self.cargas, 2)

    def test_carga_usa_cache_local_e_dispositivo_configurado(self):
        EmbeddingService().carregar_em_segundo_plano().join(timeout=5)
        self.assertEqual(self.argumentos_carga[0], {"device": modulo_emb.EMBEDDING_DEVICE, "local_files_only": True})


class ColecaoFalsa:
    def __init__(self):
        self.upserts = []
        self.consultas = 0

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def query(self, **_kwargs):
        self.consultas += 1
        return {"ids": [["doc1"]], "documents": [["texto"]], "metadatas": [[{}]], "distances": [[0.1]]}


class TestVectorStore(BaseEmbeddings):
    def setUp(self):
        super().setUp()
        self.colecao = ColecaoFalsa()
        cliente = mock.Mock()
        cliente.get_or_create_collection.return_value = self.colecao
        patcher = mock.patch.object(VectorStoreService, "_client", cliente)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.loja = VectorStoreService(persistent_dir=self._tmp.name)

    def test_busca_e_ignorada_enquanto_o_modelo_carrega(self):
        self.liberar_carga.clear()
        thread = self.loja.embedding_service.carregar_em_segundo_plano()
        self.assertEqual(self.loja.search_similarity("café"), [])
        self.assertEqual(self.colecao.consultas, 0)
        self.liberar_carga.set()
        thread.join(timeout=5)
        self.assertEqual(len(self.loja.search_similarity("café")), 1)

    def test_busca_sem_carga_previa_carrega_na_hora(self):
        # Scripts de manutenção não usam a carga em segundo plano
        self.assertEqual(len(self.loja.search_similarity("café")), 1)
        self.assertEqual(self.cargas, 1)

    def test_upsert_e_cancelado_sem_embeddings(self):
        self.falhar = True
        gravou = self.loja.upsert_documents([VectorDocument(id="a", content="texto")])
        self.assertFalse(gravou)
        self.assertEqual(self.colecao.upserts, [])

    def test_upsert_grava_com_embeddings(self):
        self.assertTrue(self.loja.upsert_documents([VectorDocument(id="a", content="texto")]))
        self.assertEqual(self.colecao.upserts[0]["embeddings"], [[0.1, 0.2]])


class TestRuntimeMemoria(BaseSemLogs):
    def test_memoria_e_gravada_depois_da_resposta(self):
        ordem = []
        decisao = {"dificuldade": "facil", "mudanca_de_contexto": False, "contexto": "geral", "acao": "consultar"}
        with mock.patch.object(app_main, "emitir_electron",
                               lambda tipo, payload=None: ordem.append(tipo) if tipo == "assistant_message" else None), \
                mock.patch.object(app_main, "orquestrar_requisicao", return_value=decisao), \
                mock.patch.object(app_main, "executar_assistente_local", return_value="Paris."), \
                mock.patch.object(app_main, "TEMPO_RETRY", 0):
            runtime = app_main.AssistenteRuntime()
            runtime.ai_service = mock.Mock()
            runtime.context_retrieval = mock.Mock()
            runtime.context_retrieval.montar_contexto_recuperado.return_value = ""
            runtime.memory_service = mock.Mock()
            runtime.memory_service.salvar_memoria_longo_prazo.side_effect = lambda **_k: ordem.append("memoria")
            resposta = runtime._processar_solicitacao("Qual é a capital da França?")
        self.assertEqual(resposta, "Paris.")
        self.assertEqual(ordem, ["assistant_message", "memoria"])


if __name__ == "__main__":
    unittest.main()
