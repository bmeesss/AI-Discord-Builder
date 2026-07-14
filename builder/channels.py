"""
builder/channels.py
Alle Discord-acties die met kanalen te maken hebben: aanmaken, verwijderen,
verplaatsen. Kanaalnamen worden genormaliseerd naar Discord's conventies
(lowercase, koppeltekens i.p.v. spaties).
"""

import re

import discord

from builder.categories import find_category


def normalize_channel_name(raw_name: str) -> str:
    name = raw_name.strip().lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^a-z0-9\-_]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or "kanaal"


async def create_channel(
    guild: discord.Guild,
    name: str,
    category_name: str | None = None,
    channel_type: str = "text",
) -> discord.abc.GuildChannel:
    clean_name = normalize_channel_name(name)
    category = find_category(guild, category_name) if category_name else None

    # Check of kanaal al bestaat (zelfde naam + zelfde categorie)
    existing = discord.utils.get(guild.channels, name=clean_name)
    if existing and (category is None or existing.category == category):
        return existing

    if channel_type == "voice":
        return await guild.create_voice_channel(
            name=clean_name, category=category, reason="AI-Discord-Builder: kanaal aangemaakt"
        )

    return await guild.create_text_channel(
        name=clean_name, category=category, reason="AI-Discord-Builder: kanaal aangemaakt"
    )


async def delete_channel(guild: discord.Guild, name: str) -> bool:
    clean_name = normalize_channel_name(name)
    channel = discord.utils.get(guild.channels, name=clean_name) or discord.utils.get(
        guild.channels, name=name
    )
    if not channel:
        return False
    await channel.delete(reason="AI-Discord-Builder: kanaal verwijderd op verzoek")
    return True


async def move_channel(guild: discord.Guild, name: str, target_category_name: str) -> bool:
    clean_name = normalize_channel_name(name)
    channel = discord.utils.get(guild.channels, name=clean_name) or discord.utils.get(
        guild.channels, name=name
    )
    category = find_category(guild, target_category_name)

    if not channel or not category:
        return False

    await channel.edit(category=category, reason="AI-Discord-Builder: kanaal verplaatst")
    return True
