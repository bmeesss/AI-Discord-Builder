"""
builder/finder.py

Smart Discord object finder.

Finds:
- Channels
- Categories
- Roles

Supports:
- Discord IDs
- Emojis
- #channel mentions
- Different spacing
- Hyphens/underscores
- Partial matches
"""

import re
import unicodedata

import discord



# =========================
# NAME CLEANING
# =========================


def simplify_name(
    name: str
) -> str:
    """
    Makes Discord names easier to compare.

    Examples:
    📜 Server Rules -> server rules
    #rules -> rules
    server-rules -> server rules
    """

    if not name:
        return ""


    name = str(name).lower().strip()


    # Discord mentions
    name = re.sub(
        r"<[#&]?\d+>",
        "",
        name
    )


    # Remove #
    name = name.replace(
        "#",
        ""
    )


    # Unicode normalize
    name = unicodedata.normalize(
        "NFKD",
        name
    )


    # Remove emojis and symbols
    name = "".join(
        char
        for char in name
        if unicodedata.category(char)[0]
        not in ("S", "C")
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





# =========================
# MATCHING
# =========================


def match_score(
    search: str,
    target: str
) -> int:
    """
    Calculates similarity score.

    100 = exact
    80  = starts with
    60  = contains
    40+ = word match
    """

    search = simplify_name(
        search
    )

    target = simplify_name(
        target
    )


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

        return 40 + (
            matches * 5
        )


    return 0





# =========================
# CHANNEL FINDER
# =========================


def find_channel(
    guild: discord.Guild,
    name: str
):
    """
    Finds best matching channel.

    Supports:
    - Channel names
    - #mentions
    - Discord channel IDs
    - Emoji names
    """

    if not name:
        return None



    # Discord ID support

    if str(name).isdigit():

        channel = guild.get_channel(
            int(name)
        )

        if channel:
            return channel



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





# =========================
# CATEGORY FINDER
# =========================


def find_category(
    guild: discord.Guild,
    name: str
):
    """
    Finds best matching category.
    """


    if not name:
        return None



    if str(name).isdigit():

        category = guild.get_channel(
            int(name)
        )

        if isinstance(
            category,
            discord.CategoryChannel
        ):

            return category



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





# =========================
# ROLE FINDER
# =========================


def find_role(
    guild: discord.Guild,
    name: str
):
    """
    Finds best matching role.

    Supports:
    - Names
    - IDs
    """


    if not name:
        return None



    if str(name).isdigit():

        role = guild.get_role(
            int(name)
        )

        if role:
            return role



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