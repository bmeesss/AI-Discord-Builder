"""
builder/finder.py

Smart Discord object finder.

Finds:
- Channels
- Categories
- Roles

Supports:
- Emojis
- #channel mentions
- Different spacing
- Hyphens/underscores
- Partial matches
"""

import re
import unicodedata

import discord


def simplify_name(name: str) -> str:
    """
    Makes Discord names easier to compare.

    Examples:
    📜 Server Rules -> server rules
    #rules -> rules
    server-rules -> server rules
    """

    if not name:
        return ""

    name = name.lower().strip()

    # Remove channel mention format
    name = re.sub(
        r"<[#&]?\d+>",
        "",
        name
    )

    # Remove #
    name = name.replace("#", "")

    # Normalize unicode
    name = unicodedata.normalize(
        "NFKD",
        name
    )

    # Remove emojis/symbols
    name = "".join(
        char
        for char in name
        if unicodedata.category(char)[0] not in ("S", "C")
    )

    # Replace separators
    name = re.sub(
        r"[-_]+",
        " ",
        name
    )

    # Remove extra spaces
    name = re.sub(
        r"\s+",
        " ",
        name
    )

    return name.strip()



def match_score(
    search: str,
    target: str
) -> int:

    search = simplify_name(search)
    target = simplify_name(target)

    if not search or not target:
        return 0


    # Exact match
    if search == target:
        return 100


    # Target starts with search
    if target.startswith(search):
        return 80


    # Search inside target
    if search in target:
        return 60


    # Word matching
    search_words = set(
        search.split()
    )

    target_words = set(
        target.split()
    )

    matches = len(
        search_words & target_words
    )

    if matches:
        return 40 + (matches * 5)


    return 0



def find_channel(
    guild: discord.Guild,
    name: str
):
    """
    Finds the best matching channel.
    """

    best = None
    highest_score = 0


    for channel in guild.channels:

        score = match_score(
            name,
            channel.name
        )

        if score > highest_score:
            highest_score = score
            best = channel


    return best



def find_text_channel(
    guild: discord.Guild,
    name: str
):
    channel = find_channel(
        guild,
        name
    )

    if isinstance(
        channel,
        discord.TextChannel
    ):
        return channel

    return None



def find_voice_channel(
    guild: discord.Guild,
    name: str
):
    channel = find_channel(
        guild,
        name
    )

    if isinstance(
        channel,
        discord.VoiceChannel
    ):
        return channel

    return None



def find_category(
    guild: discord.Guild,
    name: str
):
    """
    Finds best matching category.
    """

    best = None
    highest_score = 0


    for category in guild.categories:

        score = match_score(
            name,
            category.name
        )

        if score > highest_score:
            highest_score = score
            best = category


    return best



def find_role(
    guild: discord.Guild,
    name: str
):
    """
    Finds best matching role.
    """

    best = None
    highest_score = 0


    for role in guild.roles:

        score = match_score(
            name,
            role.name
        )

        if score > highest_score:
            highest_score = score
            best = role


    return best