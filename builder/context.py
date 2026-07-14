"""
builder/context.py

Creates a readable snapshot of the Discord server
for the AI planner.
"""

import discord


def get_server_context(guild: discord.Guild) -> str:

    context = []

    context.append("EXISTING CATEGORIES:")

    for category in guild.categories:
        context.append(
            f"- {category.name}"
        )


    context.append("")
    context.append("EXISTING CHANNELS:")

    for channel in guild.channels:

        if isinstance(channel, discord.TextChannel):
            context.append(
                f"- #{channel.name} (category: {channel.category.name if channel.category else 'None'})"
            )

        elif isinstance(channel, discord.VoiceChannel):
            context.append(
                f"- 🔊 {channel.name} (category: {channel.category.name if channel.category else 'None'})"
            )


    context.append("")
    context.append("EXISTING ROLES:")

    for role in guild.roles:

        if role.name != "@everyone":
            context.append(
                f"- {role.name}"
            )


    return "\n".join(context)