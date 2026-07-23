"""Run all schema migrations against a temporary copy of production SQLite."""

import asyncio
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def counts(path):
    connection = sqlite3.connect(path)
    try:
        result = {}
        for table in ("assignments", "payments", "dashboard_invoices", "payout_requests"):
            try:
                result[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                result[table] = 0
        return result
    finally:
        connection.close()


async def main():
    import database
    import operations
    import payment_service
    from dashboard.backend import app

    source = Path(database.DB_PATH)
    before = counts(source)
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / "migration.db"
        shutil.copy2(source, target)
        database.DB_PATH = str(target)
        operations.DB_PATH = str(target)
        payment_service.DB_PATH = str(target)
        app.DB_PATH = str(target)
        await database.setup_database()
        await app.setup_dashboard_tables()
        await payment_service.setup_payment_tables()
        await operations.setup_operations()
        connection = sqlite3.connect(target)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
        after = counts(target)
        if integrity != "ok" or before != after:
            raise SystemExit(f"Migration gagal: integrity={integrity}, before={before}, after={after}")
        print(f"Migration copy OK: integrity={integrity}, counts={after}")


if __name__ == "__main__":
    asyncio.run(main())
