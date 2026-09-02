import asyncio
import aiohttp
import os
import re
import secrets
import shutil
import time
from typing import Awaitable, Callable, Optional

import discord

from helpers.utils import is_admin, is_staff
from chapter_utils import chapters_from_assignment, normalize_chapter
from raw_downloader import get_downloader
from raw_downloader.resolver import (
    SOURCE_ORDER,
    deduplicate_results,
    filter_allowed_chapters,
    resolve_assignment_raw,
)
from raw_downloader.retry import RETRYABLE_STATUSES
from raw_downloader.image_processing import convert_images_to_webp, merge_images_lossless, resize_for_editor

RAW_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "raw")
FILEBIN_BASE_URL = "https://filebin.net"
FILEBIN_UPLOAD_CONCURRENCY = 5
FILEBIN_UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=90, sock_connect=15, sock_read=60)


def cleanup_old_raw_files(max_age_hours=24):
    if not os.path.isdir(RAW_ROOT):
        return
    cutoff = time.time() - max_age_hours * 3600
    for root, directories, files in os.walk(RAW_ROOT, topdown=False):
        for filename in files:
            path = os.path.join(root, filename)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
        for directory in directories:
            path = os.path.join(root, directory)
            try:
                if not os.listdir(path):
                    os.rmdir(path)
            except OSError:
                pass


def raw_mode_label(raw_mode: str) -> str:
    return "RAW Original" if raw_mode == "original" else "Aman untuk Editor (maks. 8192 px)"


def raw_pack_label(raw_pack_mode: str) -> str:
    if raw_pack_mode == "merge_16000":
        return "Gabung WebP HD (maks. 16.000 px)"
    if raw_pack_mode == "webp_hd":
        return "WebP HD (ukuran lebih kecil)"
    return "Normal (per halaman)"


async def resolve_pinned_raw(source: str, manga_id: str, allowed_chapters, timeout: int = 12):
    """Resolve chapters only from the source explicitly selected by the administrator."""
    source = str(source or "").casefold()
    if source not in SOURCE_ORDER or not manga_id:
        return {"status": "invalid_source", "source": source}
    try:
        chapters = await asyncio.wait_for(
            get_downloader(source).get_chapter_list(str(manga_id)), timeout=timeout
        )
    except asyncio.TimeoutError:
        return {"status": "timeout", "source": source}
    except Exception:
        return {"status": "not_found", "source": source}
    matched, missing = filter_allowed_chapters(chapters or [], allowed_chapters)
    if not matched:
        return {"status": "chapters_missing", "source": source, "missing": missing}
    return {
        "status": "resolved",
        "source": source,
        "manga": {"id": str(manga_id), "title": "Source pilihan admin"},
        "chapters": matched,
        "missing": missing,
        "fallbacks": [],
    }


async def upload_to_filebin(bin_id, file_path, remote_filename=None, session=None):
    """Upload one file into a shared Filebin bin."""
    filename = remote_filename or os.path.basename(file_path)
    timeout = FILEBIN_UPLOAD_TIMEOUT
    owned_session = session is None
    client = session or aiohttp.ClientSession(timeout=timeout)
    try:
        for attempt in range(1, 3):
            try:
                with open(file_path, "rb") as upload_file:
                    async with client.post(
                        f"{FILEBIN_BASE_URL}/{bin_id}/{filename}",
                        data=upload_file,
                        headers={
                            "Content-Type": "application/octet-stream",
                            "Accept": "application/json",
                            "Content-Length": str(os.path.getsize(file_path)),
                        },
                    ) as response:
                        if response.status == 201:
                            try:
                                payload = await response.json()
                            except (aiohttp.ContentTypeError, ValueError):
                                payload = {}
                            uploaded_name = str((payload.get("file") or {}).get("filename") or "")
                            if uploaded_name == filename:
                                return True
                            reason = "respons sukses tidak memuat metadata file yang benar"
                        elif response.status == 200:
                            reason = "HTTP 200 non-upload (kemungkinan halaman verifikasi)"
                        elif response.status not in RETRYABLE_STATUSES:
                            print(f"Filebin upload {filename} failed permanently: HTTP {response.status}")
                            return False
                        else:
                            reason = f"HTTP {response.status}"
            except (aiohttp.ClientError, TimeoutError, OSError) as error:
                reason = type(error).__name__
            print(f"Filebin upload {filename} attempt {attempt}/2 failed: {reason}")
            if attempt < 2:
                await asyncio.sleep(0.75 * attempt)
        return False
    finally:
        if owned_session:
            await client.close()


