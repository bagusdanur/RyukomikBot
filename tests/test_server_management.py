from types import SimpleNamespace

import discord

from server_management import (
    _find_text_channel,
    _plain_name,
    build_goodbye_embed,
    build_welcome_embed,
    build_welcome_view,
)


def test_plain_name_handles_discord_channel_decoration():
    assert _plain_name("👋・welcome-goodbye") == "welcome-goodbye"
    assert _plain_name("📜・Peraturan") == "peraturan"


def test_channel_lookup_does_not_create_or_rearrange_channels():
    welcome = SimpleNamespace(name="👋・welcome", id=10)
    other = SimpleNamespace(name="general", id=11)
    guild = SimpleNamespace(text_channels=[other, welcome], get_channel=lambda _id: None)

    # Keep this test independent from discord.py's concrete TextChannel class.
    original = discord.TextChannel
    try:
        discord.TextChannel = SimpleNamespace
        assert _find_text_channel(guild, names=("welcome",)) is welcome
    finally:
        discord.TextChannel = original


def test_welcome_and_goodbye_cards_are_mobile_friendly():
    avatar = SimpleNamespace(url="https://example.invalid/avatar.png")
    guild = SimpleNamespace(member_count=22)
    member = SimpleNamespace(
        mention="<@123>",
        display_name="Nama_Test",
        display_avatar=avatar,
        guild=guild,
    )
    welcome = build_welcome_embed(member)
    goodbye = build_goodbye_embed(member)

    assert welcome.title == "Selamat Datang di Ryukomik!"
    assert "Rules" in welcome.description
    assert len(welcome.fields) <= 3
    assert goodbye.title == "Sampai Jumpa"


def test_welcome_view_links_to_existing_channels_only():
    channels = [
        SimpleNamespace(name="・rules", id=10),
        SimpleNamespace(name="・ambil-role", id=11),
        SimpleNamespace(name="・staff-rekrutmen", id=12),
    ]
    guild = SimpleNamespace(
        id=99,
        text_channels=channels,
        get_channel=lambda channel_id: next(
            (channel for channel in channels if channel.id == channel_id),
            None,
        ),
    )
    original = discord.TextChannel
    try:
        discord.TextChannel = SimpleNamespace
        view = build_welcome_view(guild)
    finally:
        discord.TextChannel = original

    assert view is not None
    assert [button.label for button in view.children] == [
        "Baca Rules",
        "Ambil Role",
        "Info Rekrutmen",
    ]
    assert view.children[0].url == "https://discord.com/channels/99/10"
