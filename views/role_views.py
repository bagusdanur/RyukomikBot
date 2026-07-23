"""Persistent self-role components for the existing zodiac panel."""

from __future__ import annotations

import discord


ZODIAC_NAMES = (
    "Aries",
    "Taurus",
    "Gemini",
    "Cancer",
    "Leo",
    "Virgo",
    "Libra",
    "Scorpio",
    "Sagittarius",
    "Capricorn",
    "Aquarius",
    "Pisces",
)

ZODIAC_EMOJI = {
    "Aries": "♈",
    "Taurus": "♉",
    "Gemini": "♊",
    "Cancer": "♋",
    "Leo": "♌",
    "Virgo": "♍",
    "Libra": "♎",
    "Scorpio": "♏",
    "Sagittarius": "♐",
    "Capricorn": "♑",
    "Aquarius": "♒",
    "Pisces": "♓",
}


def zodiac_roles(member: discord.Member) -> list[discord.Role]:
    wanted = set(ZODIAC_NAMES)
    return [role for role in member.roles if role.name in wanted]


class ZodiacSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Pilih zodiak kamu...",
            custom_id="zodiac_select",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=name, value=name, emoji=ZODIAC_EMOJI[name])
                for name in ZODIAC_NAMES
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Pilihan role hanya dapat digunakan di server.",
                ephemeral=True,
            )

        # Acknowledge immediately so role updates never cause an interaction timeout.
        await interaction.response.defer(ephemeral=True)
        selected_name = self.values[0]
        selected_role = discord.utils.get(interaction.guild.roles, name=selected_name)
        if selected_role is None:
            return await interaction.followup.send(
                f"Role **{selected_name}** tidak ditemukan. Hubungi Administrator.",
                ephemeral=True,
            )
        if not selected_role.is_assignable():
            return await interaction.followup.send(
                f"Yuki belum memiliki izin untuk mengatur role **{selected_name}**.",
                ephemeral=True,
            )

        current = zodiac_roles(interaction.user)
        try:
            if selected_role in current:
                await interaction.user.remove_roles(
                    selected_role,
                    reason="Self-role zodiak dihapus oleh pengguna",
                )
                return await interaction.followup.send(
                    f"{ZODIAC_EMOJI[selected_name]} Role **{selected_name}** berhasil dihapus.",
                    ephemeral=True,
                )

            old_roles = [role for role in current if role != selected_role]
            if old_roles:
                await interaction.user.remove_roles(
                    *old_roles,
                    reason="Mengganti self-role zodiak",
                )
            await interaction.user.add_roles(
                selected_role,
                reason="Self-role zodiak dipilih oleh pengguna",
            )
            await interaction.followup.send(
                f"{ZODIAC_EMOJI[selected_name]} Role **{selected_name}** berhasil dipasang.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "Yuki tidak dapat mengubah role tersebut. Administrator perlu memeriksa hierarchy role.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Discord sedang gagal memperbarui role. Silakan coba beberapa saat lagi.",
                ephemeral=True,
            )


class ZodiacRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ZodiacSelect())
