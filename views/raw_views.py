import asyncio
import aiohttp
import os
import re
import secrets
import shutil
import time

import discord

from helpers.utils import is_staff
from chapter_utils import chapters_from_assignment, normalize_chapter
from raw_downloader import get_downloader
from raw_downloader.resolver import (
    SOURCE_ORDER,
    deduplicate_results,
    filter_allowed_chapters,
    resolve_assignment_raw,
)
from raw_downloader.retry import RETRYABLE_STATUSES
from raw_downloader.image_processing import resize_for_editor

RAW_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "raw")
FILEBIN_BASE_URL = "https://filebin.net"


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


async def upload_to_filebin(bin_id, file_path, remote_filename=None):
    """Upload one file into a shared Filebin bin."""
    filename = remote_filename or os.path.basename(file_path)
    timeout = aiohttp.ClientTimeout(total=900)
    for attempt in range(1, 4):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                with open(file_path, "rb") as upload_file:
                    async with session.post(
                        f"{FILEBIN_BASE_URL}/{bin_id}/{filename}",
                        data=upload_file,
                        headers={"Content-Type": "application/octet-stream"},
                    ) as response:
                        if response.status in (200, 201):
                            return True
                        if response.status not in RETRYABLE_STATUSES:
                            print(f"Filebin upload {filename} failed permanently: HTTP {response.status}")
                            return False
                        reason = f"HTTP {response.status}"
        except (aiohttp.ClientError, TimeoutError, OSError) as error:
            reason = type(error).__name__
        print(f"Filebin upload {filename} attempt {attempt}/3 failed: {reason}")
        if attempt < 3:
            await asyncio.sleep(0.75 * attempt)
    return False


async def create_filebin_download(source, manga_id, chapter_ids, fallbacks=None):
    """Upload images directly so Filebin's download ZIP has no nested archive/folders."""
    cleanup_old_raw_files()
    os.makedirs(RAW_ROOT, exist_ok=True)
    completed, temporary_directories = [], []
    bin_id = secrets.token_urlsafe(12).replace("_", "").replace("-", "").lower()
    request_root = os.path.join(RAW_ROOT, f"request-{bin_id}")
    os.makedirs(request_root, exist_ok=True)
    try:
        candidates = [{"source": source, "manga_id": manga_id}] + list(fallbacks or [])
        selected_source = source
        chapter_directories = []
        for candidate in candidates:
            downloader = get_downloader(candidate["source"])
            attempt_root = os.path.join(request_root, candidate["source"])
            current = []
            for chapter_id in chapter_ids:
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

        resized_images = 0
        for chapter_id, result in chapter_directories:
            safe_chapter = re.sub(r"[^a-zA-Z0-9_-]+", "-", chapter_id).strip("-")[:30] or "chapter"
            image_number = 0
            uploaded = True
            image_files = []
            for root, directories, files in os.walk(result):
                directories.sort()
                for filename in files:
                    image_files.append(os.path.join(root, filename))
            for image_path in sorted(image_files, key=lambda path: os.path.relpath(path, result)):
                resize_result = await asyncio.to_thread(resize_for_editor, image_path)
                resized_images += int(resize_result.resized)
                upload_path = resize_result.output_path or image_path
                image_number += 1
                extension = os.path.splitext(upload_path)[1] or ".png"
                remote_name = f"ch-{safe_chapter}_{image_number:03d}{extension}"
                if not await upload_to_filebin(bin_id, upload_path, remote_name):
                    uploaded = False
                    break
            if uploaded and image_number:
                completed.append(chapter_id)
            else:
                shutil.rmtree(result, ignore_errors=True)
        if not completed:
            return None, [], selected_source
        if resized_images:
            print(f"RAW editor-safe resize: {resized_images} image(s) limited to 8192px height")
        return f"{FILEBIN_BASE_URL}/{bin_id}", completed, selected_source
    finally:
        for path in temporary_directories:
            shutil.rmtree(path, ignore_errors=True)
        shutil.rmtree(request_root, ignore_errors=True)


