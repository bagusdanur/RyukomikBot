"""Editor-safe RAW image processing before Filebin upload."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_RAW_IMAGE_HEIGHT = int(os.getenv("RAW_MAX_IMAGE_HEIGHT", "8192"))


@dataclass(frozen=True)
class ResizeResult:
    resized: bool
    original_height: int | None = None
    final_height: int | None = None


def resize_for_editor(image_path: str, max_height: int = MAX_RAW_IMAGE_HEIGHT) -> ResizeResult:
    """Limit portrait RAW height while retaining ratio and high-quality pixels.

    Unsupported/corrupt files are preserved so a single bad source image never
    blocks the complete chapter download.
    """
    if max_height < 1:
        raise ValueError("max_height must be positive")
    try:
        with Image.open(image_path) as source:
            image_format = (source.format or "").upper()
            if image_format == "JPG":
                image_format = "JPEG"
            if image_format not in {"JPEG", "PNG", "WEBP"}:
                print(
                    f"RAW editor-safe resize skipped for {os.path.basename(image_path)}: "
                    f"unsupported format {image_format or 'unknown'}"
                )
                return ResizeResult(False)
            source = ImageOps.exif_transpose(source)
            width, height = source.size
            if height <= max_height:
                return ResizeResult(False, height, height)

            final_width = max(1, round(width * max_height / height))
            resized = source.resize((final_width, max_height), Image.Resampling.LANCZOS)
            if image_format == "JPEG" and resized.mode not in {"RGB", "L"}:
                resized = resized.convert("RGB")

            directory = os.path.dirname(image_path) or "."
            suffix = os.path.splitext(image_path)[1] or ".jpg"
            descriptor, temporary_path = tempfile.mkstemp(prefix=".editor-safe-", suffix=suffix, dir=directory)
            os.close(descriptor)
            try:
                save_options: dict[str, object] = {}
                if image_format == "JPEG":
                    # Keep scanlation text and screentones as clean as possible.  The
                    # user explicitly prefers larger Filebin downloads over a second
                    # lossy compression pass.
                    save_options = {"quality": 100, "subsampling": 0, "optimize": True}
                elif image_format == "WEBP":
                    save_options = {"quality": 100, "method": 6}
                resized.save(temporary_path, format=image_format, **save_options)
                os.replace(temporary_path, image_path)
            finally:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)
            return ResizeResult(True, height, max_height)
    except (OSError, UnidentifiedImageError, ValueError) as error:
        print(f"RAW editor-safe resize skipped for {os.path.basename(image_path)}: {error}")
        return ResizeResult(False)
