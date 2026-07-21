import discord
from typing import Optional, Union
from config import ROLE_ADMIN_ID, ROLE_STAFF_ID

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


def calculate_rate(role: str, manga: str) -> int:
    """Calculate base rate with popular series bonus.
    
    Base rates:
    - TL (Translator): 3000
    - PR (Proofreader): 3000
    - CL (Cleaner): 3000
    
    Popular series bonus: +30%
    Maximum rates: TL 15000, PR 12000, CL 8000
    """
    base = 3000
    
    # Apply popular series bonus
    if manga in POPULAR_SERIES:
        base = int(base * 1.3)
    
    # Apply maximum caps
    max_rates = {
        "TL": 15000,
        "PR": 12000,
        "CL": 8000,
    }
    
    return min(base, max_rates.get(role, 8000))


async def find_ticket(guild: discord.Guild, staff_id: int) -> Optional[discord.TextChannel]:
    """Find ticket channel by staff member's name or ID."""
    staff = guild.get_member(staff_id)
    if not staff:
        return None
    
    # Search for channel with staff name
    for channel in guild.text_channels:
        if staff.name.lower() in channel.name.lower() or str(staff.id) in channel.name:
            return channel
    
    return None


def format_currency(amount: int) -> str:
    """Format amount as currency string."""
    return f"Rp {amount:,.0f}".replace(",", ".")


def get_current_period() -> str:
    """Get current payment period (YYYY-MM format)."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m")