class RawSearchModal(discord.ui.Modal, title="Cari dan Download RAW"):
    query = discord.ui.TextInput(label="Judul Komik", placeholder="Contoh: Solo Leveling", min_length=2, max_length=100)

    async def on_submit(self, interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya staff yang dapat download RAW.")
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
        await interaction.followup.send(embed=embed, view=RawSearchView("auto", combined))


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
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Mencari RAW Proyekâ€¦",
                description=(
                    f"Proyek: **{assignment['manga']}**\n"
                    f"Target chapter: **{assignment['chapter']}**\n\n"
                    "Mencari otomatis di Asura, Omega, dan Doujiva."
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
                        f"Tidak ada hasil untuk **{assignment['manga']}** di Asura, Omega, maupun Doujiva. "
                        "Hubungi admin jika judul proyek perlu disesuaikan."
                    ),
                    color=discord.Color.red(),
                )
            )
        if result["status"] == "timeout":
            return await interaction.edit_original_response(embed=discord.Embed(
                title="Pencarian RAW Melewati Batas Waktu",
                description="Sumber RAW belum merespons dalam 12 detik. Bot sudah mencoba ulang otomatis; coba lagi nanti.",
                color=discord.Color.red(),
            ))
        if result["status"] == "chapters_missing":
            return await interaction.edit_original_response(embed=discord.Embed(
                title="Chapter Tugas Belum Tersedia",
                description=f"Judul ditemukan, tetapi chapter **{', '.join(allowed)}** belum tersedia di Asura, Omega, maupun Doujiva.",
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
            ),
        )


class RawSearchView(discord.ui.View):
    def __init__(self, source, results, allowed_chapters=None, assignment_id=None):
        super().__init__(timeout=300)
        normalized = [{**manga, "_source": manga.get("_source", source)} for manga in results[:25]]
        self.add_item(RawMangaSelect(normalized, allowed_chapters, assignment_id))


class RawMangaSelect(discord.ui.Select):
    def __init__(self, results, allowed_chapters=None, assignment_id=None):
        self.results = results
        self.allowed_chapters = allowed_chapters
        self.assignment_id = assignment_id
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
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya staff yang dapat memakai RAW navigator.")
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
            ),
        )


class RawChapterView(discord.ui.View):
    def __init__(self, source, manga_id, chapters, restricted=False, fallbacks=None):
        super().__init__(timeout=300)
        self.source, self.manga_id, self.chapters, self.restricted = source, manga_id, chapters, restricted
        self.fallbacks = fallbacks or []
        self.add_item(RawChapterSelect(self, chapters))

    @discord.ui.button(label="Download Chapter Tugas", style=discord.ButtonStyle.success, row=1)
    async def latest_button(self, interaction, _button):
        chapter_ids = [str(item["id"]) for item in self.chapters] if self.restricted else [str(self.chapters[0]["id"])]
        await download_chapters(
            interaction, self.source, self.manga_id, chapter_ids, self.fallbacks
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
            self.parent_view.fallbacks,
        )


async def download_chapters(interaction, source, manga_id, chapter_ids, fallbacks=None):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("Hanya staff yang dapat download RAW.")
    await interaction.response.edit_message(
        embed=discord.Embed(
            title="Menyiapkan RAW...",
            description=f"Sumber: **{source.title()}**\nChapter: **{', '.join(chapter_ids)}**\n\nMembuat satu ZIP gambar lalu upload ke Filebin.",
            color=discord.Color.gold(),
        ),
        view=None,
    )
    filebin_url, completed, final_source = await create_filebin_download(
        source, manga_id, chapter_ids, fallbacks
    )
    if not filebin_url:
        return await interaction.edit_original_response(embed=discord.Embed(title="Upload Filebin Gagal", description="RAW tidak tersedia atau Filebin sedang menolak upload. File lokal sudah dibersihkan; coba lagi nanti.", color=discord.Color.red()))
    embed = discord.Embed(title="RAW Siap Diunduh", description=f"Gambar dari **{len(completed)} chapter** sudah tersedia langsung di Filebin tanpa ZIP bertingkat.", color=discord.Color.green())
    embed.add_field(name="Sumber Final", value=final_source.title(), inline=False)
    embed.add_field(name="Chapter", value=", ".join(completed), inline=False)
    embed.add_field(name="Link Download", value=f"[Buka Filebin]({filebin_url})", inline=False)
    embed.add_field(name="Cara Download", value="Buka Filebin lalu pilih **Download files**. ZIP hasil download langsung berisi `ch-1_001.jpg`, `ch-1_002.jpg`, dan seterusnya.", inline=False)
    embed.add_field(name="Penyimpanan", value="File lokal VPS langsung dihapus. Link Filebin berlaku sementara.", inline=False)
    await interaction.edit_original_response(embed=embed)
