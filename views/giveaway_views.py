"""Interactive Discord views and dynamic items for Ryukomik giveaways."""

from __future__ import annotations

import logging
import discord

import database as db
import giveaway_service as gservice

log = logging.getLogger(__name__)


class GiveawayJoinDynamic(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"giveaway:join:(?P<giveaway_id>\d+)",
):
    """Dynamic persistent button for joining and leaving a giveaway."""

    def __init__(self, giveaway_id: int):
        self.giveaway_id = giveaway_id
        super().__init__(
            discord.ui.Button(
                label="🎉 Ikut Giveaway",
                style=discord.ButtonStyle.success,
                custom_id=f"giveaway:join:{giveaway_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: dict[str, str]):
        return cls(int(match["giveaway_id"]))

    async def callback(self, interaction: discord.Interaction):
        # 1. Retrieve giveaway record
        giveaway = await db.get_giveaway(self.giveaway_id)
        if not giveaway:
            return await interaction.response.send_message(
                "❌ Giveaway tidak ditemukan atau sudah dihapus.", ephemeral=True
            )

        if giveaway["status"] != "active":
            return await interaction.response.send_message(
                f"⚠️ Giveaway ini sudah **{giveaway['status']}**.", ephemeral=True
            )

        # 2. Check role requirement if configured
        req_role_id = giveaway.get("requirement_role_id")
        if req_role_id:
            if not isinstance(interaction.user, discord.Member) or not any(r.id == req_role_id for r in interaction.user.roles):
                return await interaction.response.send_message(
                    f"🔒 Kamu membutuhkan role <@&{req_role_id}> untuk mengikuti giveaway ini.",
                    ephemeral=True,
                )

        # 3. Toggle participation
        joined, total_entries = await db.toggle_giveaway_entry(self.giveaway_id, interaction.user.id)

        # 4. Give immediate feedback to the user
        if joined:
            msg = (
                f"🎉 **Kamu berhasil terdaftar dalam giveaway {giveaway['prize']}!**\n"
                "Semoga beruntung! 🍀 *(Klik tombol lagi jika ingin membatalkan)*"
            )
        else:
            msg = f"ℹ️ Kamu telah **membatalkan** keikutsertaan dalam giveaway **{giveaway['prize']}**."

        await interaction.response.send_message(msg, ephemeral=True)

        # 5. Refresh the giveaway message embed with updated participant count
        if interaction.message:
            try:
                guild = interaction.guild
                new_embed = gservice.build_giveaway_embed(giveaway, total_entries, guild)
                await interaction.message.edit(embed=new_embed)
            except Exception as error:
                log.debug("Could not refresh giveaway embed count: %s", error)


class GiveawayView(discord.ui.View):
    """View wrapper for initial giveaway post."""

    def __init__(self, giveaway_id: int):
        super().__init__(timeout=None)
        self.add_item(GiveawayJoinDynamic(giveaway_id))
