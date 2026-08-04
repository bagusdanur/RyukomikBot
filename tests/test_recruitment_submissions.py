import os
import tempfile
import unittest
from datetime import datetime, timezone

import database
from recruitment.ticket import (
    RecruitmentApproveDynamic,
    RecruitmentPositionView,
    RecruitmentView,
    RecruitmentSubmitView,
    build_test_embed,
    build_recruitment_panel_embed,
    build_review_embed,
    material_status,
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

    async def test_unified_test_card_has_only_current_material_actions(self):
        expected_links = {
            "TL": ["Download Bahan Tes"],
            "TS": ["Download Bahan Tes", "Asset TS"],
            "TL+TS": ["Download Bahan Tes", "Asset TS"],
        }
        for position, labels in expected_links.items():
            view = RecruitmentSubmitView(position)
            link_labels = [item.label for item in view.children if getattr(item, "url", None)]
            self.assertEqual(link_labels, labels)
            self.assertNotIn("Instruksi TL", link_labels)
            self.assertNotIn("Instruksi TS", link_labels)
            self.assertNotIn("Referensi Terjemahan", link_labels)
            self.assertIn("12 halaman", build_test_embed(position).description)

    async def test_position_instructions_are_specific_and_complete(self):
        tl = build_test_embed("TL")
        ts = build_test_embed("TS")
        both = build_test_embed("TL+TS")
        self.assertIn("aku/kamu", tl.description)
        self.assertIn("cleaning, redraw, dan typesetting", ts.description)
        self.assertIn("Asset TS", ts.description)
        ts_guide = next(field.value for field in ts.fields if field.name == "Panduan TS • Cleaning & Font")
        self.assertIn("CC Wild Words", ts_guide)
        self.assertIn("Cleaning & redraw", ts_guide)
        output_guide = next(field.value for field in ts.fields if field.name == "Panduan TS • Penempatan & Output")
        self.assertIn("Pertahankan resolusi", output_guide)
        self.assertFalse(any(field.name.startswith("Panduan TS") for field in tl.fields))
        self.assertIn("Terjemahkan", both.description)
        self.assertIn("typesetting", both.description)
        self.assertIn("Bagian TL (Translator)", both.description)
        self.assertIn("Bagian TS (Typesetter / Editor)", both.description)
        self.assertIn("hasil terjemahanmu", both.description)
        self.assertTrue(any(field.name.startswith("Panduan TS") for field in both.fields))

    async def test_material_expiry_status(self):
        self.assertEqual(material_status(datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc))["status"], "expiring")
        self.assertEqual(material_status(datetime(2026, 8, 12, tzinfo=timezone.utc))["status"], "expired")


if __name__ == "__main__":
    unittest.main()
