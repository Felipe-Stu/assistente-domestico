"""
Cópia de segurança manual (M11). O app já faz uma por dia sozinho.

    python scripts/fazer_backup.py            # faz a cópia de hoje, se ainda não existir
    python scripts/fazer_backup.py --forcar   # refaz a cópia de hoje
    python scripts/fazer_backup.py --listar   # mostra as cópias guardadas
"""
import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from core.config import BACKUP_DIARIOS, BACKUP_DIR, BACKUP_SEMANAIS, CHROMA_DIR, DB_PATH  # noqa: E402
from services.backup_service import ARQUIVO_MANIFESTO, BackupService  # noqa: E402


def criar_servico() -> BackupService:
    return BackupService(DB_PATH, CHROMA_DIR, BACKUP_DIR, diarios=BACKUP_DIARIOS, semanais=BACKUP_SEMANAIS)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cópia de segurança do SQLite e do ChromaDB.")
    parser.add_argument("--forcar", action="store_true", help="refaz a cópia de hoje")
    parser.add_argument("--listar", action="store_true", help="lista as cópias automáticas")
    args = parser.parse_args(argv)

    servico = criar_servico()
    if args.listar:
        dias = servico.listar()
        if not dias:
            print("Nenhuma cópia automática encontrada.")
        for dia in dias:
            manifesto = json.loads((servico.pasta_do_dia(dia) / ARQUIVO_MANIFESTO).read_text(encoding="utf-8"))
            chroma = manifesto.get("chroma") or {}
            print(f"{dia}  banco {manifesto['banco']['bytes']:>9} B ({manifesto['banco']['integridade']})  "
                  f"chroma {chroma.get('bytes', 0):>9} B  {servico.pasta_do_dia(dia)}")
        return 0

    pasta = servico.fazer_backup(forcar=True) if args.forcar else servico.fazer_backup_se_necessario()
    print(f"Cópia gravada em {pasta}" if pasta else "A cópia de hoje já existe (use --forcar para refazer).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
