"""
builder/categories.py
All Discord actions related to categories.
"""

import discord


async def create_category(
    guild: discord.Guild,
    name: str
) -> discord.CategoryChannel:
    """Creates a category or returns the existing one if it already exists."""

    existing = discord.utils.get(
        guild.categories,
        name=name
    )

    if existing:
        return existing

    return await guild.create_category(
        name=name,
        reason="AI-Discord-Builder: category created"
    )


def find_category(
    guild: discord.Guild,
    name: str
) -> discord.CategoryChannel | None:
    return discord.utils.get(
        guild.categories,
        name=name
    )


async def rename_category(
    guild: discord.Guild,
    old_name: str,
    new_name: str
) -> bool:
    """Renames an existing category."""

    category = find_category(
        guild,
        old_name
    )

    if not category:
        return False

    await category.edit(
        name=new_name,
        reason="AI-Discord-Builder: category renamed"
    )

    return True