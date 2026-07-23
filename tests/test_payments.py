import asyncio
import os
import sqlite3
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from cryptography.fernet import Fernet

import database
import payment_service as payments


class PaymentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "payments.db")
        self.key = Fernet.generate_key().decode()
        self.patches = [
            patch.object(database, "DB_PATH", self.path),
            patch.object(payments, "DB_PATH", self.path),
            patch.object(payments, "PAYMENT_DATA_ENCRYPTION_KEY", self.key),
        ]
        for item in self.patches:
            item.start()
        asyncio.run(database.setup_database())
        asyncio.run(payments.setup_payment_tables())

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def add_approved(self, staff_id=100, approved_at="2026-07-10", amount=12000, chapters=1):
        connection = sqlite3.connect(self.path)
        connection.execute("""INSERT INTO assignments
            (manga,chapter,staff_id,role,base_rate,final_rate,multiplier,status,approved_at,chapter_count,rate_per_chapter,chapters)
            VALUES('Project','1',?,'TS',?,?,1,'approved',?,?,?,'["1"]')""",
            (staff_id, amount, amount, approved_at, chapters, amount // chapters))
        connection.commit()
        connection.close()

    def test_method_is_encrypted_and_masked(self):
        method_id = asyncio.run(payments.create_method(100, "bank", "BCA", "Staff", "1234567890"))
        connection = sqlite3.connect(self.path)
        stored = connection.execute(
            "SELECT account_encrypted FROM staff_payment_methods WHERE id=?", (method_id,)
        ).fetchone()[0]
        connection.close()
        self.assertNotIn("1234567890", stored)
        method = asyncio.run(payments.list_methods(100, include_sensitive=True))[0]
        self.assertEqual(method["account_number"], "1234567890")
        self.assertEqual(method["masked_account"], "****7890")
        self.assertEqual(method["is_default"], 1)

    def test_instant_payout_snapshot_and_payment(self):
        self.add_approved(chapters=2, amount=24000)
        method_id = asyncio.run(payments.create_method(100, "ewallet", "DANA", "Staff", "081234567890"))
        payout = asyncio.run(payments.create_payout(100, method_id))
        self.assertEqual(payout["total_amount"], 24000)
        self.assertEqual(payout["chapter_count"], 2)
        with self.assertRaises(ValueError):
            asyncio.run(payments.create_payout(100, method_id))
        asyncio.run(payments.pay_payout(payout["id"], 999))
        connection = sqlite3.connect(self.path)
        assignment_status = connection.execute("SELECT status FROM assignments").fetchone()[0]
        payout_status = connection.execute("SELECT status FROM payout_requests").fetchone()[0]
        connection.close()
        self.assertEqual((assignment_status, payout_status), ("paid", "paid"))

    def test_rejection_releases_assignment(self):
        self.add_approved()
        method_id = asyncio.run(payments.create_method(100, "bank", "BRI", "Staff", "12345678"))
        payout = asyncio.run(payments.create_payout(100, method_id))
        asyncio.run(payments.reject_payout(payout["id"], 999, "Data rekening salah"))
        replacement = asyncio.run(payments.create_payout(100, method_id))
        self.assertNotEqual(payout["invoice_id"], replacement["invoice_id"])

    def test_schedule_cutoffs(self):
        cycles = payments.scheduled_cycles(date(2026, 7, 19))
        self.assertIn(("2026-07-19", date(2026, 7, 1), date(2026, 7, 15)), cycles)
        cycles = payments.scheduled_cycles(date(2026, 8, 4))
        self.assertIn(("2026-08-04", date(2026, 7, 16), date(2026, 7, 31)), cycles)


if __name__ == "__main__":
    unittest.main()
