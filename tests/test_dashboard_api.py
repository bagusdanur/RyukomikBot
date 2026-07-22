import asyncio
import importlib
import os
import sqlite3
import tempfile
import unittest


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        os.environ["DASHBOARD_DEV_BYPASS"] = "true"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "dashboard-test.db")
        connection = sqlite3.connect(self.db_path)
        connection.executescript("""
            CREATE TABLE assignments (
                id INTEGER PRIMARY KEY, manga TEXT, chapter TEXT, staff_id INTEGER,
                role TEXT, base_rate INTEGER, final_rate INTEGER, multiplier REAL,
                status TEXT, deadline_at TEXT, assigned_at TEXT, approved_at TEXT,
                paid_period TEXT
            );
            CREATE TABLE payrates (
                role TEXT PRIMARY KEY, base_rate INTEGER, updated_at TEXT
            );
            INSERT INTO assignments VALUES
                (1,'Project A','1',100,'TL',3000,5000,1,'claimed','2026-07-23','2026-07-20',NULL,NULL),
                (2,'Project B','2',200,'TS',3000,8000,1,'submitted','2026-07-24','2026-07-20',NULL,NULL),
                (3,'Project C','3',100,'TL',3000,6000,1,'paid',NULL,'2026-07-01','2026-07-02','2026-07');
            INSERT INTO payrates VALUES ('TL',3000,CURRENT_TIMESTAMP),('TS',3000,CURRENT_TIMESTAMP),('TL+TS',5000,CURRENT_TIMESTAMP);
        """)
        connection.commit()
        connection.close()

        self.module = importlib.import_module("dashboard.backend.app")
        self.module.DB_PATH = self.db_path
        asyncio.run(self.module.setup_dashboard_tables())

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_admin_overview_and_assignments(self):
        user = {"id": 1, "username": "Admin", "role": "admin"}
        overview = asyncio.run(self.module.overview(user))
        assignments = asyncio.run(self.module.assignments(user=user))
        self.assertEqual(overview["counts"]["claimed"], 1)
        self.assertEqual(overview["total_value"], 19000)
        self.assertEqual(len(assignments), 3)

    def test_staff_can_only_see_own_assignments(self):
        user = {"id": 100, "username": "Staff", "role": "staff"}
        assignments = asyncio.run(self.module.assignments(user=user))
        self.assertEqual({item["staff_id"] for item in assignments}, {100})
        self.assertEqual(len(assignments), 2)

    def test_payrate_update_creates_audit_log(self):
        user = {"id": 1, "username": "Admin", "role": "admin"}
        payload = self.module.PayrateUpdate(base_rate=4500)
        result = asyncio.run(self.module.update_payrate("TL", payload, user))
        logs = asyncio.run(self.module.audit_logs(user))
        self.assertEqual(result["base_rate"], 4500)
        self.assertEqual(logs[0]["action"], "payrate.update")


if __name__ == "__main__":
    unittest.main()
