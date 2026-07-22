import discord

from config import ROLE_STAFF_ID, STAFF_TASKS_CHANNEL_ID
from helpers.utils import (
    calculate_final_rate,
    format_currency,
    is_admin,
    is_popular_series,
    normalize_role,
)
from panels.claim_view import ClaimView
import database as db


class AssignRoleView(discord.ui.View):
    """First assignment step: choose a role without typing it manually."""

    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(AssignRoleSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_admin(interaction.user):
            return True
        await interaction.response.send_message(
            "Hanya administrator yang dapat membuat tugas.", ephemeral=False
        )
        return False


class AssignRoleSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Pilih role yang dibutuhkan...",
            options=[
                discord.SelectOption(
                    label="TL — Translator",
                    description="Menerjemahkan chapter",
                    value="TL",
                    emoji="💬",
                ),
                discord.SelectOption(
                    label="TS — Typesetter",
                    description="Cleaning, redraw, dan typesetting",
                    value="TS",
                    emoji="🎨",
                ),
                discord.SelectOption(
                    label="TL+TS — Keduanya",
                    description="Translator sekaligus typesetter",
                    value="TL+TS",
                    emoji="✨",
                ),
            ],
            custom_id="assign:role_select:v1",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AssignModal(self.values[0]))


class AssignModal(discord.ui.Modal, title="Detail Tugas Baru"):
    """Modal for assigning new tasks."""

    function_name = "AssignModal"

    manga = discord.ui.TextInput(
        label="Judul Manga",
        placeholder="Contoh: Solo Leveling",
        style=discord.TextStyle.short,
        required=True,
    )

    chapter = discord.ui.TextInput(
        label="Chapter",
        placeholder="Contoh: 100",
        style=discord.TextStyle.short,
        required=True,
    )

    rate_override = discord.ui.TextInput(
        label="Bayaran Manual (Opsional)",
        placeholder="Contoh: 15000. Kosongkan untuk rate default",
        style=discord.TextStyle.short,
        required=False,
    )

    page_count = discord.ui.TextInput(
        label="Jumlah Halaman (Opsional)",
        placeholder="Contoh: 24",
        style=discord.TextStyle.short,
        required=False,
    )

    tight_deadline = discord.ui.TextInput(
        label="Deadline Ketat? (Opsional)",
        placeholder="Pilih jawaban: ya atau tidak",
        style=discord.TextStyle.short,
        required=False,
    )

    def __init__(self, role: str):
        super().__init__()
        self.selected_role = role

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "Hanya admin yang bisa assign tugas!",
                ephemeral=False,
            )

        role = normalize_role(self.selected_role)
        if role is None:
            return await interaction.response.send_message(
                "Role harus TL, TS, atau TL+TS!",
                ephemeral=False,
            )

        has_override = False
        base_rate = await db.get_role_payrate(role)
        if self.rate_override.value:
            try:
                clean_override = self.rate_override.value.replace(".", "").replace(",", "").strip()
                override = int(clean_override)
                if override < 0 or override > 1000000:
                    return await interaction.response.send_message(
                        "Rate override harus antara 0 dan Rp 1.000.000!",
                        ephemeral=False,
                    )
                base_rate = override
                has_override = True
            except ValueError:
                return await interaction.response.send_message(
                    "Rate override harus berupa angka (contoh: 15000 atau 15.000)!",
                    ephemeral=False,
                )

        page_count = 0
        tight_deadline = False
        if self.page_count.value:
            try:
                page_count = int(self.page_count.value.strip())
                if page_count < 0 or page_count > 1000:
                    raise ValueError
            except ValueError:
                return await interaction.response.send_message(
                    "Jumlah halaman harus berupa angka antara 0 dan 1000.", ephemeral=False
                )
        if self.tight_deadline.value:
            deadline_answer = self.tight_deadline.value.strip().casefold()
            if deadline_answer not in ("ya", "yes", "y", "tidak", "no", "n"):
                return await interaction.response.send_message(
                    "Deadline ketat harus dijawab `ya` atau `tidak`.", ephemeral=False
                )
            tight_deadline = deadline_answer in ("ya", "yes", "y")

        multiplier = 1.0
        bonuses = []
        if is_popular_series(self.manga.value):
            multiplier += 0.3
            bonuses.append("Popular Series (+30%)")
        if page_count > 20:
            multiplier += 0.2
            bonuses.append("Chapter >20 halaman (+20%)")
        if tight_deadline:
            multiplier += 0.1
            bonuses.append("Deadline ketat (+10%)")

        if has_override:
            final_rate = base_rate
            multiplier = 1.0
            bonuses = ["Manual Override"]
        else:
            final_rate = calculate_final_rate(base_rate, role, multiplier)


        assignment_id = await db.create_assignment(
            manga=self.manga.value,
            chapter=self.chapter.value,
            role=role,
            base_rate=base_rate,
            final_rate=final_rate,
            multiplier=multiplier,
        )

        tasks_channel = interaction.guild.get_channel(STAFF_TASKS_CHANNEL_ID) if interaction.guild else None
        staff_role = interaction.guild.get_role(ROLE_STAFF_ID) if interaction.guild else None
        if tasks_channel:
            embed = discord.Embed(
                title="Tugas Baru",
                description=f"**{self.manga.value}** - Chapter {self.chapter.value}",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Role", value=role, inline=True)
            embed.add_field(name="Rate", value=format_currency(final_rate), inline=True)
            embed.add_field(name="Status", value="Available", inline=True)
            if bonuses:
                embed.add_field(name="Bonus", value="\n".join(bonuses), inline=False)
            embed.set_footer(text=f"Assignment ID: {assignment_id}")

            message = await tasks_channel.send(
                content=f"{staff_role.mention if staff_role else '@Staff'} Tugas baru tersedia!",
                embed=embed,
                view=ClaimView(assignment_id),
            )

            db_conn = await db.get_db()
            try:
                await db_conn.execute(
                    "UPDATE assignments SET message_id = ? WHERE id = ?",
                    (message.id, assignment_id),
                )
                await db_conn.commit()
            finally:
                await db_conn.close()

        embed = discord.Embed(
            title="Tugas Di-assign",
            description=f"Berhasil assign **{self.manga.value}** chapter **{self.chapter.value}**.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Role", value=role, inline=True)
        embed.add_field(name="Rate", value=format_currency(final_rate), inline=True)
        embed.add_field(name="Assignment ID", value=str(assignment_id), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)
