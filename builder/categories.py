"""
builder/categories.py
Alle Discord-acties die met categorieën te maken hebben.
"""

import discord


async def create_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    """Maakt een categorie aan, of geeft de bestaande terug als de naam al bestaat."""
    existing = discord.utils.get(guild.categories, name=name)
    if existing:
        return existing
    return await guild.create_category(name=name, reason="AI-Discord-Builder: categorie aangemaakt")


def find_category(guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
    return discord.utils.get(guild.categories, name=name)