async def verify_filebin(bin_id, expected_filenames, session):
    """Never publish a Filebin URL until every expected page is listed."""
    expected = set(expected_filenames)
    for attempt in range(1, 4):
        try:
            async with session.get(
                f"{FILEBIN_BASE_URL}/{bin_id}",
                headers={"Accept": "application/json"},
            ) as response:
                if response.status == 200:
                    payload = await response.json()
                    actual = {str(item.get("filename")) for item in payload.get("files", [])}
                    if actual == expected:
                        return True
        except (aiohttp.ClientError, aiohttp.ContentTypeError, TimeoutError, ValueError):
            pass
        if attempt < 3:
            await asyncio.sleep(attempt)
    return False


async def create_filebin_download(
    source,
    manga_id,
    chapter_ids,
    fallbacks=None,
    progress: Optional[Callable[[str], Awaitable[None]]] = None,
    raw_mode: str = "editor_safe",
    raw_pack_mode: str = "normal",
):
    """Upload images directly so Filebin's download ZIP has no nested archive/folders."""
    cleanup_old_raw_files()
    os.makedirs(RAW_ROOT, exist_ok=True)
    completed, temporary_directories = [], []
    bin_id = secrets.token_urlsafe(12).replace("_", "").replace("-", "").lower()
    request_root = os.path.join(RAW_ROOT, f"request-{bin_id}")
    os.makedirs(request_root, exist_ok=True)
    filebin_session = aiohttp.ClientSession(timeout=FILEBIN_UPLOAD_TIMEOUT)
    try:
        async def notify(message: str) -> None:
            if progress:
                await progress(message)

        candidates = [{"source": source, "manga_id": manga_id}] + list(fallbacks or [])
        selected_source = source
        chapter_directories = []
        for candidate in candidates:
            downloader = get_downloader(candidate["source"])
            attempt_root = os.path.join(request_root, candidate["source"])
            current = []
            for chapter_index, chapter_id in enumerate(chapter_ids, 1):
                await notify(f"Mengunduh chapter {chapter_index}/{len(chapter_ids)} dari {candidate['source'].title()}…")
                if candidate["source"].casefold() == "evascan":
                    async def evascan_progress(done: int, total: int, chapter=chapter_id):
                        await notify(f"Mengunduh Evascan chapter {chapter}: **{done}/{total} halaman**")
                    result = await downloader.download_chapter(
                        candidate["manga_id"], chapter_id, attempt_root, progress=evascan_progress
                    )
                else:
                    result = await downloader.download_chapter(
                        candidate["manga_id"], chapter_id, attempt_root
                    )
                if not result:
                    break
                current.append((chapter_id, result))
            if len(current) == len(chapter_ids):
                selected_source = candidate["source"]
                chapter_directories = current
                temporary_directories.extend(path for _, path in current)
                break
            shutil.rmtree(attempt_root, ignore_errors=True)

        if not chapter_directories:
            return None, [], source

        upload_entries = []
        for chapter_id, result in chapter_directories:
            safe_chapter = re.sub(r"[^a-zA-Z0-9_-]+", "-", chapter_id).strip("-")[:30] or "chapter"
            image_number = 0
            image_files = []
            for root, directories, files in os.walk(result):
                directories.sort()
                for filename in files:
                    image_files.append(os.path.join(root, filename))
            for image_path in sorted(image_files, key=lambda path: os.path.relpath(path, result)):
                image_number += 1
                extension = os.path.splitext(image_path)[1] or ".jpg"
                remote_name = f"ch-{safe_chapter}_{image_number:03d}{extension}"
                upload_entries.append((chapter_id, image_path, remote_name))

        if not upload_entries:
            return None, [], selected_source
        if raw_pack_mode == "merge_16000":
            await notify(f"Menggabungkan **{len(upload_entries)} halaman** menjadi WebP HD hingga 16.000 px...")
            merged_entries = []
            merged_root = os.path.join(request_root, "merged")
            for chapter_id in dict.fromkeys(item[0] for item in upload_entries):
                chapter_paths = [path for item_chapter, path, _ in upload_entries if item_chapter == chapter_id]
                safe_chapter = re.sub(r"[^a-zA-Z0-9_-]+", "-", chapter_id).strip("-")[:30] or "chapter"
                merged_paths = await asyncio.to_thread(
                    merge_images_lossless, chapter_paths, merged_root, f"ch-{safe_chapter}"
                )
                merged_entries.extend(
                    (chapter_id, path, os.path.basename(path)) for path in merged_paths
                )
            upload_entries = merged_entries
            await notify(f"Penggabungan selesai: **{len(upload_entries)} WebP kualitas 95** siap diunggah.")
        resized_images = 0
        for index, (_, image_path, _) in enumerate(upload_entries, 1):
            if raw_pack_mode != "merge_16000" and raw_mode != "original":
                resize_result = await asyncio.to_thread(resize_for_editor, image_path)
                resized_images += int(resize_result.resized)
            if index == len(upload_entries) or index % 3 == 0:
                await notify(f"Memproses gambar agar aman untuk editor: **{index}/{len(upload_entries)}**")

        if raw_pack_mode == "webp_hd":
            await notify(f"Mengonversi **{len(upload_entries)} gambar** ke WebP HD...")
            webp_entries = []
            webp_root = os.path.join(request_root, "webp-hd")
            for chapter_id in dict.fromkeys(item[0] for item in upload_entries):
                entries = [item for item in upload_entries if item[0] == chapter_id]
                safe_chapter = re.sub(r"[^a-zA-Z0-9_-]+", "-", chapter_id).strip("-")[:30] or "chapter"
                converted = await asyncio.to_thread(
                    convert_images_to_webp,
                    [path for _, path, _ in entries],
                    os.path.join(webp_root, safe_chapter),
                    95,
                )
                webp_entries.extend(
                    (chapter_id, path, f"ch-{safe_chapter}_{index:03d}.webp")
                    for index, path in enumerate(converted, 1)
                )
            upload_entries = webp_entries
            await notify(f"Konversi selesai: **{len(upload_entries)} WebP HD** siap diunggah.")

        upload_semaphore = asyncio.Semaphore(FILEBIN_UPLOAD_CONCURRENCY)
        uploaded_count = 0
        upload_lock = asyncio.Lock()

        async def upload_entry(chapter_id: str, image_path: str, remote_name: str) -> tuple[str, str, bool]:
            nonlocal uploaded_count
            async with upload_semaphore:
                ok = await upload_to_filebin(bin_id, image_path, remote_name, filebin_session)
            async with upload_lock:
                uploaded_count += 1
                if uploaded_count == len(upload_entries) or uploaded_count % 2 == 0:
                    await notify(f"Mengunggah ke Filebin: **{uploaded_count}/{len(upload_entries)} gambar**")
            return chapter_id, remote_name, ok

        upload_results = await asyncio.gather(*(upload_entry(*entry) for entry in upload_entries))
        failed = [remote_name for _, remote_name, ok in upload_results if not ok]
        if failed:
            print(f"Filebin upload failed for {len(failed)} image(s) in {bin_id}")
            return None, [], selected_source
        completed = list(dict.fromkeys(chapter_id for chapter_id, _, _ in upload_entries))
        expected_filenames = [remote_name for _, _, remote_name in upload_entries]
        await notify(f"Memverifikasi **{len(expected_filenames)} gambar** di Filebin…")
        if not await verify_filebin(bin_id, expected_filenames, filebin_session):
            print(
                f"Filebin verification failed for {bin_id}: "
                f"expected {len(expected_filenames)} file(s)"
            )
            return None, [], selected_source
        if resized_images:
            print(f"RAW editor-safe resize: {resized_images} image(s) limited to 8192px height")
        return f"{FILEBIN_BASE_URL}/{bin_id}", completed, selected_source
    finally:
        await filebin_session.close()
        for path in temporary_directories:
            shutil.rmtree(path, ignore_errors=True)
        shutil.rmtree(request_root, ignore_errors=True)


