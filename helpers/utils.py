import discord
from typing import Optional, Union
from config import REKRUT_CAT_ID, ROLE_ADMIN_ID, ROLE_STAFF_ID

# Popular series with bonus multiplier
POPULAR_SERIES = [
    "Solo Leveling",
    "Nano Machine",
    "Martial Peak",
    "Tomb Raider King",
    "Leveling with the Gods",
    "The S-Classes That I Raised",
    "Return of the Mount Hua Sect",
    "Demonic Emperor",
    "I Grow Stronger By Eating!",
    "A Returner's Magic Should Be Special",
    "Infinite Leveling: Murim",
    "The Dark Magician Transmigrates After 66666 Years",
    "Seoul Station's Necromancer",
    "Omniscient Reader's Viewpoint",
    "Trash of the Count's Family",
]

# Status emojis for assignments
STATUS_EMOJI = {
    "open": "🔓",
    "claimed": "⏳",
    "submitted": "🟡",
    "revision": "🔴",
    "approved": "✅",
    "paid": "💰",
}


def is_admin(member: Union[discord.Member, discord.User]) -> bool:
    """Check if member has admin role or administrator permission."""
    if isinstance(member, discord.User):
        return False
    if member.guild_permissions.administrator:
        return True
    return any(role.id == ROLE_ADMIN_ID for role in member.roles)


def is_staff(member: Union[discord.Member, discord.User]) -> bool:
    """Check if member has staff role."""
    if isinstance(member, discord.User):
        return False
    return any(role.id == ROLE_STAFF_ID for role in member.roles)


ROLE_PAYRATES = {
    "TL": {"base": 3000, "max": 8000},
    "TS": {"base": 3000, "max": 12000},
    "TL+TS": {"base": 5000, "max": 15000},
}


def normalize_role(role: str) -> Optional[str]:
    """Normalize assignment role names to the PRD role set."""
    normalized = role.strip().upper().replace(" ", "")
    aliases = {
        "TL": "TL",
        "TS": "TS",
        "TL+TS": "TL+TS",
        "TLTS": "TL+TS",
    }
    return aliases.get(normalized)


def calculate_rate(role: str, manga: str) -> int:
    """Calculate the base rate for a role.
    
    Base rates:
    - TL (Translator): 3000
    - TS (Typesetter): 3000
    - TL+TS: 5000
    
    Maximum rates: TL 8000, TS 12000, TL+TS 15000
    """
    role = normalize_role(role) or role
    rates = ROLE_PAYRATES.get(role, ROLE_PAYRATES["TL"])
    return min(rates["base"], rates["max"])


def calculate_final_rate(base_rate: int, role: str, multiplier: float) -> int:
    """Calculate final rate while respecting the role cap."""
    role = normalize_role(role) or role
    max_rate = ROLE_PAYRATES.get(role, ROLE_PAYRATES["TL"])["max"]
    return min(int(base_rate * multiplier), max_rate)


def is_popular_series(manga: str) -> bool:
    """Return whether a manga title should receive the popular-series bonus."""
    normalized = manga.strip().casefold()
    return any(title.casefold() == normalized for title in POPULAR_SERIES)


async def get_or_fetch_member(guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
    """Get member from cache or fetch from Discord API if uncached."""
    if not guild or not user_id:
        return None
    member = guild.get_member(user_id)
    if member:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.HTTPException):
        return None


async def find_ticket(guild: discord.Guild, staff_id: int) -> Optional[discord.TextChannel]:
    """Find ticket channel by staff member's name or ID."""
    staff = await get_or_fetch_member(guild, staff_id)
    if not staff:
        return None
    
    # Search for channel with staff name
    for channel in guild.text_channels:
        if channel.category_id == REKRUT_CAT_ID or (channel.topic or "").startswith("Tiket rekrutmen"):
            continue
        topic = channel.topic or ""
        if str(staff.id) in topic or str(staff.id) in channel.name:
            return channel
    
    return None


def build_private_ticket_overwrites(
    guild: discord.Guild, member: discord.Member
) -> dict:
    """Permissions shared by private recruitment and staff tickets."""
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
        ),
    }
    admin_role = guild.get_role(ROLE_ADMIN_ID)
    if admin_role:
        overwrites[admin_role] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            manage_messages=True,
            attach_files=True,
            embed_links=True,
        )
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
        )
    return overwrites


def build_private_ticket_name(member: discord.Member) -> str:
    """Use the server's established private-ticket naming convention."""
    safe_name = "".join(
        character
        for character in member.name.lower()
        if character.isalnum() or character in "-_"
    )
    return f"🔒・tiket-{(safe_name[:70] or f'member-{member.id}') }"


async def find_recruitment_ticket(
    guild: discord.Guild, member: discord.Member
) -> Optional[discord.TextChannel]:
    """Find the member's existing recruitment ticket, including legacy tickets."""
    category = guild.get_channel(REKRUT_CAT_ID)
    if not isinstance(category, discord.CategoryChannel):
        return None

    for channel in category.text_channels:
        topic = channel.topic or ""
        if str(member.id) in topic:
            return channel
        for target, overwrite in channel.overwrites.items():
            if (
                isinstance(target, discord.Member)
                and target.id == member.id
                and overwrite.view_channel is not False
            ):
                return channel
    return None


async def find_or_create_staff_ticket(guild: discord.Guild, staff: discord.Member) -> Optional[discord.TextChannel]:
    """Find or create a private staff ticket channel."""
    existing = await find_ticket(guild, staff.id)
    if existing:
        await existing.edit(
            name=build_private_ticket_name(staff),
            overwrites=build_private_ticket_overwrites(guild, staff),
            sync_permissions=False,
            reason="Menormalkan tiket privat staff",
        )
        return existing

    recruitment_ticket = await find_recruitment_ticket(guild, staff)
    if recruitment_ticket:
        await recruitment_ticket.edit(
            name=build_private_ticket_name(staff),
            topic=f"Tiket staff untuk {staff.display_name} ({staff.id})",
            overwrites=build_private_ticket_overwrites(guild, staff),
            sync_permissions=False,
            reason="Menggunakan tiket rekrutmen sebagai tiket staff",
        )
        return recruitment_ticket

    overwrites = build_private_ticket_overwrites(guild, staff)

    category = guild.get_channel(REKRUT_CAT_ID)
    return await guild.create_text_channel(
        name=build_private_ticket_name(staff),
        category=category if isinstance(category, discord.CategoryChannel) else None,
        overwrites=overwrites,
        topic=f"Tiket staff untuk {staff.display_name} ({staff.id})",
    )


def format_currency(amount: int) -> str:
    """Format amount as currency string."""
    return f"Rp {amount:,.0f}".replace(",", ".")


def get_current_period() -> str:
    """Get current payment period (YYYY-MM format)."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m")
