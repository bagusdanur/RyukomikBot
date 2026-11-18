"""Admin slash command untuk memberi/cabut akses role komunitas Scanlator."""

import discord
from discord import app_commands

from config import ROLE_SCANLATOR_ID
from helpers.utils import is_admin


async def scanlator_akses_command(
    interaction: discord.Interaction,
    member: discord.Member,
    aksi: str,
):
    """Grant atau revoke role Scanlator untuk seorang member."""
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Hanya Administrator yang dapat mengatur akses Scanlator.", ephemeral=True
        )

    if interaction.guild is None:
        return await interaction.response.send_message(
            "Command ini hanya dapat dipakai di server.", ephemeral=True
        )

    role = interaction.guild.get_role(ROLE_SCANLATOR_ID) if ROLE_SCANLATOR_ID else None
    role = role or discord.utils.get(interaction.guild.roles, name="Scanlator")
    if role is None:
        return await interaction.response.send_message(
            "Role Scanlator belum tersedia di server ini.", ephemeral=True
        )

    if aksi == "grant":
        if role in member.roles:
            return await interaction.response.send_message(
                f"{member.mention} sudah memiliki role Scanlator.", ephemeral=True
            )
        try:
            await member.add_roles(role, reason="Akses grup Scanlator diberikan Administrator")
        except (discord.Forbidden, discord.HTTPException) as error:
            return await interaction.response.send_message(
                f"Gagal memberi role: {error}", ephemeral=True
            )
        result = "diberikan"
    else:
        if role not in member.roles:
            return await interaction.response.send_message(
                f"{member.mention} tidak memiliki role Scanlator.", ephemeral=True
            )
        try:
            await member.remove_roles(role, reason="Akses grup Scanlator dicabut Administrator")
            # Hapus juga overwrite channel supaya tidak bisa baca lewat izin langsung.
            from config import SCANLATOR_CHANNEL_ID
            channel = interaction.guild.get_channel(SCANLATOR_CHANNEL_ID) if SCANLATOR_CHANNEL_ID else None
            if isinstance(channel, discord.TextChannel):
                await channel.set_permissions(member, overwrite=None)
        except (discord.Forbidden, discord.HTTPException) as error:
            return await interaction.response.send_message(
                f"Gagal mencabut role: {error}", ephemeral=True
            )
        result = "dicabut"

    try:
        import operations
        await operations.record_event(
            "scanlator", "info", f"Akses Scanlator {aksi}: {member.id}",
            {"actor": interaction.user.id, "member": member.id, "aksi": aksi},
        )
    except Exception:
        pass

    embed = discord.Embed(
        title="Akses Scanlator diperbarui",
        description=f"Role Scanlator **{result}** untuk {member.mention}.",
        color=discord.Color.green() if aksi == "grant" else discord.Color.orange(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


def register_scanlator_commands(tree, guild_id: int):
    """Daftarkan slash command ke tree (guild-scoped)."""
    tree.add_command(
        app_commands.Command(
            name="scanlator-akses",
            description="Beri/cabut akses role komunitas Scanlator",
            callback=scanlator_akses_command,
        ),
        guild=discord.Object(id=guild_id),
    )
