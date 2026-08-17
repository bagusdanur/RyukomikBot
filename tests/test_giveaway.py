"""Comprehensive unit tests for the Ryukomik Giveaway system."""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from datetime import datetime, timezone

import discord

import giveaway_service as gservice
from views.giveaway_views import GiveawayJoinDynamic


class GiveawayServiceUnitTests(unittest.TestCase):
    """Test duration parsing, embed builders, winner drawing, and announcement texts."""

    def test_parse_duration_units(self):
        self.assertEqual(gservice.parse_duration("30s"), 30)
        self.assertEqual(gservice.parse_duration("10m"), 600)
        self.assertEqual(gservice.parse_duration("2h"), 7200)
        self.assertEqual(gservice.parse_duration("3d"), 3 * 86400)
        self.assertEqual(gservice.parse_duration("7d"), 7 * 86400)
        self.assertEqual(gservice.parse_duration("30d"), 30 * 86400)
        self.assertEqual(gservice.parse_duration("1w"), 7 * 86400)

    def test_parse_duration_combined_and_case(self):
        self.assertEqual(gservice.parse_duration("1d 2h 30m"), 86400 + 7200 + 1800)
        self.assertEqual(gservice.parse_duration("7D"), 7 * 86400)
        self.assertEqual(gservice.parse_duration("  10M  "), 600)

    def test_parse_duration_invalid(self):
        self.assertEqual(gservice.parse_duration(""), 0)
        self.assertEqual(gservice.parse_duration("invalid"), 0)
        self.assertEqual(gservice.parse_duration("-5m"), 0)

    def test_build_giveaway_embed_premium(self):
        giveaway = {
            "id": 1,
            "prize": gservice.PREMIUM_30D,
            "host_id": 123456789,
            "ends_at": "2026-08-20T12:00:00+00:00",
            "winner_count": 2,
            "description": "Event Spesial Ryukomik",
            "requirement_role_id": 999888,
        }
        embed = gservice.build_giveaway_embed(giveaway, entry_count=15)
        self.assertIn("GIVEAWAY", embed.title)
        self.assertIn("Ryukomik Premium 30 Hari", embed.title)
        self.assertIn("<@123456789>", embed.description)
        self.assertIn("`2` Orang", embed.description)
        self.assertIn("`15` Orang", embed.description)
        
        # Check requirement field
        role_field = next((f for f in embed.fields if "Syarat Khusus" in f.name), None)
        self.assertIsNotNone(role_field)
        self.assertIn("<@&999888>", role_field.value)

        # Check premium perks field
        perks_field = next((f for f in embed.fields if "Keuntungan" in f.name), None)
        self.assertIsNotNone(perks_field)
        self.assertIn("bebas iklan", perks_field.value)

    def test_build_giveaway_ended_embed(self):
        giveaway = {
            "id": 1,
            "prize": gservice.PREMIUM_7D,
            "host_id": 123456789,
            "winner_count": 1,
        }
        embed = gservice.build_giveaway_ended_embed(giveaway, winner_ids=[555555], entry_count=20)
        self.assertIn("BERAKHIR", embed.title)
        self.assertIn("<@555555>", embed.description)
        
        claim_field = next((f for f in embed.fields if "Klaim Hadiah" in f.name), None)
        self.assertIsNotNone(claim_field)
        self.assertIn("DM/Chat Admin", claim_field.value)

    def test_build_winner_announcement_instructs_dm_admin(self):
        giveaway = {
            "id": 42,
            "prize": "Ryukomik Premium 7 Hari",
            "host_id": 1001,
        }
        text = gservice.build_winner_announcement(giveaway, [2001, 2002])
        self.assertIn("<@2001>", text)
        self.assertIn("<@2002>", text)
        self.assertIn("DM / Chat Admin", text)
        self.assertIn("<@1001>", text)
        self.assertIn("https://ryukomik.my.id", text)

    def test_draw_random_winners(self):
        candidates = [1, 2, 3, 4, 5]
        winners = gservice.draw_random_winners(candidates, count=2)
        self.assertEqual(len(winners), 2)
        self.assertTrue(set(winners).issubset(set(candidates)))

        # When requesting more winners than candidates
        winners_all = gservice.draw_random_winners(candidates, count=10)
        self.assertEqual(len(winners_all), 5)
        self.assertEqual(set(winners_all), set(candidates))

        # Empty candidates
        self.assertEqual(gservice.draw_random_winners([], count=1), [])


