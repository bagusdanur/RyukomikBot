import asyncio
import os
import shutil
import time

import discord

from helpers.utils import is_staff
from raw_downloader import get_downloader

RAW_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "raw")
DISCORD_FILE_LIMIT = 25 * 1024 * 1024


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


class RawSearchModal(discord.ui.Modal, title="Cari dan Download RAW"):
    query = discord.ui.TextInput(label="Judul Komik", placeholder="Contoh: Solo Leveling", min_length=2, max_length=100)

    async def on_submit(self, interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya staff yang dapat download RAW.")
        await interaction.response.defer()
        asura, doujiva = await asyncio.gather(
            get_downloader("asura").search_manga(self.query.value),
            get_downloader("doujiva").search_manga(self.query.value),
            return_exceptions=True,
        )
        combined = []
        for source, result in (("asura", asura), ("doujiva", doujiva)):
            if isinstance(result, list):
                combined.extend({**manga, "_source": source} for manga in result[:12])
        if not combined:
            return await interaction.followup.send("Komik tidak ditemukan di Asura maupun Doujiva. Coba judul yang lebih singkat.")
        embed = discord.Embed(title="Hasil Pencarian RAW", description=f"Hasil **{self.query.value}** dari Asura dan Doujiva. Pilih komik yang benar.", color=discord.Color.blue())
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
                description=f"Chapter {item['chapter']} • {item['role']}"[:100],
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
                title="Mencari RAW Proyek…",
                description=(
                    f"Proyek: **{assignment['manga']}**\n"
                    f"Target chapter: **{assignment['chapter']}**\n\n"
                    "Mencari otomatis di Asura dan Doujiva."
                ),
                color=discord.Color.gold(),
            ),
            view=None,
        )
        asura, doujiva = await asyncio.gather(
            get_downloader("asura").search_manga(assignment["manga"]),
            get_downloader("doujiva").search_manga(assignment["manga"]),
            return_exceptions=True,
        )
        combined = []
        for source, result in (("asura", asura), ("doujiva", doujiva)):
            if isinstance(result, list):
                combined.extend({**manga, "_source": source} for manga in result[:12])
        if not combined:
            return await interaction.edit_original_response(
                embed=discord.Embed(
                    title="RAW Tidak Ditemukan",
                    description=(
                        f"Tidak ada hasil untuk **{assignment['manga']}** di Asura maupun Doujiva. "
                        "Hubungi admin jika judul proyek perlu disesuaikan."
                    ),
                    color=discord.Color.red(),
                )
            )
        embed = discord.Embed(
            title="Pilih Komik RAW",
            description=(
                f"Proyek tugas: **{assignment['manga']} — Ch. {assignment['chapter']}**\n"
                "Pilih hasil yang sesuai. Judul diambil otomatis dari tugas kamu."
            ),
            color=discord.Color.blue(),
        )
        await interaction.edit_original_response(embed=embed, view=RawSearchView("auto", combined))


class RawSearchView(discord.ui.View):
    def __init__(self, source, results):
        super().__init__(timeout=300)
        normalized = [{**manga, "_source": manga.get("_source", source)} for manga in results[:25]]
        self.add_item(RawMangaSelect(normalized))


class RawMangaSelect(discord.ui.Select):
    def __init__(self, results):
        self.results = results
        options = [discord.SelectOption(label=str(manga.get("title", "Tanpa judul"))[:100], value=str(index), description=f"{manga['_source'].title()} • {manga.get('status', 'status tidak diketahui')}"[:100]) for index, manga in enumerate(results)]
        super().__init__(placeholder="Pilih komik", options=options)

    async def callback(self, interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya staff yang dapat memakai RAW navigator.")
        manga = self.results[int(self.values[0])]
        source, manga_id = manga["_source"], str(manga["id"])
        await interaction.response.edit_message(embed=discord.Embed(title="Mengambil Daftar Chapter…", description=f"**{manga.get('title')}** dari {source.title()}", color=discord.Color.gold()), view=None)
        chapters = await get_downloader(source).get_chapter_list(manga_id)
        if not chapters:
            return await interaction.edit_original_response(embed=discord.Embed(title="Chapter Tidak Ditemukan", description="Sumber sedang bermasalah atau chapter belum tersedia.", color=discord.Color.red()))
        embed = discord.Embed(title="Pilih Chapter RAW", description=f"**{manga.get('title')}** • {source.title()}\nPilih maksimal 10 chapter, atau tekan **Download Terbaru**.", color=discord.Color.blue())
        await interaction.edit_original_response(embed=embed, view=RawChapterView(source, manga_id, chapters[:25]))


class RawChapterView(discord.ui.View):
    def __init__(self, source, manga_id, chapters):
        super().__init__(timeout=300)
        self.source, self.manga_id, self.chapters = source, manga_id, chapters
        self.add_item(RawChapterSelect(self, chapters))

    @discord.ui.button(label="Download Terbaru", style=discord.ButtonStyle.success, row=1)
    async def latest_button(self, interaction, _button):
        await download_chapters(interaction, self.source, self.manga_id, [str(self.chapters[0]["id"])])


class RawChapterSelect(discord.ui.Select):
    def __init__(self, parent_view, chapters):
        self.parent_view = parent_view
        options = [discord.SelectOption(label=str(chapter.get("title", chapter.get("id")))[:100], value=str(chapter.get("id")), description=str(chapter.get("date") or "Pilih untuk download")[:100]) for chapter in chapters]
        super().__init__(placeholder="Pilih chapter (maksimal 10)", options=options, min_values=1, max_values=min(10, len(options)), row=0)

    async def callback(self, interaction):
        await download_chapters(interaction, self.parent_view.source, self.parent_view.manga_id, self.values)


async def download_chapters(interaction, source, manga_id, chapter_ids):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("Hanya staff yang dapat download RAW.")
    cleanup_old_raw_files()
    os.makedirs(RAW_ROOT, exist_ok=True)
    await interaction.response.edit_message(embed=discord.Embed(title="Mengunduh RAW…", description=f"Sumber: **{source.title()}**\nChapter: **{', '.join(chapter_ids)}**\n\nMengambil gambar dan membuat ZIP. Mohon tunggu.", color=discord.Color.gold()), view=None)
    downloader = get_downloader(source)
    completed = []
    for chapter_id in chapter_ids:
        result = await downloader.download_chapter(manga_id, chapter_id, RAW_ROOT)
        if result:
            completed.append((chapter_id, shutil.make_archive(result, "zip", result)))
    if not completed:
        return await interaction.edit_original_response(embed=discord.Embed(title="Download Gagal", description="Gambar tidak tersedia atau API sumber sedang bermasalah. Coba lagi nanti.", color=discord.Color.red()))
    deliverable = [(chapter, path) for chapter, path in completed if os.path.getsize(path) <= DISCORD_FILE_LIMIT]
    embed = discord.Embed(title="RAW Selesai", description=f"**{len(completed)} chapter** berhasil dibuat menjadi ZIP.", color=discord.Color.green())
    embed.add_field(name="Chapter", value=", ".join(chapter for chapter, _ in completed), inline=False)
    if len(deliverable) != len(completed):
        embed.add_field(name="File Terlalu Besar", value="Sebagian ZIP melebihi 25 MB. Hubungi administrator untuk mengambil file dari server.", inline=False)
    await interaction.edit_original_response(embed=embed)
    if deliverable:
        await interaction.followup.send(content="File RAW siap digunakan:", files=[discord.File(path) for _, path in deliverable[:10]])
