```python
"""
builder/executor.py

Executes validated AI action plans.

Features:
- Create/Delete/Rename/Move channels
- Create/Rename/Delete categories
- Create/Rename/Delete roles
- Send messages

Database history is handled by commands/ask.py.

IMPORTANT:
This file does NOT save history.
It only enriches action dictionaries with rollback
information before returning ActionResult objects.
"""

import logging

import discord

from builder import categories, channels, roles

from builder.finder import (
    find_channel,
)


logger = logging.getLogger(
    "ai_discord_builder.executor"
)


class ActionResult:

    def __init__(
        self,
        action: dict,
        success: bool,
        detail: str
    ):
        self.action = action
        self.success = success
        self.detail = detail


    def __str__(self):

        icon = "✅" if self.success else "❌"

        return f"{icon} {self.detail}"



async def execute_plan(
    guild: discord.Guild,
    actions: list[dict]
) -> list[ActionResult]:

    results = []

    for action in actions:

        action_type = action.get("type")

        try:

            result = await _execute_single_action(
                guild,
                action
            )

            results.append(result)


        except discord.Forbidden:

            results.append(
                ActionResult(
                    action,
                    False,
                    f"No permission for {action_type}"
                )
            )


        except discord.HTTPException as e:

            results.append(
                ActionResult(
                    action,
                    False,
                    f"Discord error: {e}"
                )
            )


        except Exception as e:

            logger.exception(
                "Action failed"
            )

            results.append(
                ActionResult(
                    action,
                    False,
                    f"Error: {e}"
                )
            )


    return results





async def _execute_single_action(
    guild: discord.Guild,
    action: dict
):

    action_type = action["type"]


    # =========================
    # CATEGORY ACTIONS
    # =========================


    if action_type == "create_category":

        category = await categories.create_category(
            guild,
            action["name"]
        )

        action["category_id"] = category.id


        return ActionResult(
            action,
            True,
            f"Category {category.name} created"
        )



    if action_type == "rename_category":

        category = discord.utils.get(
            guild.categories,
            name=action["old_name"]
        )


        if not category:

            return ActionResult(
                action,
                False,
                "Category not found"
            )


        action["category_id"] = category.id


        ok = await categories.rename_category(
            guild,
            action["old_name"],
            action["new_name"]
        )


        if ok:

            return ActionResult(
                action,
                True,
                "Category renamed"
            )


        return ActionResult(
            action,
            False,
            "Category rename failed"
        )



    # =========================
    # CHANNEL ACTIONS
    # =========================


    if action_type == "create_channel":

        channel = await channels.create_channel(
            guild,
            action["name"],
            action.get("category"),
            action.get(
                "channel_type",
                "text"
            )
        )


        action["channel_id"] = channel.id


        if channel.category:

            action["category_id"] = (
                channel.category.id
            )


        return ActionResult(
            action,
            True,
            f"Channel #{channel.name} created"
        )



    if action_type == "rename_channel":

        channel = find_channel(
            guild,
            action["old_name"]
        )


        if not channel:

            return ActionResult(
                action,
                False,
                "Channel not found"
            )


        action["channel_id"] = channel.id


        ok = await channels.rename_channel(
            guild,
            action["old_name"],
            action["new_name"]
        )


        if ok:

            return ActionResult(
                action,
                True,
                "Channel renamed"
            )


        return ActionResult(
            action,
            False,
            "Rename failed"
        )



    if action_type == "delete_channel":

        channel = find_channel(
            guild,
            action["name"]
        )


        if not channel:

            return ActionResult(
                action,
                False,
                "Channel not found"
            )


        action["channel_id"] = channel.id


        await channel.delete(
            reason="AI-Discord-Builder"
        )


        return ActionResult(
            action,
            True,
            "Channel deleted"
        )



    if action_type == "move_channel":

        channel = find_channel(
            guild,
            action["name"]
        )


        if not channel:

            return ActionResult(
                action,
                False,
                "Channel not found"
            )


        action["channel_id"] = channel.id


        if channel.category:

            action["old_category_id"] = (
                channel.category.id
            )


        ok = await channels.move_channel(
            guild,
            action["name"],
            action["target_category"]
        )


        if ok:

            return ActionResult(
                action,
                True,
                "Channel moved"
            )


        return ActionResult(
            action,
            False,
            "Move failed"
        )



    # =========================
    # SEND MESSAGE
    # =========================


    if action_type == "send_message":

        channel = find_channel(
            guild,
            action["channel"]
        )


        if not channel:

            return ActionResult(
                action,
                False,
                "Channel not found"
            )


        if not isinstance(
            channel,
            discord.TextChannel
        ):

            return ActionResult(
                action,
                False,
                "Channel is not text"
            )


        message = await channel.send(
            action["content"]
        )


        action["channel_id"] = channel.id
        action["message_id"] = message.id


        return ActionResult(
            action,
            True,
            f"Message sent in #{channel.name}"
        )



    # =========================
    # ROLE ACTIONS
    # =========================


    if action_type == "create_role":

        role = await roles.create_role(
            guild,
            action["name"],
            action.get(
                "permissions",
                []
            ),
            action.get("color"),
            action.get(
                "mentionable",
                True
            ),
            action.get(
                "hoist",
                True
            )
        )


        action["role_id"] = role.id


        return ActionResult(
            action,
            True,
            f"Role {role.name} created"
        )



    if action_type == "rename_role":

        role = discord.utils.get(
            guild.roles,
            name=action["old_name"]
        )


        if not role:

            return ActionResult(
                action,
                False,
                "Role not found"
            )


        action["role_id"] = role.id


        ok = await roles.rename_role(
            guild,
            action["old_name"],
            action["new_name"]
        )


        if ok:

            return ActionResult(
                action,
                True,
                "Role renamed"
            )


        return ActionResult(
            action,
            False,
            "Rename failed"
        )



    if action_type == "delete_role":

        role = discord.utils.get(
            guild.roles,
            name=action["name"]
        )


        if not role:

            return ActionResult(
                action,
                False,
                "Role not found"
            )


        action["role_id"] = role.id


        ok = await roles.delete_role(
            guild,
            action["name"]
        )


        if ok:

            return ActionResult(
                action,
                True,
                "Role deleted"
            )


        return ActionResult(
            action,
            False,
            "Delete failed"
        )



    return ActionResult(
        action,
        False,
        f"Unknown action: {action_type}"
    )
```