class GiveawayDatabaseIntegrationTests(unittest.TestCase):
    """Test raw SQLite schema and CRUD lifecycle."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.conn = sqlite3.connect(self.temp_db.name)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                host_id INTEGER NOT NULL,
                prize TEXT NOT NULL,
                description TEXT,
                winner_count INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                requirement_role_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                ends_at DATETIME NOT NULL,
                ended_at DATETIME,
                winners_json TEXT
            );

            CREATE TABLE giveaway_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                giveaway_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(giveaway_id, user_id),
                FOREIGN KEY(giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
            );
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_create_and_query_giveaway(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO giveaways (guild_id, channel_id, host_id, prize, ends_at, winner_count)
            VALUES (100, 200, 300, 'Ryukomik Premium 30 Hari', '2026-08-20T12:00:00+00:00', 2)
        """)
        self.conn.commit()
        giveaway_id = cursor.lastrowid
        self.assertGreater(giveaway_id, 0)

        row = cursor.execute("SELECT * FROM giveaways WHERE id=?", (giveaway_id,)).fetchone()
        self.assertEqual(row["prize"], "Ryukomik Premium 30 Hari")
        self.assertEqual(row["winner_count"], 2)
        self.assertEqual(row["status"], "active")

    def test_toggle_entries_and_count(self):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO giveaways (guild_id, channel_id, host_id, prize, ends_at) VALUES (1, 2, 3, 'P', '2026-08-20')")
        self.conn.commit()
        g_id = cursor.lastrowid

        # User 10 joins
        cursor.execute("INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)", (g_id, 10))
        self.conn.commit()

        count = cursor.execute("SELECT COUNT(*) AS total FROM giveaway_entries WHERE giveaway_id=?", (g_id,)).fetchone()["total"]
        self.assertEqual(count, 1)

        # User 10 leaves (toggle off)
        cursor.execute("DELETE FROM giveaway_entries WHERE giveaway_id=? AND user_id=?", (g_id, 10))
        self.conn.commit()

        count_after = cursor.execute("SELECT COUNT(*) AS total FROM giveaway_entries WHERE giveaway_id=?", (g_id,)).fetchone()["total"]
        self.assertEqual(count_after, 0)

    def test_end_giveaway_stores_winners_json(self):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO giveaways (guild_id, channel_id, host_id, prize, ends_at) VALUES (1, 2, 3, 'P', '2026-08-20')")
        self.conn.commit()
        g_id = cursor.lastrowid

        winners = [111, 222]
        cursor.execute("UPDATE giveaways SET status='ended', winners_json=? WHERE id=?", (json.dumps(winners), g_id))
        self.conn.commit()

        row = cursor.execute("SELECT status, winners_json FROM giveaways WHERE id=?", (g_id,)).fetchone()
        self.assertEqual(row["status"], "ended")
        self.assertEqual(json.loads(row["winners_json"]), [111, 222])


class GiveawayDynamicItemTests(unittest.TestCase):
    """Test dynamic item regex and custom_id matching."""

    def test_dynamic_item_custom_id_format(self):
        item = GiveawayJoinDynamic(giveaway_id=77)
        self.assertEqual(item.item.custom_id, "giveaway:join:77")
        self.assertEqual(item.giveaway_id, 77)

    def test_dynamic_item_from_custom_id_coro(self):
        async def run():
            item = await GiveawayJoinDynamic.from_custom_id(None, None, {"giveaway_id": "99"})
            self.assertEqual(item.giveaway_id, 99)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
