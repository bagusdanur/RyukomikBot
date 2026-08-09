"""Tools router — WebP converter, OCR extractor, and other utilities."""

import logging
import traceback
from io import BytesIO
from pathlib import Path
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, JSONResponse
from PIL import Image

from dashboard.backend.deps import admin_user
from dashboard.backend import ocr_service

log = logging.getLogger("tools")

router = APIRouter(prefix="/api/tools", tags=["tools"])

MAX_CONVERT_HEIGHT = 16000
SPLIT_HEIGHT = 12000
OCR_MAX_FILE_BYTES = 15 * 1024 * 1024  # 15 MB per gambar


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


@router.post("/ocr-extract")
async def ocr_extract(request: Request, user=Depends(admin_user)):
    """Ekstrak teks dialog English dari RAW webtoon (MiMo v2.5 vision).

    Multi-file: setiap gambar diproses terpisah, hasil digabung per-halaman.
    return_format: "json" (default) atau "txt" untuk download.
    """
    try:
        form = await request.form()
        files = form.getlist("files")
        if not files:
            raise HTTPException(status_code=400, detail="Tidak ada file yang diupload.")
        return_format = str(form.get("return_format", "json")).strip().lower()

        results = []
        for idx, upload in enumerate(files, 1):
            name = getattr(upload, "filename", "") or "image"
            ext = Path(name).suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                results.append({"name": name, "ok": False,
                                "error": "Format tidak didukung (PNG/JPG/WEBP saja)."})
                continue
            data = await upload.read()
            if len(data) > OCR_MAX_FILE_BYTES:
                results.append({"name": name, "ok": False,
                                "error": "Ukuran melebihi 15 MB."})
                continue
            try:
                out = await ocr_service.extract_text(data)
                results.append({
                    "name": name, "ok": True, "page_num": idx,
                    "text": out["text"],
                    "bubble_count": out["bubble_count"],
                    "segments": out["segments"],
                })
            except ocr_service.OcrError as error:
                results.append({"name": name, "ok": False, "error": str(error)})
            except Exception as error:  # noqa: BLE001
                log.error(f"ocr-extract [{name}] error: {error}\n{traceback.format_exc()}")
                results.append({"name": name, "ok": False,
                                "error": "Gagal memproses gambar."})

        if not results:
            raise HTTPException(status_code=400, detail="Tidak ada gambar valid.")

        # Return formatted TXT if requested
        if return_format == "txt":
            lines: list[str] = []
            for r in results:
                if not r.get("ok"):
                    continue
                page = r.get("page_num", "?")
                lines.append(f"=== HALAMAN {page} ===")
                text = r.get("text", "")
                # Pastikan nomor urut bubble di-reset per halaman
                lines.append(text if text else "(tidak ada teks)")
                lines.append("")  # blank separator
            txt_content = "\n".join(lines).encode("utf-8")
            return Response(
                content=txt_content,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="ocr_extract.txt"'},
            )

        return JSONResponse({"results": results})
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"ocr-extract error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
