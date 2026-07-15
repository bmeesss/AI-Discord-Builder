"""
builder/flow.py

Shared AI-plan flow used by both /ask and the future @mention handler.

This module is responsible for:
- building an AI plan for a given prompt (server context + AI call)
- logging conversations to Supabase
- logging successful action history to Supabase
- rendering the plan as a Discord embed

It does NOT send any Discord responses (no interaction.response,
no followup.send, no views) and does NOT execute plans. Callers own
the Discord-specific parts (how the prompt is received, how the
response is sent, when confirmation happens).
"""

import logging

import json

import discord

from ai.client import AIClient, AIPlanError
from builder.context import get_server_context
from builder.executor import ActionResult
from builder.history import add_action

from database.conversations import save_conversation

logger = logging.getLogger("ai_discord_builder.flow")


# =========================
# DATABASE LOGGING HELPERS
# =========================

def _log_conversation(
    guild_id: int,
    user_id: int,
    username: str,
    message: str,
    response: str,
) -> None:
    """Save a conversation row to Supabase.

    Database failures are logged but never break the Discord flow.
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
        logger.warning(
            "Could not save conversation (guild=%s, user=%s)",
            guild_id,
            user_id,
            exc_info=True,
        )


def _log_action_history(
    guild_id: int,
    user_id: int,
    results: list[ActionResult],
) -> None:
    """Store executed actions so plans can be rolled back later.

    IMPORTANT: this takes the ActionResult list returned by
    execute_plan(), NOT the original AI-generated action list.
    executor.py enriches each action dict in-place with rollback data
    (message_id, channel_id, created category/role ids, ...) while it
    runs, so ActionResult.action is the only reliable, up-to-date
    representation of what actually happened.

    Only successful actions are persisted: a failed action never
    touched the server, so there is nothing to roll back and saving
    it would just pollute the history table.

    Each action is saved independently: one failing insert never
    blocks the rest of the history, and a database error here can
    never crash the bot.

    This is the ONLY place in the codebase that should write to the
    actions history table. Do not call add_action() anywhere else
    (e.g. executor.py), or duplicates will come back.
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
            logger.warning(
                "Could not save action history (guild=%s, action=%s)",
                guild_id,
                result.action.get("type"),
                exc_info=True,
            )


# =========================
# PLAN EMBED
# =========================

def format_plan_embed(summary: str, actions: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="🤖 AI Server Builder — Proposed Plan",
        description=summary,
        color=discord.Color.blurple(),
    )

    categories = [
        a["name"]
        for a in actions
        if a["type"] == "create_category"
    ]

    channels = [
        a
        for a in actions
        if a["type"] == "create_channel"
    ]

    roles = [
        a
        for a in actions
        if a["type"] == "create_role"
    ]

    other = [
        a
        for a in actions
        if a["type"] not in ("create_category", "create_channel", "create_role")
    ]

    if categories:
        embed.add_field(
            name="📁 Categories",
            value="\n".join(f"- {x}" for x in categories),
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
                category = f" ({channel['category']})"

            lines.append(f"{icon} #{channel['name']}{category}")

        embed.add_field(
            name="Channels",
            value="\n".join(lines),
            inline=False,
        )

    if roles:
        embed.add_field(
            name="🎭 Roles",
            value="\n".join(f"- {r['name']}" for r in roles),
            inline=False,
        )

    if other:
        embed.add_field(
            name="Other",
            value="\n".join(f"- {x['type']}" for x in other),
            inline=False,
        )

    embed.set_footer(text=f"{len(actions)} action(s) • Confirm?")

    return embed


# =========================
# PLAN BUILDING
# =========================

async def build_plan(
    guild: discord.Guild,
    user: discord.abc.User,
    prompt: str,
) -> dict:
    """Build an AI plan for the given prompt.

    Steps:
    1. Fetch server context via get_server_context()
    2. Generate a plan via AIClient.generate_plan()
    3. Log the conversation (question + plan) to Supabase
    4. Return the plan dict

    This function is intentionally Discord-response-agnostic: it does
    not defer/reply/followup, does not build any views, and does not
    execute the plan. Callers (slash command, mention handler, ...)
    decide how to surface the result and how confirmation/execution
    happens.

    On AI failure, the conversation is still logged (with the error
    as the response) and AIPlanError is re-raised for the caller to
    handle.
    """
    server_context = get_server_context(guild)

    ai_client = AIClient()

    try:
        plan = await ai_client.generate_plan(prompt, server_context)

        try:
            plan_response = json.dumps(plan, indent=2, default=str)
        except (TypeError, ValueError):
            plan_response = str(plan)

        _log_conversation(
            guild_id=guild.id,
            user_id=user.id,
            username=str(user),
            message=prompt,
            response=plan_response,
        )

        return plan

    except AIPlanError as e:
        _log_conversation(
            guild_id=guild.id,
            user_id=user.id,
            username=str(user),
            message=prompt,
            response=f"ERROR: {e}",
        )
        raise