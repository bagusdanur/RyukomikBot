from types import SimpleNamespace
import discord

from helpers.utils import find_ticket


async def test_find_ticket_accepts_staff_ticket_inside_recruitment_category():
    staff = SimpleNamespace(id=123)
    channel = SimpleNamespace(
        name="🔒・tiket-staff",
        topic="Tiket staff untuk Staff (123)",
        category_id=999,
    )
    guild = SimpleNamespace(text_channels=[channel], get_member=lambda member_id: staff if member_id == 123 else None)
    assert await find_ticket(guild, staff.id) is channel


async def test_find_ticket_uses_private_owner_overwrite_when_legacy_topic_has_no_id():
    staff = SimpleNamespace(id=123)
    channel = SimpleNamespace(
        name="🔒・tiket-staff",
        topic="Tiket rekrutmen lama",
        category_id=999,
        overwrites_for=lambda member: discord.PermissionOverwrite(view_channel=member.id == 123),
    )
    guild = SimpleNamespace(text_channels=[channel], get_member=lambda member_id: staff if member_id == 123 else None)
    assert await find_ticket(guild, staff.id) is channel
