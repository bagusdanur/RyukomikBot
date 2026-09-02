"""Editor-safe RAW image processing before Filebin upload."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_RAW_IMAGE_HEIGHT = int(os.getenv("RAW_MAX_IMAGE_HEIGHT", "8192"))
RAW_MODES = {"editor_safe", "original"}
MAX_MERGED_HEIGHT = int(os.getenv("RAW_MERGED_HEIGHT", "16000"))
RAW_WEBP_QUALITY = max(80, min(100, int(os.getenv("RAW_WEBP_QUALITY", "95"))))


@dataclass(frozen=True)
class ResizeResult:
    resized: bool
    original_height: int | None = None
    final_height: int | None = None


def convert_images_to_webp(
    image_paths: Iterable[str], output_dir: str, quality: int = RAW_WEBP_QUALITY
) -> list[str]:
    """Convert ordered RAW pages to high-quality WebP without changing dimensions."""
    if quality < 1 or quality > 100:
        raise ValueError("quality must be between 1 and 100")
    os.makedirs(output_dir, exist_ok=True)
    outputs: list[str] = []
    for index, path in enumerate(image_paths, 1):
        output = os.path.join(output_dir, f"{index:03d}.webp")
        with Image.open(path) as opened:
            source = ImageOps.exif_transpose(opened)
            converted = None
            try:
                image = source
                if image.mode not in {"RGB", "RGBA"}:
                    converted = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                    image = converted
                image.save(output, format="WEBP", quality=quality, method=6)
            finally:
                if converted is not None:
                    converted.close()
                if source is not opened:
                    source.close()
        outputs.append(output)
    return outputs


def merge_images_lossless(
    image_paths: Iterable[str], output_dir: str, stem: str, max_height: int = MAX_MERGED_HEIGHT
) -> list[str]:
    """Vertically pack ordered pages into WebP quality 95 without resizing dimensions."""
    if max_height < 1:
        raise ValueError("max_height must be positive")
    paths = list(image_paths)
    os.makedirs(output_dir, exist_ok=True)
    groups: list[list[tuple[str, int, int]]] = []
    current: list[tuple[str, int, int]] = []
    current_height = 0
    for path in paths:
        with Image.open(path) as source:
            width, height = ImageOps.exif_transpose(source).size
        if current and current_height + height > max_height:
            groups.append(current)
            current, current_height = [], 0
        current.append((path, width, height))
        current_height += height
        if current_height >= max_height:
            groups.append(current)
            current, current_height = [], 0
    if current:
        groups.append(current)

    outputs: list[str] = []
    for part, group in enumerate(groups, 1):
        canvas_width = max(width for _, width, _ in group)
        canvas_height = sum(height for _, _, height in group)
        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        y = 0
        for path, width, height in group:
            with Image.open(path) as source:
                page = ImageOps.exif_transpose(source)
                if page.mode != "RGB":
                    if "A" in page.getbands():
                        layer = Image.new("RGB", page.size, "white")
                        layer.paste(page, mask=page.getchannel("A"))
                        page = layer
                    else:
                        page = page.convert("RGB")
                canvas.paste(page, ((canvas_width - width) // 2, y))
            y += height
        output = os.path.join(output_dir, f"{Path(stem).stem}_part{part:03d}.webp")
        canvas.save(output, format="WEBP", quality=RAW_WEBP_QUALITY, method=6)
        canvas.close()
        outputs.append(output)
    return outputs


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
            directory = os.path.dirname(image_path) or "."
            suffix = os.path.splitext(image_path)[1] or ".jpg"
            descriptor, temporary_path = tempfile.mkstemp(prefix=".editor-safe-", suffix=suffix, dir=directory)
            os.close(descriptor)
            try:
                save_options: dict[str, object] = {}
                if image_format == "JPEG":
                    if resized.mode not in {"RGB", "L"}:
                        resized = resized.convert("RGB")
                    save_options = {"quality": 95, "subsampling": 0, "optimize": True}
                elif image_format == "WEBP":
                    save_options = {"quality": 95, "method": 6}
                resized.save(temporary_path, format=image_format, **save_options)
                os.replace(temporary_path, image_path)
            finally:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)
            return ResizeResult(True, height, max_height)
    except (OSError, UnidentifiedImageError, ValueError) as error:
        print(f"RAW editor-safe resize skipped for {os.path.basename(image_path)}: {error}")
        return ResizeResult(False)
