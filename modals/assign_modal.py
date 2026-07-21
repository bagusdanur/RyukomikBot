import discord

from config import ROLE_STAFF_ID, STAFF_TASKS_CHANNEL_ID
from helpers.utils import (
    calculate_final_rate,
    calculate_rate,
    format_currency,
    is_admin,
    is_popular_series,
    normalize_role,
)
from panels.claim_view import ClaimView
import database as db


class AssignModal(discord.ui.Modal, title="Assign Tugas Baru"):
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

    role = discord.ui.TextInput(
        label="Role (TL/TS/TL+TS)",
        placeholder="TL, TS, atau TL+TS",
        style=discord.TextStyle.short,
        required=True,
    )

    rate_override = discord.ui.TextInput(
        label="Rate Override (Opsional)",
        placeholder="Kosongkan untuk rate default",
        style=discord.TextStyle.short,
        required=False,
    )

    options = discord.ui.TextInput(
        label="Halaman, Deadline Ketat? (Opsional)",
        placeholder="Contoh: 24, ya",
        style=discord.TextStyle.short,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "Hanya admin yang bisa assign tugas!",
                ephemeral=False,
            )

        role = normalize_role(self.role.value)
        if role is None:
            return await interaction.response.send_message(
                "Role harus TL, TS, atau TL+TS!",
                ephemeral=False,
            )

        base_rate = calculate_rate(role, self.manga.value)
        if self.rate_override.value:
            try:
                override = int(self.rate_override.value)
                if override < 0 or override > 50000:
                    return await interaction.response.send_message(
                        "Rate override harus antara 0 dan 50000!",
                        ephemeral=False,
                    )
                base_rate = override
            except ValueError:
                return await interaction.response.send_message(
                    "Rate override harus berupa angka!",
                    ephemeral=False,
                )

        page_count = 0
        tight_deadline = False
        if self.options.value:
            option_parts = [part.strip() for part in self.options.value.split(",")]
            if option_parts and option_parts[0]:
                try:
                    page_count = int(option_parts[0])
                except ValueError:
                    return await interaction.response.send_message(
                        "Jumlah halaman harus angka. Contoh: 24, ya",
                        ephemeral=False,
                    )
            if len(option_parts) > 1:
                tight_deadline = option_parts[1].casefold() in ("ya", "yes", "y", "true", "1")

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
