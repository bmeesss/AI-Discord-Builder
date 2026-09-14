
"""
builder/rollback.py

Handles undoing previous AI Discord Builder actions.

Supported:
- Delete created channels
- Restore renamed channels
- Delete created categories
- Restore renamed categories
- Delete created roles
- Restore renamed roles
- Delete sent messages
- Restore moved channels
"""

import asyncio
import logging

import discord

from builder import history

from builder.finder import (
    find_channel,
    find_role,
    find_category
)


logger = logging.getLogger(
    "ai_discord_builder.rollback"
)


class RollbackResult:

    def __init__(
        self,
        success: bool,
        detail: str
    ):
        self.success = success
        self.detail = detail


    def __str__(self):

        icon = "✅" if self.success else "❌"

        return f"{icon} {self.detail}"



async def safe_discord_action(coro):
    """
    Prevent Discord API calls from hanging forever.
    """

    try:

        return await asyncio.wait_for(
            coro,
            timeout=10
        )

    except asyncio.TimeoutError:

        raise Exception(
            "Discord API timeout"
        )



async def rollback_actions(
    guild: discord.Guild,
    amount: int = 1
):

    actions = await history.get_last_actions(
        guild.id,
        amount
    )


    if not actions:

        return [
            RollbackResult(
                False,
                "No history found"
            )
        ]


    results = []

    successful_rollbacks = 0


    for entry in reversed(actions):

        try:

            result = await rollback_single_action(
                guild,
                entry["action"]
            )

        except Exception as e:

            logger.exception(
                "Rollback failed"
            )

            result = RollbackResult(
                False,
                f"Error: {e}"
            )


        results.append(result)


        if result.success:
            successful_rollbacks += 1



    # Remove ONLY successful rollback entries
    if successful_rollbacks:

        await history.remove_last_actions(
            guild.id,
            successful_rollbacks
        )


    return results





async def rollback_single_action(
    guild: discord.Guild,
    action: dict
):

    action_type = action.get(
        "type"
    )


    # =====================
    # CHANNELS
    # =====================


    if action_type == "create_channel":

        channel = None


        if action.get("channel_id"):

            channel = guild.get_channel(
                int(action["channel_id"])
            )


        if not channel:

            channel = find_channel(
                guild,
                action.get("name")
            )


        if not channel:

            return RollbackResult(
                False,
                "Channel not found"
            )


        await safe_discord_action(
            channel.delete(
                reason="AI rollback"
            )
        )


        return RollbackResult(
            True,
            f"Deleted #{channel.name}"
        )



    if action_type == "rename_channel":

        channel = None


        if action.get("channel_id"):

            channel = guild.get_channel(
                int(action["channel_id"])
            )


        if not channel:

            channel = find_channel(
                guild,
                action.get("new_name")
            )


        if not channel:

            return RollbackResult(
                False,
                "Channel not found"
            )


        await safe_discord_action(
            channel.edit(
                name=action["old_name"],
                reason="AI rollback"
            )
        )


        return RollbackResult(
            True,
            "Channel restored"
        )



    if action_type == "move_channel":

        channel = None


        if action.get("channel_id"):

            channel = guild.get_channel(
                int(action["channel_id"])
            )


        if not channel:

            channel = find_channel(
                guild,
                action.get("name")
            )


        if not channel:

            return RollbackResult(
                False,
                "Channel not found"
            )


        category = None


        if action.get("old_category_id"):

            category = guild.get_channel(
                int(action["old_category_id"])
            )


        await safe_discord_action(
            channel.edit(
                category=category,
                reason="AI rollback"
            )
        )


        return RollbackResult(
            True,
            "Channel moved back"
        )



    # =====================
    # CATEGORIES
    # =====================


    if action_type == "create_category":

        category = None


        if action.get("category_id"):

            category = guild.get_channel(
                int(action["category_id"])
            )


        if not category:

            category = find_category(
                guild,
                action.get("name")
            )


        if not category:

            return RollbackResult(
                False,
                "Category not found"
            )


        await safe_discord_action(
            category.delete(
                reason="AI rollback"
            )
        )


        return RollbackResult(
            True,
            "Category deleted"
        )



    if action_type == "rename_category":

        category = None


        if action.get("category_id"):

            category = guild.get_channel(
                int(action["category_id"])
            )


        if not category:

            category = find_category(
                guild,
                action.get("new_name")
            )


        if not category:

            return RollbackResult(
                False,
                "Category not found"
            )


        await safe_discord_action(
            category.edit(
                name=action["old_name"],
                reason="AI rollback"
            )
        )


        return RollbackResult(
            True,
            "Category restored"
        )



    # =====================
    # ROLES
    # =====================


    if action_type == "create_role":

        role = None


        if action.get("role_id"):

            role = guild.get_role(
                int(action["role_id"])
            )


        if not role:

            role = find_role(
                guild,
                action.get("name")
            )


        if not role:

            return RollbackResult(
                False,
                "Role not found"
            )


        await safe_discord_action(
            role.delete(
                reason="AI rollback"
            )
        )


        return RollbackResult(
            True,
            "Role deleted"
        )



    if action_type == "rename_role":

        role = None


        if action.get("role_id"):

            role = guild.get_role(
                int(action["role_id"])
            )


        if not role:

            role = find_role(
                guild,
                action.get("new_name")
            )


        if not role:

            return RollbackResult(
                False,
                "Role not found"
            )


        await safe_discord_action(
            role.edit(
                name=action["old_name"],
                reason="AI rollback"
            )
        )


        return RollbackResult(
            True,
            "Role restored"
        )



    # =====================
    # MESSAGE ROLLBACK
    # =====================


    if action_type == "send_message":

        message_id = action.get(
            "message_id"
        )

        channel_id = action.get(
            "channel_id"
        )


        if not message_id or not channel_id:

            return RollbackResult(
                False,
                "Missing message information"
            )


        channel = guild.get_channel(
            int(channel_id)
        )


        if not channel:

            return RollbackResult(
                False,
                "Message channel missing"
            )


        try:

            message = await safe_discord_action(
                channel.fetch_message(
                    int(message_id)
                )
            )


            await safe_discord_action(
                message.delete()
            )


            return RollbackResult(
                True,
                f"Deleted message in #{channel.name}"
            )


        except discord.NotFound:

            return RollbackResult(
                False,
                "Message already deleted"
            )


        except discord.Forbidden:

            return RollbackResult(
                False,
                "Missing permission to delete message"
            )



    return RollbackResult(
        False,
        f"Unsupported: {action_type}"
    )

