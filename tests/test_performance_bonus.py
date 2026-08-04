import asyncio
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

import database
import pair_workflow
import payment_service
import performance_bonus


class PerformanceBonusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "bonus.db")
        self.patches = [
            patch.object(database, "DB_PATH", self.path),
            patch.object(performance_bonus, "DB_PATH", self.path),
            patch.object(payment_service, "DB_PATH", self.path),
            patch.object(payment_service, "PAYMENT_DATA_ENCRYPTION_KEY", Fernet.generate_key().decode()),
        ]
        for item in self.patches:
            item.start()
        asyncio.run(database.setup_database())
        asyncio.run(pair_workflow.setup_pair_tables())
        asyncio.run(payment_service.setup_payment_tables())

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def assignment(self, staff=100, chapter="1", amount=10000, deadline="2026-07-20",
                   approved="2026-07-15", chapters=1, role="TS"):
        connection = sqlite3.connect(self.path)
        cursor = connection.execute("""INSERT INTO assignments
            (manga,chapter,staff_id,role,base_rate,final_rate,multiplier,status,deadline_at,
             approved_at,chapter_count,rate_per_chapter,chapters)
            VALUES('Project',?,?,?,?,?,1,'approved',?,?,?,?,?)""",
            (chapter, staff, role, amount, amount, deadline, approved, chapters,
             amount // chapters, f'["{chapter}"]'))
        connection.commit(); connection.close()
        return cursor.lastrowid

    def test_minimum_three_chapters_and_tier(self):
        self.assignment(chapters=2, amount=20000)
        asyncio.run(performance_bonus.evaluate_period("2026-07"))
        result = asyncio.run(performance_bonus.list_bonuses("2026-07"))[0]
        self.assertEqual(result["status"], "ineligible")
        self.assignment(chapter="3")
        asyncio.run(performance_bonus.evaluate_period("2026-07"))
        result = asyncio.run(performance_bonus.list_bonuses("2026-07"))[0]
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["total_score"], 100)
        self.assertEqual(result["proposed_amount"], 3000)

    def test_no_deadline_redistributes_speed_weight(self):
        for chapter in ("1", "2", "3"):
            self.assignment(chapter=chapter, deadline=None)
        asyncio.run(performance_bonus.evaluate_period("2026-07"))
        result = asyncio.run(performance_bonus.list_bonuses("2026-07"))[0]
        self.assertIsNone(result["speed_score"])
        self.assertTrue(result["metrics"]["no_deadline_redistribution"])
        self.assertEqual(result["total_score"], 100)

    def test_revision_reduces_only_targeted_pair_role(self):
        project = asyncio.run(pair_workflow.create_project(
            manga="Pair", chapters=["1", "2", "3"], tl_staff_id=100, ts_staff_id=200,
            tl_rate_per_chapter=4000, ts_rate_per_chapter=5000,
            deadline_at="2026-07-20", created_by=999,
        ))
        connection = sqlite3.connect(self.path)
        for chapter in project["chapters"]:
            connection.execute("UPDATE assignments SET status='approved',approved_at='2026-07-15' WHERE pair_chapter_id=?", (chapter["id"],))
        first = project["chapters"][0]
        connection.execute("INSERT INTO pair_events(project_id,chapter_id,event_type,actor_id,detail) VALUES(?,?,'revision_tl','999','Fix TL')", (project["id"], first["id"]))
        connection.commit(); connection.close()
        asyncio.run(performance_bonus.evaluate_period("2026-07"))
        rows = {item["staff_id"]: item for item in asyncio.run(performance_bonus.list_bonuses("2026-07"))}
        self.assertEqual(rows["100"]["revision_chapters"], 1)
        self.assertEqual(rows["200"]["revision_chapters"], 0)
        self.assertLess(rows["100"]["quality_score"], rows["200"]["quality_score"])

    def test_approved_bonus_is_invoiced_paid_and_idempotent(self):
        for chapter in ("1", "2", "3"):
            self.assignment(chapter=chapter)
        asyncio.run(performance_bonus.evaluate_period("2026-07"))
        bonus = asyncio.run(performance_bonus.list_bonuses("2026-07"))[0]
        asyncio.run(performance_bonus.review_bonus(bonus["id"], "approve", 999))
        method = asyncio.run(payment_service.create_method(100, "bank", "BCA", "Staff", "1234567890"))
        payout = asyncio.run(payment_service.create_payout(100, method))
        self.assertEqual(payout["total_amount"], 33000)
        detail = asyncio.run(payment_service.payout_detail(payout["id"]))
        self.assertEqual(sum(1 for item in detail["items"] if item.get("role") == "BONUS"), 1)
        asyncio.run(payment_service.pay_payout(payout["id"], 999))
        result = asyncio.run(performance_bonus.list_bonuses("2026-07"))[0]
        self.assertEqual(result["status"], "paid")
        asyncio.run(performance_bonus.evaluate_period("2026-07"))
        self.assertEqual(len(asyncio.run(performance_bonus.list_bonuses("2026-07"))), 1)

    def test_cap_and_rejection(self):
        for chapter in ("1", "2", "3"):
            self.assignment(chapter=chapter, amount=200000)
        asyncio.run(performance_bonus.evaluate_period("2026-07"))
        bonus = asyncio.run(performance_bonus.list_bonuses("2026-07"))[0]
        self.assertEqual(bonus["proposed_amount"], 25000)
        with self.assertRaises(ValueError):
            asyncio.run(performance_bonus.review_bonus(bonus["id"], "reject", 999, ""))
        asyncio.run(performance_bonus.review_bonus(bonus["id"], "reject", 999, "Data belum lengkap"))
        self.assertEqual(asyncio.run(performance_bonus.list_bonuses("2026-07"))[0]["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