class RawSearchModal(discord.ui.Modal, title="Cari dan Download RAW"):
    query = discord.ui.TextInput(label="Judul Komik", placeholder="Contoh: Solo Leveling", min_length=2, max_length=100)
    raw_mode = discord.ui.TextInput(label="Mode RAW", placeholder="editor_safe atau original", default="editor_safe", required=False, max_length=20)

    def __init__(self, initial_query: str = ""):
        super().__init__()
        if initial_query:
            self.query.default = initial_query[:100]

    async def on_submit(self, interaction):
        if not (is_staff(interaction.user) or is_admin(interaction.user)):
            return await interaction.response.send_message("Hanya staff atau administrator yang dapat download RAW.")
        mode = self.raw_mode.value.strip().casefold() or "editor_safe"
        if mode not in {"editor_safe", "original"}:
            return await interaction.response.send_message("Mode RAW hanya `editor_safe` atau `original`.", ephemeral=True)
        await interaction.response.defer()
        searches = await asyncio.gather(
            *(get_downloader(source).search_manga(self.query.value) for source in SOURCE_ORDER),
            return_exceptions=True,
        )
        results = {
            source: result[:12] if isinstance(result, list) else []
            for source, result in zip(SOURCE_ORDER, searches)
        }
        combined = deduplicate_results(results)
        if not combined:
            return await interaction.followup.send("Komik tidak ditemukan di Asura, Omega, maupun Doujiva. Coba judul yang lebih singkat.")
        embed = discord.Embed(title="Hasil Pencarian RAW", description=f"Hasil **{self.query.value}** sudah digabung tanpa judul duplikat. Pilih komik yang benar.", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=RawSearchView("auto", combined, raw_mode=mode))


