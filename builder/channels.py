"""
builder/channels.py

All Discord actions related to channels:
- Create
- Delete
- Move
- Rename

Supports:
- Text channels
- Voice channels
- Emoji prefixed channels
"""

import re
import unicodedata

import discord

from builder.categories import find_category


def clean_discord_name(name: str) -> str:
    """
    Removes emojis and Discord formatting from names.
    Example:
    🔊 Algemeen -> algemeen
    """

    name = unicodedata.normalize("NFKD", name)

    # remove emojis/symbols
    name = "".join(
        char for char in name
        if unicodedata.category(char)[0] not in ("S", "C")
    )

    return name.strip()


def normalize_channel_name(raw_name: str) -> str:
    """
    Converts channel names to Discord format.
    """

    name = clean_discord_name(raw_name)

    name = name.lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(
        r"[^a-z0-9\-_]",
        "",
        name
    )

    name = re.sub(
        r"-{2,}",
        "-",
        name
    )

    return name.strip("-") or "channel"



def find_channel(
    guild: discord.Guild,
    name: str
):

    """
    Finds text or voice channel.
    Supports emoji names.
    """

    clean = normalize_channel_name(name)


    for channel in guild.channels:

        channel_clean = normalize_channel_name(
            channel.name
        )

        if channel_clean == clean:
            return channel


    return None



async def create_channel(
    guild: discord.Guild,
    name: str,
    category_name: str | None = None,
    channel_type: str = "text",
):

    clean_name = normalize_channel_name(name)

    category = (
        find_category(
            guild,
            category_name
        )
        if category_name
        else None
    )


    existing = find_channel(
        guild,
        clean_name
    )


    if existing:
        return existing



    if channel_type == "voice":

        return await guild.create_voice_channel(
            name=clean_name,
            category=category,
            reason="AI-Discord-Builder: created voice channel"
        )


    return await guild.create_text_channel(
        name=clean_name,
        category=category,
        reason="AI-Discord-Builder: created text channel"
    )



async def delete_channel(
    guild: discord.Guild,
    name: str
) -> bool:


    channel = find_channel(
        guild,
        name
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
    target_category_name: str
) -> bool:


    channel = find_channel(
        guild,
        name
    )


    category = find_category(
        guild,
        target_category_name
    )


    if not channel or not category:
        return False



    await channel.edit(
        category=category,
        reason="AI-Discord-Builder: moved channel"
    )


    return True




async def rename_channel(
    guild: discord.Guild,
    old_name: str,
    new_name: str
) -> bool:


    channel = find_channel(
        guild,
        old_name
    )


    if not channel:
        return False



    new_clean = normalize_channel_name(
        new_name
    )


    # already correct
    if normalize_channel_name(channel.name) == new_clean:
        return True



    existing = find_channel(
        guild,
        new_clean
    )


    if existing:
        return True



    await channel.edit(
        name=new_clean,
        reason="AI-Discord-Builder: renamed channel"
    )


    return True