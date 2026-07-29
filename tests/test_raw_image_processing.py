import os
import tempfile
import unittest

from PIL import Image

from raw_downloader.image_processing import resize_for_editor


class RawImageProcessingTests(unittest.TestCase):
    def test_tall_image_is_resized_with_ratio_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "page.jpg")
            Image.new("RGB", (1000, 10000), "white").save(path, quality=100)
            result = resize_for_editor(path, max_height=8192)
            self.assertTrue(result.resized)
            self.assertEqual(os.path.splitext(result.output_path or "")[1], ".png")
            with Image.open(result.output_path) as image:
                self.assertEqual(image.height, 8192)
                self.assertEqual(image.width, 819)
                self.assertEqual(image.format, "PNG")

    def test_normal_image_is_not_reencoded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "page.png")
            Image.new("RGB", (1000, 4000), "white").save(path)
            original_size = os.path.getsize(path)
            result = resize_for_editor(path, max_height=8192)
            self.assertFalse(result.resized)
            self.assertEqual(os.path.getsize(path), original_size)

    def test_tall_png_keeps_png_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "page.png")
            Image.new("RGBA", (1000, 10000), (255, 255, 255, 150)).save(path)
            result = resize_for_editor(path, max_height=8192)
            self.assertTrue(result.resized)
            with Image.open(result.output_path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.height, 8192)
                self.assertEqual(image.mode, "RGBA")
