import discord

from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import find_or_create_staff_ticket, format_currency, is_staff
from views.ticket_views import TicketSubmitView
import database as db


class ClaimView(discord.ui.View):
    """View for claiming an assignment."""

    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id

    @discord.ui.button(label="Claim Tugas", style=discord.ButtonStyle.primary, custom_id="claim_task")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                "Hanya staff yang bisa claim tugas!",
                ephemeral=False,
            )

        assignment = await db.get_assignment(self.assignment_id)
        if not assignment:
            return await interaction.response.send_message("Tugas tidak ditemukan!", ephemeral=False)

        if assignment["status"] != "open":
            return await interaction.response.send_message(
                "Tugas ini sudah di-claim atau tidak tersedia!",
                ephemeral=False,
            )

        success = await db.claim_assignment(self.assignment_id, interaction.user.id)
        if not success:
            return await interaction.response.send_message(
                "Gagal claim tugas. Mungkin sudah di-claim orang lain!",
                ephemeral=False,
            )

        ticket_channel = None
        if interaction.guild and isinstance(interaction.user, discord.Member):
            ticket_channel = await find_or_create_staff_ticket(interaction.guild, interaction.user)
            if ticket_channel:
                await db.set_assignment_ticket_channel(self.assignment_id, ticket_channel.id)

        embed = discord.Embed(
            title="Tugas Di-claim",
            description=f"**{interaction.user.display_name}** telah claim tugas ini.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Manga", value=assignment["manga"], inline=True)
        embed.add_field(name="Chapter", value=assignment["chapter"], inline=True)
        embed.add_field(name="Role", value=assignment["role"], inline=True)
        embed.add_field(name="Rate", value=format_currency(assignment["final_rate"]), inline=True)
        if ticket_channel:
            embed.add_field(name="Tiket Staff", value=ticket_channel.mention, inline=False)

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

        if ticket_channel:
            ticket_embed = discord.Embed(
                title=f"Tugas #{assignment['id']}",
                description=f"**{assignment['manga']}** - Chapter {assignment['chapter']}",
                color=discord.Color.blue(),
            )
            ticket_embed.add_field(name="Role", value=assignment["role"], inline=True)
            ticket_embed.add_field(name="Rate", value=format_currency(assignment["final_rate"]), inline=True)
            ticket_embed.add_field(name="Status", value="claimed", inline=True)
            await ticket_channel.send(
                content=interaction.user.mention,
                embed=ticket_embed,
                view=TicketSubmitView(self.assignment_id),
            )

        if interaction.guild:
            log_channel = interaction.guild.get_channel(STAFF_LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(
                    f"**{interaction.user.display_name}** claim tugas "
                    f"**{assignment['manga']}** chapter **{assignment['chapter']}** ({assignment['role']})."
                )
