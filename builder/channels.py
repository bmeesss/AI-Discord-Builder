"""
builder/channels.py

All Discord actions related to channels:
- Create
- Delete
- Move
- Rename
"""

import re

import discord

from builder.categories import find_category


def normalize_channel_name(raw_name: str) -> str:
    """
    Converts a channel name into Discord's preferred format.
    """
    name = raw_name.strip().lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^a-z0-9\-_]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")

    return name or "channel"


async def create_channel(
    guild: discord.Guild,
    name: str,
    category_name: str | None = None,
    channel_type: str = "text",
) -> discord.abc.GuildChannel:

    clean_name = normalize_channel_name(name)
    category = find_category(guild, category_name) if category_name else None

    existing = discord.utils.get(guild.channels, name=clean_name)

    if existing and (category is None or existing.category == category):
        return existing

    if channel_type == "voice":
        return await guild.create_voice_channel(
            name=clean_name,
            category=category,
            reason="AI-Discord-Builder: created voice channel",
        )

    return await guild.create_text_channel(
        name=clean_name,
        category=category,
        reason="AI-Discord-Builder: created text channel",
    )


async def delete_channel(
    guild: discord.Guild,
    name: str,
) -> bool:

    clean_name = normalize_channel_name(name)

    channel = (
        discord.utils.get(guild.channels, name=clean_name)
        or discord.utils.get(guild.channels, name=name)
    )

    if not channel:
        return False

    await channel.delete(
        reason="AI-Discord-Builder: deleted channel"
    )

    return True


async def move_channel(
    guild: discord.Guild,
    name: str,
    target_category_name: str,
) -> bool:

    clean_name = normalize_channel_name(name)

    channel = (
        discord.utils.get(guild.channels, name=clean_name)
        or discord.utils.get(guild.channels, name=name)
    )

    category = find_category(
        guild,
        target_category_name,
    )

    if not channel or not category:
        return False

    await channel.edit(
        category=category,
        reason="AI-Discord-Builder: moved channel",
    )

    return True


async def rename_channel(
    guild: discord.Guild,
    old_name: str,
    new_name: str,
) -> bool:

    old_clean = normalize_channel_name(old_name)
    new_clean = normalize_channel_name(new_name)

    channel = (
        discord.utils.get(guild.channels, name=old_clean)
        or discord.utils.get(guild.channels, name=old_name)
    )

    if not channel:
        return False

    existing = discord.utils.get(
        guild.channels,
        name=new_clean,
    )

    if existing:
        return True

    await channel.edit(
        name=new_clean,
        reason="AI-Discord-Builder: renamed channel",
    )

    return True