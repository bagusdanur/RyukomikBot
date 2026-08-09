import discord

import database as db
from config import STAFF_PAYRATE_CHANNEL_ID
from helpers.utils import DEFAULT_PAYRATES, find_ticket


ROLE_LABELS = {
    "TL": "Translator (TL)",
    "TS": "Editor / Typesetter (TS)",
    "TL+TS": "TL + TS (Keduanya)",
}


async def get_payrate_ranges() -> dict[str, dict[str, int]]:
    connection = await db.get_db()
    try:
        rows = await (await connection.execute(
            "SELECT role,base_rate,min_rate,max_rate FROM payrates"
        )).fetchall()
    finally:
        await connection.close()
    result = {
        role: {"min": values["min"], "max": values["max"]}
        for role, values in DEFAULT_PAYRATES.items()
    }
    for row in rows:
        result[row["role"]] = {
            "min": int(row["min_rate"] or row["base_rate"]),
            "max": int(row["max_rate"] or row["base_rate"]),
        }
    return result


def build_payrate_embed(ranges: dict[str, dict[str, int]]) -> discord.Embed:
    embed = discord.Embed(
        title="💰 Ryukomik | Staff Pay Rates",
        description=(
            "Rate berikut berlaku sebagai panduan bayaran per chapter. "
            "Nominal tugas tetap ditampilkan sebelum staff mulai mengerjakan."
        ),
        color=discord.Color.from_rgb(124, 140, 255),
    )
    for role in ("TL", "TS", "TL+TS"):
        values = ranges[role]
        value = (
            f"**Rp{values['min']:,.0f} – Rp{values['max']:,.0f} / chapter**"
            .replace(",", ".")
        )
        embed.add_field(name=ROLE_LABELS[role], value=value, inline=False)
    embed.add_field(
        name="Ketentuan",
        value=(
            "• Rate final dihitung otomatis dari tingkat kesusahan RAW asli chapter "
            "(jumlah halaman & tinggi gambar), lalu ditampilkan sebagai Ringan/Sedang/Berat "
            "di tugas kamu — bukan tebakan Administrator.\n"
            "• Administrator hanya bisa menyesuaikan manual bila memang diperlukan.\n"
            "• Tugas multi-chapter dihitung: rate per chapter × jumlah chapter.\n"
            "• Perubahan rate resmi tidak mengubah tugas lama secara otomatis."
        ),
        inline=False,
    )
    embed.set_footer(text="Ryukomik Official • Informasi rate staff terbaru")
    return embed


async def upsert_payrate_panel(guild: discord.Guild) -> discord.Message | None:
    channel = guild.get_channel(STAFF_PAYRATE_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return None
    embed = build_payrate_embed(await get_payrate_ranges())
    async for message in channel.history(limit=100):
        if (
            guild.me
            and message.author.id == guild.me.id
            and message.embeds
            and "Staff Pay Rates" in (message.embeds[0].title or "")
        ):
            await message.edit(embed=embed)
            return message
    return await channel.send(embed=embed)


async def broadcast_payrate_update(
    guild: discord.Guild,
    role: str,
    min_rate: int,
    max_rate: int,
) -> int:
    """Notify only current Staff-role members in their private ticket."""
    from helpers.utils import is_staff

    sent = 0
    for member in guild.members:
        if member.bot or not is_staff(member):
            continue
        ticket = await find_ticket(guild, member.id)
        if not ticket:
            continue
        embed = discord.Embed(
            title="📢 Payrate Staff Diperbarui",
            description=(
                f"Range **{ROLE_LABELS[role]}** sekarang "
                f"**Rp{min_rate:,.0f} – Rp{max_rate:,.0f} / chapter**."
            ).replace(",", "."),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Tugas lama tidak berubah • Berlaku untuk penentuan tugas berikutnya")
        await ticket.send(embed=embed)
        sent += 1
    return sent