class RawAssignmentView(discord.ui.View):
    """Start RAW navigation from one of the staff member's claimed projects."""

    def __init__(self, assignments):
        super().__init__(timeout=300)
        self.add_item(RawAssignmentSelect(assignments[:25]))


class RawAssignmentSelect(discord.ui.Select):
    def __init__(self, assignments):
        self.assignments = {str(item["id"]): item for item in assignments}
        options = [
            discord.SelectOption(
                label=f"#{item['id']} {item['manga']}"[:100],
                value=str(item["id"]),
                description=f"Chapter {item['chapter']} â€¢ {item['role']}"[:100],
            )
            for item in assignments
        ]
        super().__init__(placeholder="Pilih proyek yang sedang dikerjakan", options=options)

    async def callback(self, interaction):
        assignment = self.assignments[self.values[0]]
        if assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message("Tugas ini bukan milikmu.")
        pinned_source = assignment.get("raw_source")
        pinned_id = assignment.get("raw_manga_id")
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Mencari RAW Proyekâ€¦",
                description=(
                    f"Proyek: **{assignment['manga']}**\n"
                    f"Target chapter: **{assignment['chapter']}**\n\n"
                    + (f"Menggunakan source pilihan admin: **{pinned_source.title()}**."
                     if pinned_source and pinned_id else
                     "Mencari otomatis di seluruh source RAW.")
                ),
                color=discord.Color.gold(),
            ),
            view=None,
        )
        allowed = chapters_from_assignment(assignment)

        async def show_progress(message):
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="Mendeteksi RAW Otomatis...",
                    description=(
                        f"Proyek: **{assignment['manga']}**\n"
                        f"Target chapter: **{assignment['chapter']}**\n\n{message}"
                    ),
                    color=discord.Color.gold(),
                ),
                view=None,
            )

        if pinned_source and pinned_id:
            await show_progress(f"Membuka source pilihan admin: **{pinned_source.title()}**.")
            result = await resolve_pinned_raw(pinned_source, pinned_id, allowed)
            if result["status"] == "resolved":
                result["manga"]["title"] = assignment["manga"]
        else:
            result = await resolve_assignment_raw(
                assignment["manga"],
                allowed,
                {source: get_downloader(source) for source in SOURCE_ORDER},
                progress=show_progress,
            )
        if result["status"] == "not_found":
            return await interaction.edit_original_response(
                embed=discord.Embed(
                    title="RAW Tidak Ditemukan",
                    description=(
                        f"RAW **{assignment['manga']}** tidak tersedia di source yang ditetapkan"
                        f"{f' ({pinned_source.title()})' if pinned_source else ''}. "
                        "Hubungi admin untuk mengganti source tugas."
                    ),
                    color=discord.Color.red(),
                )
            )
        if result["status"] == "timeout":
            return await interaction.edit_original_response(embed=discord.Embed(
                title="Pencarian RAW Melewati Batas Waktu",
                description=(f"Source **{pinned_source.title()}** belum merespons dalam 12 detik; coba lagi nanti."
                             if pinned_source else
                             "Sumber RAW belum merespons dalam 12 detik. Bot sudah mencoba ulang otomatis; coba lagi nanti."),
                color=discord.Color.red(),
            ))
        if result["status"] == "chapters_missing":
            return await interaction.edit_original_response(embed=discord.Embed(
                title="Chapter Tugas Belum Tersedia",
                description=(f"Chapter **{', '.join(allowed)}** belum tersedia di source "
                             f"**{pinned_source.title()}**. Hubungi admin untuk mengganti source tugas."
                             if pinned_source else
                             f"Judul ditemukan, tetapi chapter **{', '.join(allowed)}** belum tersedia di seluruh source."),
                color=discord.Color.orange(),
            ))
        if result["status"] == "resolved":
            source = result["source"]
            available = [normalize_chapter(item["id"]) for item in result["chapters"]]
            description = (
                f"**{result['manga'].get('title')}** • Sumber terpilih: **{source.title()}**\n"
                f"Chapter tersedia: **{', '.join(available)}**."
            )
            if result["missing"]:
                description += f"\nBelum tersedia: **{', '.join(result['missing'])}**."
            return await interaction.edit_original_response(
                embed=discord.Embed(title="RAW Tugas Ditemukan", description=description, color=discord.Color.green()),
                view=RawChapterView(
                    source,
                    str(result["manga"]["id"]),
                    result["chapters"],
                    restricted=True,
                    fallbacks=[
                        {
                            "source": item["source"],
                            "manga_id": str(item["manga"]["id"]),
                        }
                        for item in result.get("fallbacks", [])
                    ],
                    raw_mode=assignment.get("raw_mode", "editor_safe"),
                    raw_pack_mode=assignment.get("raw_pack_mode", "normal"),
                ),
            )

        combined = result["combined"]
        embed = discord.Embed(
            title="Pilih Komik yang Sesuai",
            description=(
                f"Proyek tugas: **{assignment['manga']} â€” Ch. {assignment['chapter']}**\n"
                "Ada beberapa judul yang mirip, jadi bot perlu konfirmasi satu kali."
            ),
            color=discord.Color.blue(),
        )
        await interaction.edit_original_response(
            embed=embed,
            view=RawSearchView(
                "auto", combined,
                allowed_chapters=allowed,
                assignment_id=assignment["id"],
                raw_mode=assignment.get("raw_mode", "editor_safe"),
                raw_pack_mode=assignment.get("raw_pack_mode", "normal"),
            ),
        )


