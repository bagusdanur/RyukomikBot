import unittest

import project_scout as scout


class ProjectScoutTests(unittest.TestCase):
    def entry(self, source, title, chapter=None, group="indonesia"):
        return {
            "source": source, "source_group": group, "source_id": title,
            "slug": title, "title": title, "normalized_title": scout.normalize_title(title),
            "alternative_titles": [], "cover_url": None, "synopsis": "", "genres": [],
            "content_type": None, "publication_status": None, "latest_chapter": chapter,
            "chapter_count": None, "detail_url": None, "match_score": 0,
        }

    def test_title_normalisation_handles_punctuation(self):
        self.assertEqual(
            scout.normalize_title("Let’s Do It After Work!"),
            scout.normalize_title("lets-do-it-after-work"),
        )

    def test_untranslated_when_no_confident_match(self):
        raw = [self.entry("omega", "Affair Agency", 11, "raw")]
        result = scout._classify(raw, [self.entry("komiku", "Different Story", 30)])
        self.assertEqual(result["status"], "untranslated")

    def test_exact_indonesian_match_is_available(self):
        raw = [self.entry("omega", "Affair Agency", 11, "raw")]
        result = scout._classify(raw, [self.entry("komiku", "Affair Agency", 10)])
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["confidence"], 100)

    def test_large_chapter_gap_is_lagging(self):
        raw = [self.entry("thunder", "Example Project", 20, "raw")]
        result = scout._classify(raw, [self.entry("komikid", "Example Project", 12)])
        self.assertEqual(result["status"], "lagging")
        self.assertEqual(result["chapter_gap"], 8)

    def test_internal_project_takes_priority(self):
        raw = [self.entry("asura", "Existing Project", 5, "raw")]
        internal = self.entry("ryukomik", "Existing Project", 3, "internal")
        result = scout._classify(raw, [internal])
        self.assertEqual(result["status"], "ryukomik_project")


if __name__ == "__main__":
    unittest.main()
