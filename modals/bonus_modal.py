"""Modal and views for admin manual bonus."""

import discord

import performance_bonus as bonus_service
from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import format_currency, is_admin


class ManualBonusModal(discord.ui.Modal, title="Bonus Manual"):
    """Admin fills in amount + reason for a manual bonus."""

    jumlah = discord.ui.TextInput(
        label="Jumlah (Rp)",
        placeholder="Contoh: 15000",
        required=True,
        max_length=10,
    )
    alasan = discord.ui.TextInput(
        label="Alasan",
        placeholder="Contoh: Lembur deadline ketat",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=200,
    )
    periode = discord.ui.TextInput(
        label="Periode (opsional, default bulan ini)",
        placeholder="YYYY-MM, contoh: 2026-08",
        required=False,
        max_length=7,
    )

    def __init__(self, staff_member: discord.Member):
        super().__init__()
        self.staff_member = staff_member

    async def on_submit(self, interaction: discord.Interaction):
        # Validate amount
        try:
            amount = int(str(self.jumlah.value).strip().replace(".", "").replace(",", ""))
        except ValueError:
            return await interaction.response.send_message(
                "Jumlah harus berupa angka.", ephemeral=False,
            )
        if amount <= 0:
            return await interaction.response.send_message(
                "Jumlah bonus harus lebih dari 0.", ephemeral=False,
            )

        reason = str(self.alasan.value).strip()
        if not reason:
            return await interaction.response.send_message(
                "Alasan bonus wajib diisi.", ephemeral=False,
            )

        period = str(self.periode.value).strip() or None
        if period:
            import re
            if not re.match(r"^\d{4}-\d{2}$", period):
                return await interaction.response.send_message(
                    "Format periode harus YYYY-MM, contoh: 2026-08.", ephemeral=False,
                )

        await interaction.response.defer(ephemeral=False)

        try:
            result = await bonus_service.create_manual_bonus(
                staff_id=self.staff_member.id,
                amount=amount,
                reason=reason,
                created_by=interaction.user.id,
                period=period,
            )
        except ValueError as error:
            return await interaction.followup.send(str(error))

        # Confirmation embed
        embed = discord.Embed(
            title="🎁 Bonus Manual Diberikan",
            color=discord.Color.green(),
        )
        embed.add_field(name="Staff", value=self.staff_member.mention, inline=True)
        embed.add_field(name="Jumlah", value=format_currency(amount), inline=True)
        embed.add_field(name="Periode", value=result["period"], inline=True)
        embed.add_field(name="Alasan", value=reason, inline=False)
        embed.set_footer(text=f"Bonus #{result['id']} • Diberikan oleh {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

        # Notify staff ticket
        if interaction.guild:
            from helpers.utils import find_ticket
            ticket = await find_ticket(interaction.guild, self.staff_member.id)
            if ticket:
                staff_embed = discord.Embed(
                    title="🎁 Kamu Mendapat Bonus Manual!",
                    description=(
                        f"Administrator memberikan bonus sebesar **{format_currency(amount)}**.\n"
                        f"Bonus ini akan otomatis masuk ke invoice gaji berikutnya."
                    ),
                    color=discord.Color.green(),
                )
                staff_embed.add_field(name="Alasan", value=reason, inline=False)
                staff_embed.add_field(name="Periode", value=result["period"], inline=True)
                await ticket.send(
                    content=self.staff_member.mention,
                    embed=staff_embed,
                )


class ManualBonusStaffSelect(discord.ui.UserSelect):
    """Dropdown to pick which staff member receives the bonus."""

    def __init__(self):
        super().__init__(
            placeholder="Pilih staff yang akan diberi bonus...",
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message(
                "Member tidak ditemukan di server ini.", ephemeral=False,
            )
        from helpers.utils import is_staff
        if not is_staff(member):
            return await interaction.response.send_message(
                f"{member.mention} belum memiliki role Staff.", ephemeral=False,
            )
        await interaction.response.send_modal(ManualBonusModal(member))


class ManualBonusStaffView(discord.ui.View):
    """Ephemeral view that lets admin select a staff member for manual bonus."""

    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ManualBonusStaffSelect())

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