class RawSearchView(discord.ui.View):
    def __init__(self, source, results, allowed_chapters=None, assignment_id=None, raw_mode="editor_safe", raw_pack_mode="normal"):
        super().__init__(timeout=300)
        normalized = [{**manga, "_source": manga.get("_source", source)} for manga in results[:25]]
        self.add_item(RawMangaSelect(normalized, allowed_chapters, assignment_id, raw_mode, raw_pack_mode))


class RawMangaSelect(discord.ui.Select):
    def __init__(self, results, allowed_chapters=None, assignment_id=None, raw_mode="editor_safe", raw_pack_mode="normal"):
        self.results = results
        self.allowed_chapters = allowed_chapters
        self.assignment_id = assignment_id
        self.raw_mode = raw_mode
        self.raw_pack_mode = raw_pack_mode
        options = [
            discord.SelectOption(
                label=str(manga.get("title", "Tanpa judul"))[:100],
                value=str(index),
                description=(
                    f"{' / '.join(source.title() for source in manga.get('_sources', [manga['_source']]))} "
                    f"• {manga.get('status', 'status tidak diketahui')}"
                )[:100],
            )
            for index, manga in enumerate(results)
        ]
        super().__init__(placeholder="Pilih komik", options=options)

    async def callback(self, interaction):
        if not (is_staff(interaction.user) or is_admin(interaction.user)):
            return await interaction.response.send_message("Hanya staff atau administrator yang dapat memakai RAW navigator.")
        manga = self.results[int(self.values[0])]
        source, manga_id = manga["_source"], str(manga["id"])
        await interaction.response.edit_message(embed=discord.Embed(title="Mengambil Daftar Chapterâ€¦", description=f"**{manga.get('title')}** dari sumber terbaik", color=discord.Color.gold()), view=None)
        fallback_candidates = []
        if self.allowed_chapters is not None and manga.get("_candidates"):
            async def inspect(candidate_source, candidate):
                candidate_chapters = await get_downloader(candidate_source).get_chapter_list(
                    str(candidate["id"])
                )
                filtered, missing_items = filter_allowed_chapters(
                    candidate_chapters, self.allowed_chapters
                )
                return {
                    "source": candidate_source,
                    "manga": candidate,
                    "chapters": filtered,
                    "missing": missing_items,
                }

            inspected = await asyncio.gather(*(
                inspect(candidate_source, candidate)
                for candidate_source, candidate in manga["_candidates"].items()
            ))
            inspected.sort(
                key=lambda item: (
                    -len(item["chapters"]),
                    SOURCE_ORDER.index(item["source"]),
                )
            )
            best = inspected[0]
            source, manga_id, chapters = (
                best["source"],
                str(best["manga"]["id"]),
                best["chapters"],
            )
            fallback_candidates = [
                {
                    "source": item["source"],
                    "manga_id": str(item["manga"]["id"]),
                }
                for item in inspected[1:]
                if not item["missing"]
            ]
        else:
            chapters = await get_downloader(source).get_chapter_list(manga_id)
        if not chapters:
            return await interaction.edit_original_response(embed=discord.Embed(title="Chapter Tidak Ditemukan", description="Sumber sedang bermasalah atau chapter belum tersedia.", color=discord.Color.red()))
        missing = []
        if self.allowed_chapters is not None:
            filtered, missing = filter_allowed_chapters(chapters, self.allowed_chapters)
            if not filtered:
                return await interaction.edit_original_response(embed=discord.Embed(
                    title="Chapter Tugas Belum Tersedia",
                    description=(
                        f"Tidak ada chapter tugas **{', '.join(self.allowed_chapters)}** pada {source.title()}.\n"
                        "Pilih hasil manga atau sumber lain. Bot tidak akan menampilkan chapter di luar tugas."
                    ),
                    color=discord.Color.orange(),
                ))
            chapters = filtered
        description = f"**{manga.get('title')}** • {source.title()}\n"
        if self.allowed_chapters is None:
            description += "Mode administrator: pilih maksimal 10 chapter atau Download Terbaru."
        else:
            description += f"Chapter tugas tersedia: **{', '.join(normalize_chapter(ch['id']) for ch in chapters)}**."
            if missing:
                description += f"\nBelum tersedia: **{', '.join(missing)}**."
        embed = discord.Embed(title="Pilih Chapter RAW", description=description, color=discord.Color.blue())
        await interaction.edit_original_response(
            embed=embed,
            view=RawChapterView(
                source,
                manga_id,
                chapters[:25],
                restricted=self.allowed_chapters is not None,
                fallbacks=fallback_candidates,
                raw_mode=self.raw_mode,
                raw_pack_mode=self.raw_pack_mode,
            ),
        )


