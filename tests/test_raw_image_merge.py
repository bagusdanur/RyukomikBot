import os
import tempfile
import unittest

from PIL import Image

from raw_downloader.image_processing import merge_images_lossless


class RawImageMergeTests(unittest.TestCase):
    def test_merges_in_order_without_resizing_and_respects_height(self):
        with tempfile.TemporaryDirectory() as root:
            colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
            paths = []
            for index, color in enumerate(colors, 1):
                path = os.path.join(root, f"{index:03d}.png")
                Image.new("RGB", (20, 6), color).save(path, format="PNG")
                paths.append(path)

            outputs = merge_images_lossless(paths, os.path.join(root, "merged"), "ch-6", max_height=12)

            self.assertEqual(len(outputs), 2)
            with Image.open(outputs[0]) as first:
                self.assertEqual(first.format, "WEBP")
                self.assertEqual(first.size, (20, 12))
            with Image.open(outputs[1]) as second:
                self.assertEqual(second.format, "WEBP")
                self.assertEqual(second.size, (20, 6))

    def test_different_widths_are_centered_without_scaling(self):
        with tempfile.TemporaryDirectory() as root:
            wide = os.path.join(root, "001.png")
            narrow = os.path.join(root, "002.png")
            Image.new("RGB", (20, 4), "red").save(wide)
            Image.new("RGB", (10, 4), "blue").save(narrow)

            [output] = merge_images_lossless([wide, narrow], root, "ch-6", max_height=16)
            with Image.open(output) as merged:
                self.assertEqual(merged.format, "WEBP")
                self.assertEqual(merged.size, (20, 8))

    def test_single_page_taller_than_limit_is_split_before_webp_encoding(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "very-tall.png")
            Image.new("RGB", (20, 35), "purple").save(source)

            outputs = merge_images_lossless([source], root, "chapter", max_height=16)

            self.assertEqual(len(outputs), 3)
            sizes = []
            for path in outputs:
                with Image.open(path) as output:
                    sizes.append(output.size)
                    self.assertEqual(output.format, "WEBP")
                    self.assertLessEqual(output.height, 16)
            self.assertEqual(sizes, [(20, 16), (20, 16), (20, 3)])


if __name__ == "__main__":
    unittest.main()
