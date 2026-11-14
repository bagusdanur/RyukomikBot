"""Tools router — WebP converter, OCR extractor, and other utilities."""

import asyncio
import logging
import os
import re
import tempfile
import traceback
from io import BytesIO
from pathlib import Path
import zipfile

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, JSONResponse, FileResponse
from dashboard.backend import raw_exports
from PIL import Image

from dashboard.backend.deps import admin_user
from dashboard.backend import ocr_service
from raw_downloader import get_downloader

log = logging.getLogger("tools")

router = APIRouter(prefix="/api/tools", tags=["tools"])

MAX_CONVERT_HEIGHT = 16000
SPLIT_HEIGHT = 12000
OCR_MAX_FILE_BYTES = 15 * 1024 * 1024  # 15 MB per gambar
TRANSLATOR_API_URL = os.getenv("TRANSLATOR_API_URL", "http://127.0.0.1:3210").rstrip("/")
TRANSLATOR_API_TOKEN = os.getenv("TRANSLATOR_API_TOKEN", "").strip()


def _raw_downloader(source: str):
    try:
        return get_downloader(source)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


async def _raw_zip(payload: dict) -> tuple[str, bytes]:
    source = str(payload.get("source") or "").strip().lower()
    manga_id = str(payload.get("manga_id") or "").strip()
    chapter_id = str(payload.get("chapter_id") or "").strip()
    if not source or not manga_id or not chapter_id:
        raise HTTPException(status_code=400, detail="Source, judul, dan chapter RAW wajib dipilih.")
    downloader = _raw_downloader(source)
    with tempfile.TemporaryDirectory(prefix="ryukomik-raw-") as temporary:
        folder = await asyncio.wait_for(
            downloader.download_chapter(manga_id, chapter_id, temporary), timeout=300
        )
        if not folder:
            raise HTTPException(status_code=502, detail="Source tidak mengembalikan gambar chapter.")
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as output:
            for path in sorted(Path(folder).rglob("*")):
                if path.is_file():
                    output.write(path, path.relative_to(folder).as_posix())
        safe_manga = "".join(c if c.isalnum() or c in "-_" else "-" for c in manga_id).strip("-")
        safe_chapter = "".join(c if c.isalnum() or c in "-_." else "-" for c in chapter_id).strip("-")
        return f"{source}-{safe_manga}-{safe_chapter}.zip", archive.getvalue()


@router.get("/translator/raw/{source}/{manga_id}/chapters")
async def translator_raw_chapters(source: str, manga_id: str, user=Depends(admin_user)):
    downloader = _raw_downloader(source)
    try:
        return await asyncio.wait_for(downloader.get_chapter_list(manga_id), timeout=30)
    except asyncio.TimeoutError as error:
        raise HTTPException(status_code=504, detail="Source terlalu lama memuat chapter.") from error


@router.post("/translator/raw/prepare")
async def translator_raw_prepare(request: Request, user=Depends(admin_user)):
    payload=await request.json()
    source=str(payload.get("source") or "").strip().lower()
    manga_id=str(payload.get("manga_id") or "").strip()
    chapter_id=str(payload.get("chapter_id") or "").strip()
    if not manga_id or not chapter_id or len(manga_id)>250 or len(chapter_id)>250:
        raise HTTPException(400,"Judul dan chapter RAW wajib dipilih.")
    downloader=_raw_downloader(source)
    return raw_exports.start({"source":source,"manga_id":manga_id,"chapter_id":chapter_id},user["id"],downloader)


@router.get("/translator/raw/prepared/{token}")
async def translator_raw_prepared(token: str, user=Depends(admin_user)):
    _,state=raw_exports.read_state(token,user["id"])
    return raw_exports.public_state(state)


@router.post("/translator/raw/download")
async def translator_raw_download(request: Request, user=Depends(admin_user)):
    payload=await request.json()
    if payload.get("prepared_token"):
        path,state=raw_exports.download_path(str(payload["prepared_token"]),user["id"],str(payload.get("raw_mode") or "original"))
        mode=str(payload.get('raw_mode') or 'original')
        return FileResponse(path,filename=raw_exports.filename(state,mode),media_type="application/zip")
    filename, content = await _raw_zip(payload)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/translator/raw/import")
async def translator_raw_import(request: Request, user=Depends(admin_user)):
    payload = await request.json()
    try:
        min_y=max(0,int(payload.get("min_y") or 0))
    except (ValueError,TypeError):
        raise HTTPException(400,"Abaikan area atas harus berupa angka.")
    prepared_upload=None
    if payload.get("prepared_token"):
        path,state=raw_exports.download_path(str(payload['prepared_token']),user['id'],str(payload.get('raw_mode') or 'original'))
        mode=str(payload.get('raw_mode') or 'original')
        if state[mode]['count']>60 or path.stat().st_size>100*1024*1024:
            raise HTTPException(413,"Paket terjemahan dibatasi 60 halaman / 100 MB. Pilih format lain atau unduh ZIP untuk dibagi.")
        filename=raw_exports.filename(state,mode)
        prepared_upload=open(path,'rb');content=prepared_upload
    else:
        filename, content = await _raw_zip(payload)
    headers = {"Authorization": f"Bearer {TRANSLATOR_API_TOKEN}"} if TRANSLATOR_API_TOKEN else {}
    fields = {
        "comicId": str(payload.get("comic_id") or ""),
        "chapterId": str(payload.get("target_chapter_id") or ""),
        "title": str(payload.get("title") or ""),
        "chapter": str(payload.get("chapter") or "1"),
        "minY": str(min_y),
        "rawMode": str(payload.get("raw_mode") or "auto"),
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=300)) as client:
            upstream = await client.post(
                f"{TRANSLATOR_API_URL}/api/jobs",
                headers=headers,
                data=fields,
                files={"files": (filename, content, "application/zip")},
            )
    finally:
        if prepared_upload is not None: prepared_upload.close()
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


@router.api_route(
    "/translator/{upstream_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def translator_proxy(upstream_path: str, request: Request, user=Depends(admin_user)):
    """Authenticated dashboard bridge to the private translator API."""
    headers: dict[str, str] = {}
    if TRANSLATOR_API_TOKEN:
        headers["Authorization"] = f"Bearer {TRANSLATOR_API_TOKEN}"
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    try:
        body = await request.body()
        target_path = "/api/system/status" if upstream_path == "status" else f"/api/{upstream_path}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=300)) as client:
            upstream = await client.request(
                request.method,
                f"{TRANSLATOR_API_URL}{target_path}",
                params=request.query_params,
                headers=headers,
                content=body,
            )
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=504, detail="Translator tidak merespons tepat waktu.") from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="Service translator sedang tidak tersedia.") from error

    response_headers = {}
    for name in ("content-disposition", "cache-control"):
        value = upstream.headers.get(name)
        if value:
            response_headers[name] = value
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers=response_headers,
    )


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
