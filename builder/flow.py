"""
builder/flow.py

Shared AI-plan flow used by:
- /ask command
- @mention handler

Responsible for:
- Creating AI plans
- Loading server context
- Logging conversations
- Saving rollback history
- Formatting plan embeds

Does NOT:
- Send Discord messages
- Execute actions
- Handle buttons/views
"""

import json
import logging

import discord

from ai.client import AIPlanError
from builder.history import add_action
from services.ai_planning_service import AIPlanningService

from database.conversations import save_conversation


logger = logging.getLogger(
    "ai_discord_builder.flow"
)


# =====================================
# DATABASE LOGGING
# =====================================


def log_conversation(
    guild_id: int,
    user_id: int,
    username: str,
    message: str,
    response: str,
):
    """
    Save conversation safely.

    Database failures should never break
    the Discord flow.
    """

    try:

        save_conversation(
            guild_id=guild_id,
            user_id=user_id,
            username=username,
            message=message,
            response=response,
        )


    except Exception:

        logger.exception(
            "Conversation logging failed"
        )





def log_action_history(
    guild_id: int,
    user_id: int,
    results: list,
):
    """
    Save successful executed actions
    for rollback.

    Only successful actions are saved.
    """

    for result in results:

        if not result.success:
            continue


        try:

            add_action(
                guild_id=guild_id,
                action=result.action,
                user_id=user_id,
            )


        except Exception:

            logger.exception(
                "Action history save failed"
            )



# =====================================
# EMBED FORMAT
# =====================================


def format_plan_embed(
    summary: str,
    actions: list[dict],
    risk: str = "low",
    recommendations: list[str] | None = None,
):

    embed = discord.Embed(
        title="🤖 AI Server Builder — Proposed Plan",
        description=summary,
        color=_risk_color(risk),
    )


    embed.add_field(
        name="Risk",
        value=risk.upper(),
        inline=False,
    )


    categories = [
        x["name"]
        for x in actions
        if x.get("type") == "create_category"
    ]


    channels = [
        x
        for x in actions
        if x.get("type") == "create_channel"
    ]


    roles = [
        x
        for x in actions
        if x.get("type") == "create_role"
    ]


    other = [
        x
        for x in actions
        if x.get("type")
        not in (
            "create_category",
            "create_channel",
            "create_role",
        )
    ]



    if categories:

        embed.add_field(
            name="📁 Categories",
            value="\n".join(
                f"- {x}"
                for x in categories
            ),
            inline=False,
        )



    if channels:

        lines = []


        for channel in channels:

            icon = (
                "🔊"
                if channel.get("channel_type") == "voice"
                else "💬"
            )


            category = ""

            if channel.get("category"):

                category = (
                    f" ({channel['category']})"
                )


            lines.append(
                f"{icon} #{channel['name']}{category}"
            )



        embed.add_field(
            name="Channels",
            value="\n".join(lines),
            inline=False,
        )



    if roles:

        embed.add_field(
            name="🎭 Roles",
            value="\n".join(
                f"- {r['name']}"
                for r in roles
            ),
            inline=False,
        )



    if other:

        embed.add_field(
            name="Other",
            value="\n".join(
                f"- {x.get('type')}"
                for x in other
            ),
            inline=False,
        )



    if recommendations:

        embed.add_field(
            name="Recommendations",
            value="\n".join(
                f"- {item}"
                for item in recommendations[:5]
            ),
            inline=False,
        )


    embed.set_footer(
        text=f"{len(actions)} action(s) • Confirm?"
    )


    return embed


def _risk_color(
    risk: str
):

    if risk == "critical":
        return discord.Color.red()

    if risk == "high":
        return discord.Color.orange()

    if risk == "medium":
        return discord.Color.gold()

    return discord.Color.green()



# =====================================
# AI PLAN BUILDER
# =====================================


async def build_plan(
    guild: discord.Guild,
    user: discord.abc.User,
    prompt: str,
):

    logger.info(
        "Building plan for %s",
        prompt,
    )


    # -----------------------------
    # AI REQUEST
    # -----------------------------


    planning_service = AIPlanningService()


    try:

        logger.info(
            "Sending request to AI"
        )


        plan = await planning_service.build_plan(
            guild=guild,
            user=user,
            prompt=prompt,
        )


        logger.info(
            "AI returned plan"
        )


    except AIPlanError:

        raise



    except Exception as e:

        logger.exception(
            "AI generation failed"
        )


        raise AIPlanError(
            str(e)
        )



    # -----------------------------
    # SAVE CONVERSATION
    # -----------------------------


    try:

        response = json.dumps(
            plan,
            indent=2,
            default=str,
        )


    except Exception:

        response = str(plan)



    log_conversation(
        guild_id=guild.id,
        user_id=user.id,
        username=str(user),
        message=prompt,
        response=response,
    )


    return plan
