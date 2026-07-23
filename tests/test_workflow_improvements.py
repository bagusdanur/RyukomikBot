import asyncio
import os
import tempfile
import unittest

import database


class WorkflowImprovementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp.name, "workflow.db")
        asyncio.run(database.setup_database())

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp.cleanup()

    def test_timeline_records_assignment_transitions(self):
        assignment_id = asyncio.run(database.create_assignment(
            "Series", "1", "TL", 3000, 3000, 1.0
        ))
        self.assertTrue(asyncio.run(database.claim_assignment(assignment_id, 123)))
        self.assertTrue(asyncio.run(database.submit_assignment(
            assignment_id, "https://drive.google.com/folder"
        )))
        self.assertTrue(asyncio.run(database.approve_assignment(assignment_id)))
        events = asyncio.run(database.get_assignment_timeline(assignment_id))
        self.assertEqual(
            [item["event_type"] for item in events],
            ["created", "claimed", "submitted", "approved"],
        )

    def test_reminder_key_is_idempotent(self):
        assignment_id = asyncio.run(database.create_assignment(
            "Series", "1", "TS", 5000, 5000, 1.0
        ))
        self.assertTrue(asyncio.run(database.claim_reminder(
            "deadline-h1:1:2026-07-24", assignment_id, "staff"
        )))
        self.assertFalse(asyncio.run(database.claim_reminder(
            "deadline-h1:1:2026-07-24", assignment_id, "staff"
        )))


if __name__ == "__main__":
    unittest.main()
