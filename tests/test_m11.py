"""
Testes do M11: cópia de segurança automática, com as correções P13 (reconstrução dos
embeddings preserva as memórias) e P22 (conexões SQLite fechadas ao sair do `with`).

Executar na raiz do assistente:
    python -m unittest discover -s tests -v
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import warnings
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from services import db_service as modulo_db, logger_service  # noqa: E402
from services.backup_service import ARQUIVO_CHROMA, ARQUIVO_MANIFESTO, BackupError, BackupService  # noqa: E402
from services.db_service import DatabaseService  # noqa: E402
from scripts import rebuild_embeddings  # noqa: E402


class BaseTemporaria(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        patcher = mock.patch.object(logger_service.logger, "base_dir", str(self.raiz / "logs"))
        patcher.start()
        self.addCleanup(patcher.stop)


class BaseBackup(BaseTemporaria):
    def setUp(self):
        super().setUp()
        self.db = self.raiz / "casa.db"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE compras (id INTEGER PRIMARY KEY, nome TEXT)")
        conn.execute("INSERT INTO compras (nome) VALUES ('café')")
        conn.commit()
        conn.close()

        self.chroma = self.raiz / "chroma_db"
        (self.chroma / "segmento").mkdir(parents=True)
        conn = sqlite3.connect(self.chroma / "chroma.sqlite3")
        conn.execute("CREATE TABLE embeddings (id TEXT)")
        conn.execute("INSERT INTO embeddings VALUES ('mem_1')")
        conn.commit()
        conn.close()
        (self.chroma / "segmento" / "data_level0.bin").write_bytes(b"\x00\x01")

        self.dia = date(2026, 11, 22)
        self.backups = self.raiz / "backups"

    def servico(self, **kwargs):
        return BackupService(self.db, self.chroma, self.backups, hoje=lambda: self.dia, **kwargs)


class TestCopia(BaseBackup):
    def test_copia_do_dia_tem_banco_chroma_e_manifesto(self):
        pasta = self.servico().fazer_backup_se_necessario()
        self.assertEqual(pasta, self.backups / "auto" / "2026-11-22")

        manifesto = json.loads((pasta / ARQUIVO_MANIFESTO).read_text(encoding="utf-8"))
        self.assertEqual(manifesto["banco"]["integridade"], "ok")
        self.assertEqual(len(manifesto["banco"]["sha256"]), 64)
        self.assertEqual(manifesto["chroma"]["arquivos"], 2)

        conn = sqlite3.connect(pasta / "casa.db")
        self.assertEqual(conn.execute("SELECT nome FROM compras").fetchall(), [("café",)])
        conn.close()

        with zipfile.ZipFile(pasta / ARQUIVO_CHROMA) as zipado:
            self.assertEqual(sorted(zipado.namelist()), ["chroma.sqlite3", "segmento/data_level0.bin"])
            zipado.extract("chroma.sqlite3", self.raiz / "extraido")
        conn = sqlite3.connect(self.raiz / "extraido" / "chroma.sqlite3")
        self.assertEqual(conn.execute("SELECT id FROM embeddings").fetchall(), [("mem_1",)])
        conn.close()

    def test_segunda_chamada_no_mesmo_dia_nao_refaz(self):
        servico = self.servico()
        self.assertIsNotNone(servico.fazer_backup_se_necessario())
        self.assertIsNone(servico.fazer_backup_se_necessario())

    def test_forcar_substitui_a_copia_de_hoje(self):
        servico = self.servico()
        servico.fazer_backup()
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO compras (nome) VALUES ('leite')")
        conn.commit()
        conn.close()
        pasta = servico.fazer_backup(forcar=True)
        conn = sqlite3.connect(pasta / "casa.db")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM compras").fetchone()[0], 2)
        conn.close()

    def test_sem_chroma_a_copia_do_banco_continua(self):
        servico = BackupService(self.db, self.raiz / "nao_existe", self.backups, hoje=lambda: self.dia)
        manifesto = json.loads((servico.fazer_backup() / ARQUIVO_MANIFESTO).read_text(encoding="utf-8"))
        self.assertIsNone(manifesto["chroma"])

    def test_banco_ausente_e_recusado_sem_criar_arquivo(self):
        ausente = self.raiz / "ausente.db"
        with self.assertRaises(BackupError):
            BackupService(ausente, self.chroma, self.backups, hoje=lambda: self.dia).fazer_backup()
        self.assertFalse(ausente.exists())
        self.assertEqual(BackupService(ausente, None, self.backups).listar(), [])

    def test_falha_no_meio_nao_deixa_copia_pela_metade(self):
        servico = self.servico()
        with mock.patch.object(servico, "_copiar_chroma", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                servico.fazer_backup()
        self.assertEqual(list((self.backups / "auto").iterdir()), [])

    def test_parcial_de_execucao_interrompida_e_limpa(self):
        restos = self.backups / "auto" / "2026-11-21.parcial"
        restos.mkdir(parents=True)
        self.servico().fazer_backup()
        self.assertFalse(restos.exists())

    def test_copia_manual_fora_da_pasta_auto_nao_e_tocada(self):
        manual = self.backups / "assistente_casa_pre_fase1.db"
        self.backups.mkdir()
        manual.write_bytes(b"x")
        servico = self.servico(diarios=1, semanais=0)
        for deslocamento in range(5):
            self.dia = date(2026, 11, 22) + timedelta(days=deslocamento)
            servico.fazer_backup()
        self.assertTrue(manual.exists())


class TestRetencao(BaseBackup):
    def criar_copias(self, dias):
        for dia in dias:
            pasta = self.backups / "auto" / dia.isoformat()
            pasta.mkdir(parents=True)
            (pasta / ARQUIVO_MANIFESTO).write_text("{}", encoding="utf-8")

    def test_sete_diarias_e_quatro_semanais(self):
        hoje = date(2026, 11, 22)  # domingo
        self.criar_copias(hoje - timedelta(days=n) for n in range(60))
        removidos = self.servico().aplicar_retencao()
        restantes = self.servico().listar()

        self.assertEqual(restantes[:7], [hoje - timedelta(days=n) for n in range(7)])
        semanais = restantes[7:]
        self.assertEqual(len(semanais), 4)
        # Uma por semana, sempre a mais nova da semana, em semanas diferentes
        self.assertEqual(len({d.isocalendar()[:2] for d in semanais}), 4)
        self.assertEqual(semanais[0], date(2026, 11, 15))
        self.assertEqual(len(removidos), 60 - 11)

    def test_pasta_sem_manifesto_e_ignorada(self):
        self.criar_copias([date(2026, 1, 1)])
        (self.backups / "auto" / "2026-01-02").mkdir()
        self.assertEqual(self.servico().listar(), [date(2026, 1, 1)])

    def test_execucao_periodica_grava_e_para(self):
        gravadas = []
        parar = {"valor": False}

        def ao_gravar(pasta):
            gravadas.append(pasta)
            parar["valor"] = True

        thread = self.servico().iniciar_em_segundo_plano(lambda: parar["valor"], ao_gravar=ao_gravar, intervalo_s=1)
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(gravadas), 1)


class TestConexoesFechadas(BaseTemporaria):
    """P22: `with get_connection()` confirma e também fecha a conexão."""

    def test_conexao_fecha_ao_sair_do_with(self):
        with mock.patch.object(modulo_db, "DB_PATH", self.raiz / "p22.db"):
            db = DatabaseService()
        with db.get_connection() as conn:
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
        self.assertEqual(db.executar_consulta("SELECT x FROM t"), [(1,)])

    def test_sem_resource_warning(self):
        with mock.patch.object(modulo_db, "DB_PATH", self.raiz / "p22.db"):
            with warnings.catch_warnings(record=True) as avisos:
                warnings.simplefilter("always", ResourceWarning)
                db = DatabaseService()
                db.executar_consulta("SELECT 1")
                import gc
                gc.collect()
        self.assertEqual([a for a in avisos if issubclass(a.category, ResourceWarning)], [])

    def test_erro_desfaz_e_fecha(self):
        with mock.patch.object(modulo_db, "DB_PATH", self.raiz / "p22.db"):
            db = DatabaseService()
        db.executar_comando("CREATE TABLE t (x INTEGER)")
        with self.assertRaises(ValueError):
            with db.get_connection() as conn:
                conn.execute("INSERT INTO t VALUES (1)")
                raise ValueError("falha no meio")
        self.assertEqual(db.executar_consulta("SELECT x FROM t"), [])


class ColecaoFalsa:
    def __init__(self, ids, documentos, metadados):
        self.dados = {"ids": ids, "documents": documentos, "metadatas": metadados}

    def get(self, include=None):
        return self.dados


class ClienteFalso:
    def __init__(self, colecao=None):
        self.colecao = colecao
        self.apagadas = []

    def list_collections(self):
        return [rebuild_embeddings.DEFAULT_COLLECTION] if self.colecao else []

    def get_collection(self, nome):
        return self.colecao

    def delete_collection(self, nome):
        self.apagadas.append(nome)
        self.colecao = None


class VetorFalso:
    def __init__(self, client, upsert_ok=True):
        self.client = client
        self.upsert_ok = upsert_ok
        self.gravados = []

    def upsert_documents(self, documentos):
        self.gravados.extend(documentos)
        return self.upsert_ok


class TestReconstrucaoPreservaMemorias(BaseTemporaria):
    """P13: rebuild_embeddings apagava a coleção e perdia as memórias mem_*."""

    def vetor(self, upsert_ok=True):
        colecao = ColecaoFalsa(
            ids=["mem_a1", "compra_1", "mem_b2"],
            documentos=["prefiro café Pilão", "Compra no Moreschi", "namorada mora em Bauru"],
            metadados=[{"assistant": "geral"}, {"entity_type": "compra"}, None],
        )
        return VetorFalso(ClienteFalso(colecao), upsert_ok)

    def test_memorias_sao_exportadas_e_regravadas(self):
        vetor = self.vetor()
        ordem = []
        total = rebuild_embeddings.reconstruir_embeddings(
            vector_store=vetor, migrar=lambda: ordem.append("migrar"), backup=False, pasta_exportacao=self.raiz,
        )
        self.assertEqual(total, 2)
        self.assertEqual(vetor.client.apagadas, [rebuild_embeddings.DEFAULT_COLLECTION])
        self.assertEqual(ordem, ["migrar"])
        self.assertEqual([d.id for d in vetor.gravados], ["mem_a1", "mem_b2"])
        # Sem vetor antigo: recalculado com o modelo atual
        self.assertTrue(all(d.embedding is None for d in vetor.gravados))

        [exportacao] = list(self.raiz.glob("memorias-*.json"))
        conteudo = json.loads(exportacao.read_text(encoding="utf-8"))
        self.assertEqual([m["content"] for m in conteudo], ["prefiro café Pilão", "namorada mora em Bauru"])

    def test_falha_ao_regravar_avisa_e_mantem_exportacao(self):
        with self.assertRaises(RuntimeError):
            rebuild_embeddings.reconstruir_embeddings(
                vector_store=self.vetor(upsert_ok=False), migrar=lambda: None, backup=False, pasta_exportacao=self.raiz,
            )
        self.assertEqual(len(list(self.raiz.glob("memorias-*.json"))), 1)

    def test_erro_ao_ler_memorias_nao_apaga_nada(self):
        vetor = self.vetor()
        vetor.client.get_collection = mock.Mock(side_effect=RuntimeError("chroma travado"))
        with self.assertRaises(rebuild_embeddings.ReconstrucaoAbortada):
            rebuild_embeddings.reconstruir_embeddings(vector_store=vetor, migrar=lambda: None, backup=False)
        self.assertEqual(vetor.client.apagadas, [])

    def test_backup_e_feito_antes_de_apagar(self):
        backup = mock.Mock()
        vetor = self.vetor()
        backup.fazer_backup.side_effect = lambda forcar: self.assertEqual(vetor.client.apagadas, []) or self.raiz
        rebuild_embeddings.reconstruir_embeddings(
            vector_store=vetor, migrar=lambda: None, backup=backup, pasta_exportacao=self.raiz,
        )
        backup.fazer_backup.assert_called_once_with(forcar=True)


if __name__ == "__main__":
    unittest.main()
