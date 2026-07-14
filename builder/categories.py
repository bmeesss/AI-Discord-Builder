"""
builder/categories.py

All Discord actions related to categories:
- Create
- Find
- Rename
"""

import discord


def normalize_category_name(name: str) -> str:
    """
    Cleans category names for comparison.
    Keeps normal capitalization and removes extra spaces.
    """
    return name.strip()


def simplify_name(name: str) -> str:
    """
    Removes emojis and special symbols for better matching.
    Example:
    "📢 Nieuws" -> "nieuws"
    """

    name = name.lower().strip()

    return "".join(
        c for c in name
        if c.isalnum() or c in " _-"
    ).strip()


async def create_category(
    guild: discord.Guild,
    name: str
) -> discord.CategoryChannel:
    """
    Creates a category or returns the existing one.
    """

    clean_name = normalize_category_name(name)

    existing = find_category(
        guild,
        clean_name
    )

    if existing:
        return existing

    return await guild.create_category(
        name=clean_name,
        reason="AI-Discord-Builder: category created"
    )


def find_category(
    guild: discord.Guild,
    name: str
) -> discord.CategoryChannel | None:
    """
    Finds a category.

    Supports:
    - Different capitalization
    - Emojis
    - Extra symbols
    """

    search = simplify_name(name)

    for category in guild.categories:

        category_name = simplify_name(
            category.name
        )

        if category_name == search:
            return category

    return None


async def rename_category(
    guild: discord.Guild,
    old_name: str,
    new_name: str
) -> bool:
    """
    Renames an existing category.
    """

    category = find_category(
        guild,
        old_name
    )

    if not category:
        return False

    new_name = normalize_category_name(
        new_name
    )

    if category.name == new_name:
        return True

    await category.edit(
        name=new_name,
        reason="AI-Discord-Builder: category renamed"
    )

    return True