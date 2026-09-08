import unittest

from yuki_discord import response_embeds, response_view


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

    def test_comics_become_rich_cards_and_link_buttons(self):
        payload = {
            "reply": "Aku punya rekomendasi.\n\n**Judul Bagus** — silakan baca.",
            "mood": "senang",
            "comics": [{
                "title": "Judul Bagus", "url": "https://ryde.com/komik/judul-bagus",
                "image": "https://img.example/cover.jpg", "format": "MANGA",
                "type": "Romance, Comedy", "chapter": "Chapter 12", "score": "8.7",
            }],
        }
        embeds = response_embeds(payload)
        self.assertEqual(len(embeds), 2)
        self.assertNotIn("Judul Bagus", embeds[0].description)
        self.assertEqual(embeds[1].title, "Judul Bagus")
        self.assertEqual(embeds[1].thumbnail.url, "https://img.example/cover.jpg")
        self.assertEqual(len(response_view(payload).children), 1)


if __name__ == "__main__":
    unittest.main()
