import asyncio
import os
import tempfile
import unittest

import database


class DatabaseConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_reads_and_writes_use_wal_and_busy_timeout(self):
        original_path = database.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                database.DB_PATH = os.path.join(temporary_directory, "concurrency.db")
                await database.setup_database()
                self.assertEqual(await database.get_role_payrate("TL"), 3000)
                await database.set_role_payrate("TL", 7500)
                self.assertEqual(await database.get_role_payrate("TL"), 7500)

                await asyncio.gather(
                    *(
                        database.create_assignment(
                            f"Manga {index}", str(index), "TL", 3000, 3000, 1.0
                        )
                        for index in range(30)
                    )
                )
                rows = await database.get_assignments_by_status("open")
                stats = await asyncio.gather(
                    *(database.get_staff_stats(index, "2026-07") for index in range(20))
                )

                connection = await database.get_db()
                try:
                    journal_cursor = await connection.execute("PRAGMA journal_mode")
                    timeout_cursor = await connection.execute("PRAGMA busy_timeout")
                    journal_mode = (await journal_cursor.fetchone())[0]
                    busy_timeout = (await timeout_cursor.fetchone())[0]
                finally:
                    await connection.close()

                self.assertEqual(len(rows), 30)
                self.assertEqual(len(stats), 20)
                self.assertEqual(journal_mode, "wal")
                self.assertEqual(busy_timeout, 30000)
        finally:
            database.DB_PATH = original_path


if __name__ == "__main__":
    unittest.main()
