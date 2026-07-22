"""Create a consistent SQLite backup and prune backups older than retention."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.getenv("RYUKOMIK_DB_PATH", ROOT / "data" / "ryukomik.db"))
BACKUP_DIR = Path(os.getenv("RYUKOMIK_BACKUP_DIR", ROOT / "data" / "backups"))
RETENTION_DAYS = int(os.getenv("RYUKOMIK_BACKUP_RETENTION_DAYS", "14"))


def main():
    if not SOURCE.is_file():
        raise SystemExit(f"Database tidak ditemukan: {SOURCE}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    target = BACKUP_DIR / f"ryukomik-{now.strftime('%Y%m%d-%H%M%S')}.db"
    with sqlite3.connect(SOURCE) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            target.unlink(missing_ok=True)
            raise SystemExit(f"Backup gagal integrity check: {result}")
    cutoff = now - timedelta(days=RETENTION_DAYS)
    for candidate in BACKUP_DIR.glob("ryukomik-*.db"):
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            candidate.unlink()
    print(target)


if __name__ == "__main__":
    main()
