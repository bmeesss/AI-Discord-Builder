"""
builder/context.py

Creates typed and readable Discord server context for the AI planner.
"""

import discord

from ai.models import ServerContext
from services.context_intelligence import ContextIntelligenceEngine


async def build_server_context(
    guild: discord.Guild,
    user: discord.abc.User | None = None,
    user_request: str = "",
) -> ServerContext:
    return await ContextIntelligenceEngine().build(
        guild=guild,
        user=user,
        user_request=user_request,
    )


def render_server_context(
    context: ServerContext,
) -> str:

    lines = []

    lines.append(
        f"GUILD: {context.guild_name} ({context.guild_id})"
    )

    if context.member_count is not None:
        lines.append(
            f"MEMBERS: {context.member_count}"
        )

    if context.analysis:
        lines.append("")
        lines.append(
            f"SERVER HEALTH SCORE: {context.analysis.health_score}/100"
        )
        lines.append("ISSUES:")
        if context.analysis.issues:
            for issue in context.analysis.issues:
                lines.append(
                    f"- [{issue.severity}] {issue.category}: {issue.message}"
                )
        else:
            lines.append("- None detected")

        lines.append("RECOMMENDATIONS:")
        if context.analysis.recommendations:
            for recommendation in context.analysis.recommendations:
                lines.append(
                    f"- {recommendation}"
                )
        else:
            lines.append("- None")

    # =====================
    # CATEGORIES
    # =====================

    lines.append(
        "EXISTING CATEGORIES:"
    )

    for category in context.categories:

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


    for channel in context.channels:
        category = channel.category_name or "No category"

        lines.append(
            f"- {channel.name} ({channel.type} channel, category: {category})"
        )



    # =====================
    # ROLES
    # =====================

    lines.append("")
    lines.append(
        "EXISTING ROLES:"
    )


    for role in context.roles:
        dangerous = [
            permission
            for permission in role.permissions
            if permission in (
                "administrator",
                "manage_roles",
                "manage_channels",
                "ban_members",
                "kick_members",
            )
        ]

        suffix = ""
        if dangerous:
            suffix = f" (dangerous permissions: {', '.join(dangerous)})"

        lines.append(
            f"- {role.name}{suffix}"
        )

    lines.append("")
    lines.append("BOT PERMISSIONS:")
    if context.permissions.missing_bot_permissions:
        lines.append(
            "- Missing: "
            + ", ".join(context.permissions.missing_bot_permissions)
        )
    else:
        lines.append("- Required permissions available")

    lines.append("")
    lines.append("MEMORY:")
    if context.memories:
        for memory in context.memories:
            lines.append(
                f"- {memory.key}: {memory.value} (confidence {memory.confidence})"
            )
    else:
        lines.append("- No relevant memory")

    lines.append("")
    lines.append("CONVERSATION SUMMARIES:")
    if context.conversations:
        for summary in context.conversations:
            lines.append(
                f"- {summary.summary}"
            )
    else:
        lines.append("- No summaries")

    lines.append("")
    lines.append("TEMPLATE CANDIDATES:")
    if context.templates:
        for template in context.templates:
            lines.append(
                f"- {template.name} v{template.version}: {template.description}"
            )
    else:
        lines.append("- No template candidates")


    return "\n".join(lines)


def get_server_context(
    guild: discord.Guild
) -> str:
    return render_server_context(
        build_server_context(guild)
    )
