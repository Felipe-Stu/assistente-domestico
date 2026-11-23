"""
Cópia de segurança automática do SQLite e do ChromaDB (M11).

Uma cópia por dia em <BACKUP_DIR>/auto/AAAA-MM-DD/:
- assistente_casa.db  -> feito com VACUUM INTO (cópia consistente mesmo com o app aberto)
- chroma_db.zip       -> pasta do ChromaDB; o chroma.sqlite3 é copiado pela API de backup do SQLite
- manifesto.json      -> data, tamanhos, SHA-256 e resultado do PRAGMA integrity_check

A cópia é montada em AAAA-MM-DD.parcial e só recebe o nome final quando termina:
uma pasta com o nome do dia está sempre completa.

Retenção: as `diarios` cópias mais recentes, mais a mais nova de cada uma das
`semanais` semanas anteriores. Só a pasta auto/ é limpa; cópias manuais ficam intactas.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Callable, List, Optional

from services.logger_service import logger as custom_logger

COMPONENTE = "backup"
PASTA_AUTO = "auto"
SUFIXO_PARCIAL = ".parcial"
ARQUIVO_MANIFESTO = "manifesto.json"
ARQUIVO_CHROMA = "chroma_db.zip"
VERSAO_MANIFESTO = 1


class BackupError(Exception):
    """A cópia não pôde ser feita ou não passou na verificação."""


def _sha256(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def _copiar_sqlite(origem: Path, destino: Path):
    """Cópia consistente de um banco SQLite em uso (API de backup)."""
    fonte = sqlite3.connect(origem)
    try:
        alvo = sqlite3.connect(destino)
        try:
            fonte.backup(alvo)
        finally:
            alvo.close()
    finally:
        fonte.close()


class BackupService:
    def __init__(
        self,
        db_path,
        chroma_dir,
        pasta_backups,
        diarios: int = 7,
        semanais: int = 4,
        hoje: Callable[[], date] = date.today,
    ):
        self.db_path = Path(db_path)
        self.chroma_dir = Path(chroma_dir) if chroma_dir else None
        self.pasta_auto = Path(pasta_backups) / PASTA_AUTO
        self.diarios = max(1, diarios)
        self.semanais = max(0, semanais)
        self._hoje = hoje

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def listar(self) -> List[date]:
        """Dias com cópia completa (pasta com manifesto), do mais recente para o mais antigo."""
        if not self.pasta_auto.exists():
            return []
        dias = []
        for pasta in self.pasta_auto.iterdir():
            if not pasta.is_dir() or not (pasta / ARQUIVO_MANIFESTO).exists():
                continue
            try:
                dias.append(date.fromisoformat(pasta.name))
            except ValueError:
                continue
        return sorted(dias, reverse=True)

    def pasta_do_dia(self, dia: date) -> Path:
        return self.pasta_auto / dia.isoformat()

    # ------------------------------------------------------------------
    # Cópia
    # ------------------------------------------------------------------

    def fazer_backup_se_necessario(self) -> Optional[Path]:
        """Faz a cópia do dia se ainda não existir. Retorna a pasta criada ou None."""
        if self._hoje() in self.listar():
            return None
        return self.fazer_backup()

    def fazer_backup(self, forcar: bool = False) -> Path:
        """Cria a cópia do dia (com `forcar`, substitui a cópia de hoje). Aplica a retenção ao final."""
        dia = self._hoje()
        destino = self.pasta_do_dia(dia)
        if destino.exists() and not forcar:
            return destino
        if not self.db_path.exists():
            # sqlite3.connect criaria um banco vazio: melhor recusar
            raise BackupError(f"Banco de dados não encontrado: {self.db_path}")

        inicio = time.perf_counter()
        self.pasta_auto.mkdir(parents=True, exist_ok=True)
        self._remover_parciais()
        parcial = self.pasta_auto / f"{dia.isoformat()}{SUFIXO_PARCIAL}"
        parcial.mkdir()

        try:
            manifesto = {
                "versao": VERSAO_MANIFESTO,
                "criado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
                "banco": self._copiar_banco(parcial),
                "chroma": self._copiar_chroma(parcial),
            }
            with open(parcial / ARQUIVO_MANIFESTO, "w", encoding="utf-8") as arquivo:
                json.dump(manifesto, arquivo, ensure_ascii=False, indent=2)

            if destino.exists():
                shutil.rmtree(destino)
            os.replace(parcial, destino)
        except Exception:
            shutil.rmtree(parcial, ignore_errors=True)
            raise

        removidos = self.aplicar_retencao()
        custom_logger.evento(
            COMPONENTE, "backup_gravado",
            pasta=str(destino),
            bytes_banco=manifesto["banco"]["bytes"],
            bytes_chroma=(manifesto["chroma"] or {}).get("bytes", 0),
            removidos=[d.isoformat() for d in removidos],
            duracao_ms=int((time.perf_counter() - inicio) * 1000),
        )
        return destino

    def _copiar_banco(self, pasta: Path) -> dict:
        copia = pasta / self.db_path.name
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("VACUUM INTO ?", (str(copia),))
        finally:
            conn.close()

        conn = sqlite3.connect(copia)
        try:
            integridade = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if integridade != "ok":
            raise BackupError(f"A cópia do banco não passou no integrity_check: {integridade}")

        return {"arquivo": copia.name, "bytes": copia.stat().st_size, "sha256": _sha256(copia), "integridade": integridade}

    def _copiar_chroma(self, pasta: Path) -> Optional[dict]:
        if not self.chroma_dir or not self.chroma_dir.exists() or not any(self.chroma_dir.iterdir()):
            return None
        destino = pasta / ARQUIVO_CHROMA
        total = 0
        with tempfile.TemporaryDirectory() as temporaria, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zipado:
            for arquivo in sorted(self.chroma_dir.rglob("*")):
                if not arquivo.is_file():
                    continue
                relativo = arquivo.relative_to(self.chroma_dir).as_posix()
                if arquivo.suffix in (".sqlite3", ".db"):
                    copia = Path(temporaria) / f"{total}{arquivo.suffix}"
                    _copiar_sqlite(arquivo, copia)
                    zipado.write(copia, relativo)
                elif arquivo.name.endswith(("-wal", "-shm", "-journal")):
                    continue  # Já incorporados pela cópia do SQLite acima
                else:
                    zipado.write(arquivo, relativo)
                total += 1
        return {"arquivo": destino.name, "bytes": destino.stat().st_size, "sha256": _sha256(destino), "arquivos": total}

    # ------------------------------------------------------------------
    # Retenção
    # ------------------------------------------------------------------

    def aplicar_retencao(self) -> List[date]:
        """Apaga as cópias automáticas fora da retenção. Retorna os dias removidos."""
        dias = self.listar()
        manter = set(dias[: self.diarios])
        semanas = []
        for dia in dias[self.diarios:]:
            semana = dia.isocalendar()[:2]
            if semana in semanas:
                continue
            if len(semanas) >= self.semanais:
                break
            semanas.append(semana)
            manter.add(dia)  # dias está em ordem decrescente: é a cópia mais nova da semana

        removidos = []
        for dia in dias:
            if dia not in manter:
                shutil.rmtree(self.pasta_do_dia(dia), ignore_errors=True)
                removidos.append(dia)
        return removidos

    def _remover_parciais(self):
        """Restos de uma cópia interrompida (ex.: app fechado no meio)."""
        for pasta in self.pasta_auto.glob(f"*{SUFIXO_PARCIAL}"):
            shutil.rmtree(pasta, ignore_errors=True)

    # ------------------------------------------------------------------
    # Execução periódica
    # ------------------------------------------------------------------

    def iniciar_em_segundo_plano(
        self,
        deve_parar: Callable[[], bool],
        ao_gravar: Optional[Callable[[Path], None]] = None,
        ao_falhar: Optional[Callable[[Exception], None]] = None,
        intervalo_s: int = 3600,
    ) -> threading.Thread:
        """Confere a cada `intervalo_s` se a cópia do dia existe (o app pode ficar aberto de um dia para o outro)."""

        def _laco():
            while not deve_parar():
                try:
                    pasta = self.fazer_backup_se_necessario()
                    if pasta and ao_gravar:
                        ao_gravar(pasta)
                except Exception as erro:
                    custom_logger.evento(COMPONENTE, "backup_falhou", str(erro), nivel="ERROR", erro_tipo=type(erro).__name__)
                    if ao_falhar:
                        ao_falhar(erro)
                for _ in range(intervalo_s):
                    if deve_parar():
                        return
                    time.sleep(1)

        thread = threading.Thread(target=_laco, name="backup-diario", daemon=True)
        thread.start()
        return thread