class RawChapterView(discord.ui.View):
    def __init__(self, source, manga_id, chapters, restricted=False, fallbacks=None, raw_mode="editor_safe", raw_pack_mode="normal"):
        super().__init__(timeout=300)
        self.source, self.manga_id, self.chapters, self.restricted = source, manga_id, chapters, restricted
        self.fallbacks = fallbacks or []
        self.raw_mode = raw_mode
        self.raw_pack_mode = raw_pack_mode
        self.add_item(RawChapterSelect(self, chapters))

    @discord.ui.button(label="Download Chapter Tugas", style=discord.ButtonStyle.success, row=1)
    async def latest_button(self, interaction, _button):
        chapter_ids = [str(item["id"]) for item in self.chapters] if self.restricted else [str(self.chapters[0]["id"])]
        await download_chapters(
            interaction, self.source, self.manga_id, chapter_ids, self.fallbacks, self.raw_mode, self.raw_pack_mode
        )


class RawChapterSelect(discord.ui.Select):
    def __init__(self, parent_view, chapters):
        self.parent_view = parent_view
        options = [discord.SelectOption(label=str(chapter.get("title", chapter.get("id")))[:100], value=str(chapter.get("id")), description=str(chapter.get("date") or "Pilih untuk download")[:100]) for chapter in chapters]
        placeholder = "Pilih chapter tugas" if parent_view.restricted else "Pilih chapter (maksimal 10)"
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=min(10, len(options)), row=0)

    async def callback(self, interaction):
        await download_chapters(
            interaction,
            self.parent_view.source,
            self.parent_view.manga_id,
            self.values,
            self.parent_view.fallbacks, self.parent_view.raw_mode, self.parent_view.raw_pack_mode,
        )


