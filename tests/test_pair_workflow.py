import asyncio
import os
import sqlite3
import tempfile
import unittest

import database
import pair_workflow


class PairWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp_dir.name, "pair.db")
        asyncio.run(database.setup_database())

    def tearDown(self):
        database.DB_PATH = self.old_path
        self.temp_dir.cleanup()

    def create_pair(self, chapters=None):
        return asyncio.run(pair_workflow.create_project(
            manga="Pair Project", chapters=chapters or ["1", "2"],
            tl_staff_id=100, ts_staff_id=200,
            tl_rate_per_chapter=4000, ts_rate_per_chapter=5000,
            deadline_at="2026-08-20", created_by=999,
        ))

    def test_each_chapter_has_two_locked_assignments(self):
        project = self.create_pair()
        connection = sqlite3.connect(database.DB_PATH)
        rows = connection.execute(
            "SELECT role,chapter,status,final_rate FROM assignments WHERE pair_project_id=? ORDER BY chapter,role",
            (project["id"],),
        ).fetchall()
        connection.close()
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row[2] == "pair_waiting" for row in rows))
        self.assertEqual(sum(row[3] for row in rows), 18000)

    def test_tl_and_ts_must_finish_before_atomic_pay_release(self):
        project = self.create_pair(["1"])
        chapter_id = project["chapters"][0]["id"]
        self.assertIsNone(asyncio.run(pair_workflow.approve_final(chapter_id, 999)))
        self.assertTrue(asyncio.run(pair_workflow.submit_tl(
            chapter_id, 100, "https://drive.google.com/tl", None
        )))
        self.assertTrue(asyncio.run(pair_workflow.submit_final(
            chapter_id, 200, "https://drive.google.com/final", None
        )))
        approved = asyncio.run(pair_workflow.approve_final(chapter_id, 999))
        self.assertIsNotNone(approved)
        connection = sqlite3.connect(database.DB_PATH)
        states = connection.execute(
            "SELECT role,status,approved_at FROM assignments WHERE pair_chapter_id=? ORDER BY role",
            (chapter_id,),
        ).fetchall()
        connection.close()
        self.assertEqual([row[1] for row in states], ["approved", "approved"])
        self.assertEqual(states[0][2], states[1][2])

    def test_ts_can_return_translation_without_releasing_salary(self):
        project = self.create_pair(["1"])
        chapter_id = project["chapters"][0]["id"]
        asyncio.run(pair_workflow.submit_tl(chapter_id, 100, "https://drive.google.com/tl", None))
        self.assertTrue(asyncio.run(pair_workflow.request_revision(
            chapter_id, 200, "tl", "Perbaiki dialog halaman 3."
        )))
        chapter = asyncio.run(pair_workflow.get_chapter(chapter_id))
        self.assertEqual(chapter["status"], "tl_revision")
        timeline = asyncio.run(pair_workflow.timeline(project["id"]))
        revision = next(item for item in timeline if item["event_type"] == "revision_tl")
        self.assertIn("Perbaiki dialog halaman 3.", revision["detail"])
        connection = sqlite3.connect(database.DB_PATH)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM assignments WHERE status='approved'").fetchone()[0], 0
        )
        connection.close()

    def test_one_chapter_can_complete_without_waiting_for_rest(self):
        project = self.create_pair(["1", "2"])
        first = project["chapters"][0]["id"]
        asyncio.run(pair_workflow.submit_tl(first, 100, "https://drive.google.com/tl", None))
        asyncio.run(pair_workflow.submit_final(first, 200, "https://drive.google.com/final", None))
        asyncio.run(pair_workflow.approve_final(first, 999))
        current = asyncio.run(pair_workflow.get_project(project["id"]))
        self.assertEqual(current["status"], "active")
        self.assertEqual([item["status"] for item in current["chapters"]], ["completed", "waiting_tl"])

    def test_wrong_staff_cannot_submit(self):
        project = self.create_pair(["1"])
        chapter_id = project["chapters"][0]["id"]
        self.assertFalse(asyncio.run(pair_workflow.submit_tl(
            chapter_id, 200, "https://drive.google.com/wrong", None
        )))
        self.assertFalse(asyncio.run(pair_workflow.submit_final(
            chapter_id, 100, "https://drive.google.com/wrong", None
        )))

    def test_same_manga_workspace_can_be_reused(self):
        project = self.create_pair(["1"])
        asyncio.run(pair_workflow.set_workspace(project["id"], 12345, 67890))
        reusable = asyncio.run(pair_workflow.find_reusable_workspace("Pair Project"))
        self.assertEqual(reusable["id"], project["id"])
        self.assertEqual(reusable["channel_id"], 12345)
        self.assertIsNotNone(asyncio.run(pair_workflow.find_reusable_workspace("pair-project!")))
        self.assertIsNone(asyncio.run(pair_workflow.find_reusable_workspace("Different Manga")))

    def test_active_same_manga_workspace_is_reused(self):
        project = self.create_pair(["1"])
        asyncio.run(pair_workflow.set_workspace(project["id"], 12345, 67890))
        self.assertEqual(asyncio.run(pair_workflow.find_reusable_workspace("Pair Project"))["channel_id"], 12345)

    def test_latest_batch_is_selected_for_workspace_menu(self):
        first = self.create_pair(["1"])
        asyncio.run(pair_workflow.set_workspace(first["id"], 12345, 111))
        second = self.create_pair(["2"])
        asyncio.run(pair_workflow.set_workspace(second["id"], 12345, 222))
        latest = asyncio.run(pair_workflow.get_latest_project_by_channel(12345))
        self.assertEqual(latest["id"], second["id"])
        self.assertEqual(latest["panel_message_id"], 222)

    def test_ts_handoff_message_is_stored_per_chapter(self):
        project = self.create_pair(["1"])
        chapter_id = project["chapters"][0]["id"]
        asyncio.run(pair_workflow.set_ts_handoff_message(chapter_id, 987654321))
        chapter = asyncio.run(pair_workflow.get_chapter(chapter_id))
        self.assertEqual(chapter["ts_handoff_message_id"], 987654321)


if __name__ == "__main__":
    unittest.main()
