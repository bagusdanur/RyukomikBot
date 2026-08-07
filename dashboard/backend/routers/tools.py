"""Tools router — WebP converter and other utilities."""

import logging
import traceback
from io import BytesIO
from pathlib import Path
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from PIL import Image

from dashboard.backend.deps import admin_user

log = logging.getLogger("tools")

router = APIRouter(prefix="/api/tools", tags=["tools"])

MAX_CONVERT_HEIGHT = 16000
SPLIT_HEIGHT = 12000


def _convert_one(file_data: bytes, filename: str, quality: int) -> list[dict]:
    img = Image.open(BytesIO(file_data))
    stem = Path(filename).stem
    results: list[dict] = []

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    width, height = img.size

    def save_webp(image) -> bytes:
        buf = BytesIO()
        image.save(buf, format="WEBP", quality=quality, method=4)
        buf.seek(0)
        return buf.read()

    if height <= MAX_CONVERT_HEIGHT:
        data = save_webp(img)
        results.append({"name": f"{stem}.webp", "data": data})
    else:
        part = 1
        y = 0
        while y < height:
            crop_h = min(SPLIT_HEIGHT, height - y)
            chunk = img.crop((0, y, width, y + crop_h))
            data = save_webp(chunk)
            results.append({"name": f"{stem}_part{part:02d}.webp", "data": data})
            y += crop_h
            part += 1

    return results


@router.post("/webp-convert")
async def webp_convert(request: Request, user=Depends(admin_user)):
    try:
        form = await request.form()
        quality_raw = form.get("quality", "95")
        try:
            quality = int(str(quality_raw))
        except (TypeError, ValueError):
            quality = 95
        quality = max(1, min(100, quality))

        files = form.getlist("files")
        if not files:
            raise HTTPException(status_code=400, detail="Tidak ada file yang diupload.")

        all_results: list[dict] = []
        for upload in files:
            ext = Path(upload.filename).suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg"):
                continue
            file_data = await upload.read()
            log.info(f"Processing {upload.filename} ({len(file_data)} bytes, quality={quality})")
            parts = _convert_one(file_data, upload.filename, quality)
            all_results.extend(parts)

        if not all_results:
            raise HTTPException(status_code=400, detail="Tidak ada gambar valid.")

        if len(all_results) == 1:
            return Response(
                content=all_results[0]["data"],
                media_type="image/webp",
                headers={"Content-Disposition": f'attachment; filename="{all_results[0]["name"]}"'},
            )

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for r in all_results:
                zf.writestr(r["name"], r["data"])
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="webp_converted.zip"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"webp-convert error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
