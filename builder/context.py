"""
builder/context.py

Creates a readable Discord server snapshot
for the AI planner.
"""

import discord


def get_server_context(
    guild: discord.Guild
) -> str:

    lines = []


    # =====================
    # CATEGORIES
    # =====================

    lines.append(
        "EXISTING CATEGORIES:"
    )

    for category in guild.categories:

        lines.append(
            f"- {category.name}"
        )



    # =====================
    # CHANNELS
    # =====================

    lines.append("")
    lines.append(
        "EXISTING CHANNELS:"
    )


    for channel in guild.channels:


        if isinstance(
            channel,
            discord.TextChannel
        ):

            category = (
                channel.category.name
                if channel.category
                else "No category"
            )

            lines.append(
                f"- {channel.name} (text channel, category: {category})"
            )


        elif isinstance(
            channel,
            discord.VoiceChannel
        ):

            category = (
                channel.category.name
                if channel.category
                else "No category"
            )

            lines.append(
                f"- {channel.name} (voice channel, category: {category})"
            )



    # =====================
    # ROLES
    # =====================

    lines.append("")
    lines.append(
        "EXISTING ROLES:"
    )


    for role in guild.roles:

        if role.name != "@everyone":

            lines.append(
                f"- {role.name}"
            )


    return "\n".join(lines)