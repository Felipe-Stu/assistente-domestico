"""
Testes do M26: registro de eventos estruturado (JSON por linha, requisição, etapas, retenção).

Executar na raiz do assistente:
    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from services import logger_service  # noqa: E402
from scripts import ver_logs  # noqa: E402


class BaseLogs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.pasta = os.path.join(self._tmp.name, "logs")
        patcher = mock.patch.object(logger_service.logger, "base_dir", self.pasta)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.log = logger_service.logger

    def eventos(self):
        caminho = os.path.join(self.pasta, logger_service.nome_arquivo_do_dia(datetime.now()))
        if not os.path.exists(caminho):
            return []
        with open(caminho, encoding="utf-8") as arquivo:
            return [json.loads(linha) for linha in arquivo if linha.strip()]


class TestFormato(BaseLogs):
    def test_cada_evento_e_uma_linha_json_com_campos_fixos(self):
        self.log.evento("backup", "gravado", "cópia ok", bytes=123)
        [evento] = self.eventos()
        self.assertEqual(evento["componente"], "backup")
        self.assertEqual(evento["evento"], "gravado")
        self.assertEqual(evento["mensagem"], "cópia ok")
        self.assertEqual(evento["nivel"], "INFO")
        self.assertEqual(evento["bytes"], 123)
        datetime.fromisoformat(evento["ts"])  # carimbo ISO válido, com fuso

    def test_api_antiga_continua_funcionando(self):
        self.log.log_geral("Entrada recebida")
        self.log.log_assistente("Controle de Consumo", "Erro ao gravar")
        geral, assistente = self.eventos()
        self.assertEqual((geral["componente"], geral["nivel"]), ("main", "INFO"))
        self.assertEqual((assistente["componente"], assistente["nivel"]), ("controle_de_consumo", "ERROR"))

    def test_acentos_ficam_legiveis(self):
        self.log.log_geral("Compra de pão e café")
        with open(os.path.join(self.pasta, logger_service.nome_arquivo_do_dia(datetime.now())), encoding="utf-8") as f:
            self.assertIn("pão e café", f.read())


class TestRequisicao(BaseLogs):
    def test_eventos_dentro_da_requisicao_recebem_o_mesmo_id(self):
        with self.log.requisicao(canal="texto") as req:
            self.log.log_geral("dentro")
        self.log.log_geral("fora")
        inicio, dentro, fim, fora = self.eventos()
        self.assertEqual(len(req), 8)
        self.assertEqual({inicio["req"], dentro["req"], fim["req"]}, {req})
        self.assertNotIn("req", fora)
        self.assertEqual(inicio["canal"], "texto")
        self.assertEqual(fim["status"], "ok")
        self.assertIn("duracao_ms", fim)

    def test_erro_fecha_a_requisicao_e_e_repassado(self):
        with self.assertRaises(ValueError):
            with self.log.requisicao():
                raise ValueError("x")
        fim = self.eventos()[-1]
        self.assertEqual((fim["evento"], fim["status"], fim["erro_tipo"], fim["nivel"]),
                         ("requisicao_fim", "erro", "ValueError", "ERROR"))
        self.assertIsNone(self.log.id_requisicao())

    def test_requisicoes_em_threads_nao_se_misturam(self):
        ids = {}

        def trabalhar(nome):
            with self.log.requisicao() as req:
                ids[nome] = req
                self.log.evento("main", "passo", nome=nome)

        threads = [threading.Thread(target=trabalhar, args=(n,)) for n in ("a", "b", "c")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for evento in self.eventos():
            if evento["evento"] == "passo":
                self.assertEqual(evento["req"], ids[evento["nome"]])


class TestEtapas(BaseLogs):
    def test_etapa_registra_duracao_e_status(self):
        with self.log.requisicao() as req:
            with self.log.etapa("roteamento"):
                pass
        etapa = [e for e in self.eventos() if e["evento"] == "etapa"][0]
        self.assertEqual((etapa["etapa"], etapa["status"], etapa["req"]), ("roteamento", "ok", req))
        self.assertGreaterEqual(etapa["duracao_ms"], 0)

    def test_etapa_com_erro_e_registrada_e_repassada(self):
        with self.assertRaises(KeyError):
            with self.log.etapa("banco", componente="db_service"):
                raise KeyError("x")
        [etapa] = self.eventos()
        self.assertEqual((etapa["componente"], etapa["status"], etapa["erro_tipo"]), ("db_service", "erro", "KeyError"))

    def test_cronometrado_mede_cada_tentativa(self):
        chamadas = []
        funcao = self.log.cronometrado("extracao_compras", lambda x: chamadas.append(x) or x * 2)
        self.assertEqual(funcao(2), 4)
        self.assertEqual(funcao(3), 6)
        self.assertEqual([e["etapa"] for e in self.eventos()], ["extracao_compras", "extracao_compras"])


class TestPrivacidade(BaseLogs):
    def test_conteudo_omitido_quando_desligado(self):
        with mock.patch.object(logger_service, "LOG_CONTEUDO", False):
            self.assertEqual(self.log.conteudo("comprei pão"), "[omitido: 11 caracteres]")
        with mock.patch.object(logger_service, "LOG_CONTEUDO", True):
            self.assertEqual(self.log.conteudo("comprei pão"), "comprei pão")


class TestRetencao(BaseLogs):
    def test_arquivos_vencidos_sao_apagados(self):
        os.makedirs(self.pasta)
        hoje = datetime.now()
        antigo = logger_service.nome_arquivo_do_dia(hoje - timedelta(days=45))
        recente = logger_service.nome_arquivo_do_dia(hoje - timedelta(days=3))
        outro = "anotacoes.txt"
        for nome in (antigo, recente, outro):
            Path(self.pasta, nome).write_text("{}\n", encoding="utf-8")

        handler = logger_service.ArquivoDiarioHandler(lambda: self.pasta, retencao_dias=30)
        handler._apagar_vencidos(self.pasta, hoje)
        restantes = set(os.listdir(self.pasta))
        self.assertNotIn(antigo, restantes)
        self.assertTrue({recente, outro} <= restantes)


class TestVerLogs(BaseLogs):
    def test_resumo_por_etapa_e_filtro_por_requisicao(self):
        with self.log.requisicao() as req:
            with self.log.etapa("roteamento"):
                pass
        with self.log.requisicao():
            self.log.evento("main", "erro", nivel="ERROR")

        caminho = Path(self.pasta) / logger_service.nome_arquivo_do_dia(datetime.now())
        eventos = ver_logs.ler_eventos(caminho)
        self.assertTrue(all(e.get("req") == req for e in ver_logs.filtrar(eventos, req=req)))
        self.assertEqual([e["evento"] for e in ver_logs.filtrar(eventos, nivel_minimo="ERROR")], ["erro"])
        resumo = ver_logs.resumo_etapas(eventos)
        self.assertIn("roteamento", resumo)
        self.assertIn("(requisição inteira)", resumo)

    def test_linha_cortada_e_ignorada(self):
        os.makedirs(self.pasta)
        caminho = Path(self.pasta) / "x.jsonl"
        caminho.write_text('{"evento": "a"}\n{"evento": "b', encoding="utf-8")
        self.assertEqual(ver_logs.ler_eventos(caminho), [{"evento": "a"}])


if __name__ == "__main__":
    unittest.main()
