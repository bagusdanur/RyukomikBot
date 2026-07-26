import os
import tempfile
import unittest

import database
from recruitment.ticket import (
    RecruitmentApproveDynamic,
    RecruitmentPositionView,
    RecruitmentView,
    build_recruitment_panel_embed,
    build_review_embed,
)


class RecruitmentSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_path = database.DB_PATH
        self.temporary_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(
            self.temporary_directory.name,
            "recruitment.db",
        )
        await database.setup_database()

    async def asyncTearDown(self):
        database.DB_PATH = self.original_path
        self.temporary_directory.cleanup()

    async def test_resubmit_updates_one_active_submission(self):
        first = await database.upsert_recruitment_submission(
            123,
            "TL",
            456,
            "https://drive.google.com/first",
            "Pertama",
        )
        await database.set_recruitment_review_message(first["id"], 789)
        second = await database.upsert_recruitment_submission(
            123,
            "TL+TS",
            456,
            "https://drive.google.com/second",
            "Diperbarui",
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["review_message_id"], 789)
        self.assertEqual(second["position"], "TL+TS")
        self.assertEqual(second["gdrive_link"], "https://drive.google.com/second")

    async def test_approval_is_idempotent(self):
        submission = await database.upsert_recruitment_submission(
            123,
            "TS",
            456,
            "https://drive.google.com/result",
        )
        self.assertTrue(
            await database.approve_recruitment_submission(submission["id"], 999)
        )
        self.assertFalse(
            await database.approve_recruitment_submission(submission["id"], 999)
        )
        approved = await database.get_recruitment_submission(submission["id"])
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["reviewed_by"], 999)

    async def test_position_settings_are_independent_and_persistent(self):
        defaults = await database.get_recruitment_position_settings()
        self.assertEqual(defaults, {"TL": True, "TS": True, "TL+TS": True})
        updated = await database.set_recruitment_position_settings(
            {"TL": True, "TS": False, "TL+TS": True},
            999,
        )
        self.assertEqual(updated, {"TL": True, "TS": False, "TL+TS": True})
        self.assertEqual(await database.get_recruitment_position_settings(), updated)

    async def test_review_card_and_custom_id_contain_submission_identity(self):
        submission = {
            "id": 7,
            "applicant_id": 123,
            "position": "TL",
            "ticket_channel_id": 456,
            "gdrive_link": "https://drive.google.com/result",
            "notes": "Selesai",
        }
        embed = build_review_embed(submission)
        fields = {field.name: field.value for field in embed.fields}
        dynamic_item = RecruitmentApproveDynamic(7)

        self.assertEqual(fields["Tiket Pelamar"], "<#456>")
        self.assertEqual(fields["Link Hasil"], submission["gdrive_link"])
        self.assertEqual(
            dynamic_item.item.custom_id,
            "recruitment:approve:7:v2",
        )

    async def test_panel_and_position_menu_follow_enabled_settings(self):
        panel = build_recruitment_panel_embed(["TL"])
        field_names = [field.name for field in panel.fields]
        self.assertTrue(any("TL" in name for name in field_names))
        self.assertTrue(any("TS —" in name and "CLOSED" in name for name in field_names))

        selector_view = RecruitmentPositionView(["TS", "TL+TS"])
        values = [option.value for option in selector_view.children[0].options]
        self.assertEqual(values, ["TS", "TL+TS"])

        closed_view = RecruitmentView([])
        self.assertTrue(closed_view.children[0].disabled)


if __name__ == "__main__":
    unittest.main()
