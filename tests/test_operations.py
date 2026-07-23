import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import operations


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = operations.DB_PATH
        self.original_backup = operations.BACKUP_DIR
        operations.DB_PATH = os.path.join(self.temp.name, "ops.db")
        operations.BACKUP_DIR = Path(self.temp.name) / "backups"
        connection = sqlite3.connect(operations.DB_PATH)
        connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY,value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES('ok')")
        connection.commit()
        connection.close()
        asyncio.run(operations.setup_operations())

    def tearDown(self):
        operations.DB_PATH = self.original_db
        operations.BACKUP_DIR = self.original_backup
        self.temp.cleanup()

    def test_events_are_fingerprinted_and_resolved(self):
        asyncio.run(operations.record_event("discord", "warning", "timeout", {"channel": 1}))
        asyncio.run(operations.record_event("discord", "warning", "timeout", {"channel": 1}))
        snapshot = asyncio.run(operations.operations_snapshot())
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertEqual(snapshot["events"][0]["occurrence_count"], 2)
        self.assertTrue(asyncio.run(operations.resolve_event(snapshot["events"][0]["id"], 99)))
        self.assertEqual(asyncio.run(operations.operations_snapshot())["events"], [])

    def test_outbox_is_deduplicated_and_retried(self):
        self.assertTrue(asyncio.run(operations.enqueue_notification("same", "test", 1, {"content": "x"})))
        self.assertFalse(asyncio.run(operations.enqueue_notification("same", "test", 1, {"content": "x"})))
        due = asyncio.run(operations.due_notifications())
        self.assertEqual(len(due), 1)
        asyncio.run(operations.finish_notification(due[0]["id"], "temporary"))
        snapshot = asyncio.run(operations.operations_snapshot())
        self.assertEqual(snapshot["outbox"][0]["status"], "retry")

    def test_verified_backup_has_integrity_and_checksum(self):
        result = asyncio.run(operations.create_verified_backup())
        self.assertTrue(Path(result["path"]).exists())
        self.assertEqual(len(result["sha256"]), 64)
        snapshot = asyncio.run(operations.operations_snapshot())
        self.assertEqual(snapshot["backups"][0]["integrity_status"], "ok")


if __name__ == "__main__":
    unittest.main()
