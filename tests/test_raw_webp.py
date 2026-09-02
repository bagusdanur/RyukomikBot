import os
import tempfile
import unittest

from PIL import Image

from raw_downloader.image_processing import convert_images_to_webp


class RawWebpTests(unittest.TestCase):
    def test_conversion_keeps_dimensions_and_uses_webp(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "page.png")
            with Image.new("RGB", (120, 240), "white") as image:
                image.save(source)
            [output_path] = convert_images_to_webp([source], os.path.join(directory, "webp"), 92)
            with Image.open(output_path) as output:
                self.assertEqual(output.format, "WEBP")
                self.assertEqual(output.size, (120, 240))


if __name__ == "__main__":
    unittest.main()
