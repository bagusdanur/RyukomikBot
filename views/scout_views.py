import discord

import project_scout as scout_service
from helpers.utils import is_admin
from views.raw_views import RawSearchModal


SCOUT_LABELS = {
    "untranslated": "Belum ditemukan di Indonesia",
    "lagging": "Versi Indonesia tertinggal",
    "available": "Sudah tersedia di Indonesia",
    "ambiguous": "Perlu diperiksa manual",
    "ryukomik_project": "Sudah menjadi project Ryukomik",
    "candidate": "Kandidat", "adopted": "Sudah diambil", "ignored": "Diabaikan",
}


def build_scout_embed(result: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Project Scout • {result['canonical_title']}",
        description=SCOUT_LABELS.get(result["scout_status"], result["scout_status"]),
        color=discord.Color.green() if result["scout_status"] == "untranslated" else discord.Color.gold(),
    )
    embed.add_field(name="Chapter RAW", value=str(result.get("raw_latest_chapter") or "—"), inline=True)
    embed.add_field(name="Chapter Indonesia", value=str(result.get("indonesia_latest_chapter") or "—"), inline=True)
    embed.add_field(name="Confidence", value=f"{result.get('confidence', 0)}%", inline=True)
    matches = [source for source in result.get("sources", []) if source.get("source_group") != "raw" and int(source.get("match_score") or 0) >= 55][:6]
    embed.add_field(
        name="Hasil Pembanding",
        value="\n".join(f"• **{item['source'].title()}** — {item['title']} ({item['match_score']}%)" for item in matches) or "Tidak ditemukan hasil yang cukup mirip.",
        inline=False,
    )
    embed.set_footer(text="Pustaka Indonesia diperiksa lebih dahulu • Konfirmasi sebelum mengambil project")
    return embed


class ScoutResultView(discord.ui.View):
    def __init__(self, title: str, dashboard_url: str):
        super().__init__(timeout=900)
        self.raw_title = title
        self.add_item(discord.ui.Button(label="Buka Dashboard", style=discord.ButtonStyle.link, url=f"{dashboard_url}/?page=scout"))

    @discord.ui.button(label="Cari & Download RAW", style=discord.ButtonStyle.success)
    async def download_raw(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator yang dapat memakai aksi ini.", ephemeral=True)
        await interaction.response.send_modal(RawSearchModal(self.raw_title))


class ProjectScoutModal(discord.ui.Modal, title="Project Scout"):
    query = discord.ui.TextInput(label="Judul Komik RAW", placeholder="Contoh: Affair Agency", min_length=2, max_length=180)

    def __init__(self, dashboard_url: str):
        super().__init__()
        self.dashboard_url = dashboard_url

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator yang dapat memakai Project Scout.", ephemeral=True)
        await interaction.response.defer(ephemeral=False, thinking=True)
        try:
            result = await scout_service.scan_title(str(self.query.value), "all")
        except ValueError as error:
            return await interaction.followup.send(str(error), ephemeral=True)
        except Exception:
            return await interaction.followup.send("Project Scout gagal menghubungi layanan sumber. Coba kembali sebentar lagi.", ephemeral=True)
        await interaction.followup.send(embed=build_scout_embed(result), view=ScoutResultView(result["canonical_title"], self.dashboard_url))
