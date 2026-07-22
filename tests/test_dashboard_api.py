import asyncio
import importlib
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


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
                paid_period TEXT, message_id INTEGER, ticket_channel_id INTEGER,
                claimed_at TEXT, submitted_at TEXT, gdrive_link TEXT, admin_notes TEXT
            );
            CREATE TABLE payments (
                id INTEGER PRIMARY KEY, staff_id INTEGER, period TEXT, total_amount INTEGER,
                chapter_count INTEGER, status TEXT, paid_at TEXT
            );
            CREATE TABLE payrates (
                role TEXT PRIMARY KEY, base_rate INTEGER, updated_at TEXT
            );
            INSERT INTO assignments VALUES
                (1,'Project A','1',100,'TL',3000,5000,1,'claimed','2026-07-23','2026-07-20',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL),
                (2,'Project B','2',200,'TS',3000,8000,1,'submitted','2026-07-24','2026-07-20',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL),
                (3,'Project C','3',100,'TL',3000,6000,1,'paid',NULL,'2026-07-01','2026-07-02','2026-07',NULL,NULL,NULL,NULL,NULL,NULL),
                (4,'Project D','4',100,'TL',3000,7000,1,'approved',NULL,'2026-07-03','2026-07-04',NULL,NULL,NULL,NULL,NULL,NULL,NULL);
            INSERT INTO payrates VALUES ('TL',3000,CURRENT_TIMESTAMP),('TS',3000,CURRENT_TIMESTAMP),('TL+TS',5000,CURRENT_TIMESTAMP);
        """)
        connection.commit()
        connection.close()

        self.module = importlib.import_module("dashboard.backend.app")
        self.module.DB_PATH = self.db_path
        self.module.staff_db.DB_PATH = self.db_path
        asyncio.run(self.module.setup_dashboard_tables())

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_admin_overview_and_assignments(self):
        user = {"id": 1, "username": "Admin", "role": "admin"}
        overview = asyncio.run(self.module.overview(user))
        assignments = asyncio.run(self.module.assignments(status=None, search=None, user=user))
        self.assertEqual(overview["counts"]["claimed"], 1)
        self.assertEqual(overview["total_value"], 26000)
        self.assertEqual(len(assignments), 4)

    def test_staff_can_only_see_own_assignments(self):
        user = {"id": 100, "username": "Staff", "role": "staff"}
        assignments = asyncio.run(self.module.assignments(status=None, search=None, user=user))
        self.assertEqual({item["staff_id"] for item in assignments}, {"100"})
        self.assertEqual(len(assignments), 3)

    def test_payrate_update_creates_audit_log(self):
        user = {"id": 1, "username": "Admin", "role": "admin"}
        payload = self.module.PayrateUpdate(base_rate=4500)
        result = asyncio.run(self.module.update_payrate("TL", payload, user))
        logs = asyncio.run(self.module.audit_logs(user))
        self.assertEqual(result["base_rate"], 4500)
        self.assertEqual(logs[0]["action"], "payrate.update")

    def test_admin_can_create_direct_assignment(self):
        user = {"id": 1, "username": "Admin", "role": "admin"}
        payload = self.module.AssignmentCreate(
            manga="Project Baru", chapter="5", staff_id=100, role="TL",
            final_rate=5000, deadline_at="2026-07-30",
        )
        result = asyncio.run(self.module.create_dashboard_assignment(payload, user))
        assignment = asyncio.run(self.module.assignments(status="claimed", search="Project Baru", user=user))[0]
        self.assertEqual(result["id"], assignment["id"])
        self.assertEqual(assignment["staff_id"], "100")

    def test_invoice_creation_and_payment(self):
        user = {"id": 1, "username": "Admin", "role": "admin"}
        created = asyncio.run(self.module.create_invoice(self.module.InvoiceCreate(staff_id=100, period="2026-07"), user))
        invoice_rows = asyncio.run(self.module.invoices(period="2026-07", _user=user))
        self.assertEqual(invoice_rows[0]["total_amount"], 7000)
        detail = asyncio.run(self.module.invoice_detail(created["id"], user))
        self.assertEqual(detail["work_started_at"], "2026-07-03")
        self.assertEqual(detail["work_ended_at"], "2026-07-04")
        self.assertEqual(detail["items"][0]["manga"], "Project D")
        self.assertEqual(detail["items"][0]["amount"], 7000)
        asyncio.run(self.module.pay_invoice(created["id"], user))
        paid_rows = asyncio.run(self.module.invoices(period="2026-07", _user=user))
        self.assertEqual(paid_rows[0]["status"], "paid")

    def test_staff_can_upload_and_submit_result(self):
        class FakeR2:
            def generate_presigned_url(self, *_args, **_kwargs):
                return "https://upload.example/signed"

            def head_object(self, **_kwargs):
                return {"ContentLength": 1234}

        user = {"id": 100, "username": "Staff 100", "role": "staff"}
        payload = self.module.UploadRequest(
            assignment_id=1, filename="hasil-chapter.zip",
            content_type="application/zip", size_bytes=1234,
        )
        with patch.object(self.module, "r2_client", return_value=FakeR2()):
            signed = asyncio.run(self.module.presign_upload(payload, user))
            result = asyncio.run(self.module.complete_upload(signed["upload_id"], user))
        self.assertTrue(result["ok"])
        submitted = asyncio.run(self.module.assignments(status="submitted", search="Project A", user=user))
        self.assertEqual(len(submitted), 1)


if __name__ == "__main__":
    unittest.main()
