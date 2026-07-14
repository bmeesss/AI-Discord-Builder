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
    Keeps category names clean but allows normal capitalization.
    """
    return name.strip()


async def create_category(
    guild: discord.Guild,
    name: str
) -> discord.CategoryChannel:
    """
    Creates a category or returns the existing one if it already exists.
    """

    clean_name = normalize_category_name(name)

    existing = discord.utils.get(
        guild.categories,
        name=clean_name
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
    Finds a category case-insensitive.
    """

    name = normalize_category_name(name).lower()

    for category in guild.categories:
        if category.name.lower() == name:
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

    new_name = normalize_category_name(new_name)

    # Already the same name
    if category.name == new_name:
        return True

    await category.edit(
        name=new_name,
        reason="AI-Discord-Builder: category renamed"
    )

    return True