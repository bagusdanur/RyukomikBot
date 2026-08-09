"""OCR service — ekstrak teks dialog English dari RAW webtoon via MiMo v2.5 vision.

Dipakai TL: upload RAW -> teks dialog bernomor per-bubble, urut atas-bawah.
MiMo dipilih setelah benchmark: ~95% akurat vs Tesseract ~55% (baca overlay
system box & teks di area gelap yang Tesseract gagal). Pakai saldo Xiaomi
yang sudah ada, tanpa API key baru.
"""
from __future__ import annotations

import base64
import io
import json
import os
import asyncio
from pathlib import Path

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")
MIMO_MODEL = os.getenv("MIMO_OCR_MODEL", "mimo-v2.5")
# Lebar target saat resize — >400px sering timeout di MiMo, 380 aman & tajam.
OCR_TARGET_WIDTH = int(os.getenv("OCR_TARGET_WIDTH", "380"))
OCR_JPEG_QUALITY = int(os.getenv("OCR_JPEG_QUALITY", "72"))
# Webtoon panjang: potong jadi segmen tinggi agar MiMo tidak kehilangan detail
# dan payload tetap kecil. 4500px per segmen (rasio ~1:12 pada lebar 380).
OCR_SEGMENT_HEIGHT = int(os.getenv("OCR_SEGMENT_HEIGHT", "4500"))
OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "90"))

_PROMPT = (
    "Ini halaman webtoon/manhwa berbahasa Inggris. Ekstrak SEMUA teks dialog "
    "di dalam speech bubble DAN teks system/notification/status box, urut dari "
    "ATAS ke BAWAH. Aturan:\n"
    "1. Format tiap baris: nomor urut lalu teksnya. Contoh: '1. HELLO THERE'\n"
    "2. ABAIKAN sound effect Jepang/katakana (contoh: ドクン, カハッ) dan SFX.\n"
    "3. Pertahankan teks PERSIS seperti tertulis (jangan terjemahkan).\n"
    "4. Kalau tidak ada teks sama sekali, tulis: (tidak ada teks)\n"
    "5. Jangan tambahkan komentar atau penjelasan lain, cuma daftar teksnya."
)


class OcrError(Exception):
    """Kesalahan yang aman ditampilkan ke user."""


def _load_api_key() -> str:
    key = os.getenv("XIAOMI_API_KEY", "").strip()
    if key:
        return key
    # Fallback: baca dari ~/.hermes/.env (tempat key aslinya tinggal)
    hermes_env = Path.home() / ".hermes" / ".env"
    try:
        for line in hermes_env.read_text().splitlines():
            if line.startswith("XIAOMI_API_KEY="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    raise OcrError("XIAOMI_API_KEY belum dikonfigurasi untuk OCR.")


def _prepare_segments(data: bytes) -> list[str]:
    """Resize + potong gambar panjang jadi segmen, return list base64 JPEG."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise OcrError(f"Gambar tidak valid atau rusak: {error}") from error

    w, h = img.size
    if w > OCR_TARGET_WIDTH:
        ratio = OCR_TARGET_WIDTH / w
        img = img.resize((OCR_TARGET_WIDTH, int(h * ratio)), Image.LANCZOS)
        w, h = img.size

    segments: list[str] = []
    y = 0
    # Overlap kecil antar-segmen biar bubble yang kepotong tetap kebaca di salah satu.
    overlap = 200
    while y < h:
        bottom = min(h, y + OCR_SEGMENT_HEIGHT)
        crop = img.crop((0, y, w, bottom))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=OCR_JPEG_QUALITY)
        segments.append(base64.b64encode(buf.getvalue()).decode())
        if bottom >= h:
            break
        y = bottom - overlap
    return segments


async def _ocr_one_segment(client: httpx.AsyncClient, api_key: str, b64: str) -> str:
    payload = {
        "model": MIMO_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
    }
    try:
        resp = await client.post(
            f"{MIMO_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=OCR_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as error:
        raise OcrError("OCR timeout — gambar terlalu besar atau server sibuk.") from error
    except httpx.HTTPError as error:
        raise OcrError(f"Gagal menghubungi layanan OCR: {error}") from error

    if resp.status_code != 200:
        raise OcrError(f"Layanan OCR menolak permintaan (HTTP {resp.status_code}).")
    body = resp.json()
    choices = body.get("choices")
    if not choices:
        raise OcrError("Layanan OCR tidak mengembalikan hasil.")
    return (choices[0].get("message", {}).get("content") or "").strip()


def _renumber(raw_blocks: list[str]) -> str:
    """Gabung hasil per-segmen jadi satu daftar bernomor ulang, buang duplikat overlap."""
    lines: list[str] = []
    seen: set[str] = set()
    for block in raw_blocks:
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "(tidak ada teks)":
                continue
            # Buang nomor lama di depan (mis. "1. ", "12) ")
            text = stripped
            for sep in (". ", ") ", "- ", ": "):
                head, found, tail = text.partition(sep)
                if found and head.strip().rstrip(".").isdigit():
                    text = tail.strip()
                    break
            key = "".join(text.lower().split())
            if not text or key in seen:
                continue
            seen.add(key)
            lines.append(text)
    if not lines:
        return "(tidak ada teks terdeteksi)"
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


async def extract_text(data: bytes) -> dict:
    """OCR satu gambar RAW. Return {text, segments, bubble_count}."""
    api_key = _load_api_key()
    segments = _prepare_segments(data)
    async with httpx.AsyncClient() as client:
        blocks = []
        for b64 in segments:
            blocks.append(await _ocr_one_segment(client, api_key, b64))
    text = _renumber(blocks)
    bubble_count = 0 if text.startswith("(tidak ada") else len(text.splitlines())
    return {"text": text, "segments": len(segments), "bubble_count": bubble_count}
