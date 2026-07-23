"""Safely restore a verified local .db or .db.gz backup.

Usage:
  python dashboard/deploy/restore_database.py data/backups/file.db.gz
"""

import argparse
import gzip
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "data" / "ryukomik.db"
PRE_RESTORE = ROOT / "data" / "backups"


def integrity(path):
    connection = sqlite3.connect(path)
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    source = args.backup.resolve()
    if not source.is_file():
        raise SystemExit("Backup tidak ditemukan.")
    PRE_RESTORE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp:
        candidate = Path(temp) / "candidate.db"
        if source.suffix == ".gz":
            with gzip.open(source, "rb") as src, candidate.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            shutil.copy2(source, candidate)
        result = integrity(candidate)
        if result != "ok":
            raise SystemExit(f"Backup rusak: {result}")
        print(f"Backup: {source}")
        print(f"Ukuran: {candidate.stat().st_size} bytes")
        print("Integrity: ok")
        if not args.yes and input("Ketik RESTORE untuk melanjutkan: ").strip() != "RESTORE":
            raise SystemExit("Restore dibatalkan.")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety = PRE_RESTORE / f"pre-restore-{timestamp}.db"
        if DATABASE.exists():
            current = sqlite3.connect(DATABASE)
            backup = sqlite3.connect(safety)
            try:
                current.backup(backup)
            finally:
                backup.close()
                current.close()
        subprocess.run(["pm2", "stop", "ryukomik-bot", "ryukomik-dashboard-api"], check=True)
        try:
            replacement = DATABASE.with_suffix(".restore")
            shutil.copy2(candidate, replacement)
            replacement.replace(DATABASE)
        finally:
            subprocess.run(["pm2", "restart", "ryukomik-dashboard-api", "ryukomik-bot"], check=True)
        print(f"Restore selesai. Safety backup: {safety}")


if __name__ == "__main__":
    main()