async def download_chapters(interaction, source, manga_id, chapter_ids, fallbacks=None, raw_mode="editor_safe", raw_pack_mode="normal"):
    if not (is_staff(interaction.user) or is_admin(interaction.user)):
        return await interaction.response.send_message("Hanya staff atau administrator yang dapat download RAW.")
    await interaction.response.edit_message(
        embed=discord.Embed(
            title="Menyiapkan RAW...",
            description=(
                f"Sumber: **{source.title()}**\nChapter: **{', '.join(chapter_ids)}**\n\n"
                f"Mode: **{raw_mode_label(raw_mode)}**\nPaket: **{raw_pack_label(raw_pack_mode)}**\nMengunduh gambar lalu mengunggahnya ke Filebin."
            ),
            color=discord.Color.gold(),
        ),
        view=None,
    )
    async def progress(message: str):
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="Menyiapkan RAW…",
                description=f"Sumber: **{source.title()}**\nChapter: **{', '.join(chapter_ids)}**\n\n{message}",
                color=discord.Color.gold(),
            )
        )

    filebin_url, completed, final_source = await create_filebin_download(
        source, manga_id, chapter_ids, fallbacks, progress=progress, raw_mode=raw_mode,
        raw_pack_mode=raw_pack_mode,
    )
    if not filebin_url:
        return await interaction.edit_original_response(embed=discord.Embed(title="Upload Filebin Gagal", description="RAW tidak tersedia atau Filebin sedang menolak upload. File lokal sudah dibersihkan; coba lagi nanti.", color=discord.Color.red()))
    embed = discord.Embed(title="RAW Siap Diunduh", description=f"Gambar dari **{len(completed)} chapter** sudah tersedia langsung di Filebin tanpa ZIP bertingkat.", color=discord.Color.green())
    embed.add_field(name="Sumber Final", value=final_source.title(), inline=False)
    embed.add_field(name="Mode RAW", value=raw_mode_label(raw_mode), inline=False)
    embed.add_field(name="Paket RAW", value=raw_pack_label(raw_pack_mode), inline=False)
    embed.add_field(name="Chapter", value=", ".join(completed), inline=False)
    embed.add_field(name="Link Download", value=f"[Buka Filebin]({filebin_url})", inline=False)
    embed.add_field(name="Cara Download", value="Buka Filebin lalu pilih **Download files**. ZIP hasil download langsung berisi `ch-1_001.jpg`, `ch-1_002.jpg`, dan seterusnya.", inline=False)
    embed.add_field(name="Penyimpanan", value="File lokal VPS langsung dihapus. Link Filebin berlaku sementara.", inline=False)
    await interaction.edit_original_response(embed=embed)
