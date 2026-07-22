import os
import shutil

import discord

from helpers.utils import is_staff
from raw_downloader import get_downloader


class RawSearchView(discord.ui.View):
    def __init__(self, source, results):
        super().__init__(timeout=300)
        self.add_item(RawMangaSelect(source, results[:25]))


class RawMangaSelect(discord.ui.Select):
    def __init__(self, source, results):
        self.source = source
        options = [discord.SelectOption(label=str(m.get("title", "Tanpa judul"))[:100], value=str(m.get("id")), description=f"{source.title()} • {m.get('status', 'status tidak diketahui')}"[:100]) for m in results]
        super().__init__(placeholder="Pilih komik untuk melihat chapter", options=options)

    async def callback(self, interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya staff yang dapat memakai RAW navigator.")
        await interaction.response.defer()
        manga_id = self.values[0]
        chapters = await get_downloader(self.source).get_chapter_list(manga_id)
        if not chapters:
            return await interaction.followup.send("Chapter tidak ditemukan atau API sedang bermasalah.")
        embed = discord.Embed(title="Pilih Chapter RAW", description="Pilih satu atau beberapa chapter (maksimal 10), lalu bot akan mengunduh dan membuat ZIP.", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=RawChapterView(self.source, manga_id, chapters[:25]))


class RawChapterView(discord.ui.View):
    def __init__(self, source, manga_id, chapters):
        super().__init__(timeout=300)
        self.add_item(RawChapterSelect(source, manga_id, chapters))


class RawChapterSelect(discord.ui.Select):
    def __init__(self, source, manga_id, chapters):
        self.source, self.manga_id = source, manga_id
        options = [discord.SelectOption(label=str(c.get("title", c.get("id")))[:100], value=str(c.get("id")), description=str(c.get("date", "Pilih untuk download"))[:100]) for c in chapters]
        super().__init__(placeholder="Pilih chapter untuk download", options=options, min_values=1, max_values=min(10, len(options)))

    async def callback(self, interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya staff yang dapat download RAW.")
        await interaction.response.defer()
        downloader = get_downloader(self.source)
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "raw")
        completed = []
        for chapter_id in self.values:
            result = await downloader.download_chapter(self.manga_id, chapter_id, base)
            if result:
                archive = shutil.make_archive(result, "zip", result)
                completed.append((chapter_id, archive))
        if not completed:
            return await interaction.followup.send("Download gagal. Coba lagi atau cek kesehatan API lewat `/status-bot`.")
        small = [(cid, path) for cid, path in completed if os.path.getsize(path) <= 25 * 1024 * 1024]
        embed = discord.Embed(title="RAW Selesai", description=f"{len(completed)} chapter berhasil diproses.", color=discord.Color.green())
        embed.add_field(name="Chapter", value=", ".join(cid for cid, _ in completed), inline=False)
        if len(small) != len(completed):
            embed.add_field(name="Catatan", value="Sebagian ZIP lebih dari 25 MB dan tersimpan di server.", inline=False)
        await interaction.followup.send(embed=embed, files=[discord.File(path) for _, path in small[:10]])
