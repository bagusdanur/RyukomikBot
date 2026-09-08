import unittest

from yuki_discord import response_embeds


class YukiDiscordTests(unittest.TestCase):
    def test_response_embed_uses_mood_and_bond(self):
        [embed] = response_embeds({"reply": "Halo!", "mood": "senang", "bond": "teman"})
        self.assertEqual(embed.description, "Halo!")
        self.assertIn("Senang", embed.footer.text)
        self.assertIn("teman", embed.footer.text)

    def test_long_reply_is_split_below_discord_limit(self):
        embeds = response_embeds({"reply": "a" * 8001})
        self.assertEqual(len(embeds), 3)
        self.assertTrue(all(len(embed.description) <= 3900 for embed in embeds))


if __name__ == "__main__":
    unittest.main()
