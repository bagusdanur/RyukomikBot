import unittest

from raw_downloader.doujiva import _image_extension, _sort_chapter_images


class DoujivaImageOrderTests(unittest.TestCase):
    def test_proxy_urls_are_sorted_by_upstream_page_number(self):
        base = "https://api.example/image?url=https%3A%2F%2Fcdn.example%2Fchapter%2F"
        images = [base + name for name in ("10-hash.jpg", "2-hash.jpg", "1-hash.jpg")]

        ordered = _sort_chapter_images(images)

        self.assertIn("1-hash.jpg", ordered[0])
        self.assertIn("2-hash.jpg", ordered[1])
        self.assertIn("10-hash.jpg", ordered[2])

    def test_object_page_metadata_takes_priority(self):
        images = [
            {"url": "https://cdn.example/unknown-b.webp", "page": 2},
            {"url": "https://cdn.example/unknown-a.webp", "page": 1},
        ]

        self.assertTrue(_sort_chapter_images(images)[0].endswith("unknown-a.webp"))

    def test_extension_comes_from_url_inside_proxy(self):
        url = "https://api.example/image?url=https%3A%2F%2Fcdn.example%2F10-page.webp"
        self.assertEqual(_image_extension(url), "webp")

    def test_unsafe_or_missing_extension_falls_back_to_jpg(self):
        self.assertEqual(_image_extension("https://api.example/image?id=1"), "jpg")


if __name__ == "__main__":
    unittest.main()
