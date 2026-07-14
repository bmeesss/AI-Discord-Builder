"""
builder/executor.py
Executes a validated action plan (list of dicts) against a Discord guild.
Each action is handled separately so one failed action does not stop the whole plan.
"""

import logging

import discord

from builder import categories, channels, roles

logger = logging.getLogger("ai_discord_builder.executor")


class ActionResult:
    def __init__(self, action: dict, success: bool, detail: str):
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

    results: list[ActionResult] = []

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
                    f"No permission for action: {action_type}"
                )
            )

            logger.warning(
                "Forbidden action: %s",
                action
            )

        except discord.HTTPException as e:
            results.append(
                ActionResult(
                    action,
                    False,
                    f"Discord API error for {action_type}: {e}"
                )
            )

            logger.warning(
                "HTTP error action %s: %s",
                action,
                e
            )

        except Exception as e:
            results.append(
                ActionResult(
                    action,
                    False,
                    f"Unexpected error for {action_type}: {e}"
                )
            )

            logger.exception(
                "Unexpected error action: %s",
                action
            )

    return results


async def _execute_single_action(
    guild: discord.Guild,
    action: dict
) -> ActionResult:

    action_type = action["type"]


    # CREATE CATEGORY
    if action_type == "create_category":

        cat = await categories.create_category(
            guild,
            action["name"]
        )

        return ActionResult(
            action,
            True,
            f"Category **{cat.name}** created (or already existed)"
        )


    # CREATE CHANNEL
    if action_type == "create_channel":

        ch = await channels.create_channel(
            guild,
            name=action["name"],
            category_name=action.get("category"),
            channel_type=action.get(
                "channel_type",
                "text"
            )
        )

        return ActionResult(
            action,
            True,
            f"Channel **#{ch.name}** created (or already existed)"
        )


    # DELETE CHANNEL
    if action_type == "delete_channel":

        ok = await channels.delete_channel(
            guild,
            action["name"]
        )

        if ok:
            return ActionResult(
                action,
                True,
                f"Channel **{action['name']}** deleted"
            )

        return ActionResult(
            action,
            False,
            f"Channel **{action['name']}** not found"
        )


    # MOVE CHANNEL
    if action_type == "move_channel":

        ok = await channels.move_channel(
            guild,
            action["name"],
            action["target_category"]
        )

        if ok:
            return ActionResult(
                action,
                True,
                f"Channel **{action['name']}** moved to **{action['target_category']}**"
            )

        return ActionResult(
            action,
            False,
            "Channel or category not found"
        )


    # RENAME CHANNEL
    if action_type == "rename_channel":

        ok = await channels.rename_channel(
            guild,
            action["old_name"],
            action["new_name"]
        )

        if ok:
            return ActionResult(
                action,
                True,
                f"Channel **{action['old_name']}** renamed to **{action['new_name']}**"
            )

        return ActionResult(
            action,
            False,
            f"Channel **{action['old_name']}** not found"
        )


    # CREATE ROLE
    if action_type == "create_role":

        role = await roles.create_role(
            guild,
            name=action["name"],
            permission_names=action.get(
                "permissions",
                []
            ),
            color_hex=action.get("color"),
            mentionable=action.get(
                "mentionable",
                True
            ),
            hoist=action.get(
                "hoist",
                True
            )
        )

        return ActionResult(
            action,
            True,
            f"Role **{role.name}** created (or already existed)"
        )


    # DELETE ROLE
    if action_type == "delete_role":

        ok = await roles.delete_role(
            guild,
            action["name"]
        )

        if ok:
            return ActionResult(
                action,
                True,
                f"Role **{action['name']}** deleted"
            )

        return ActionResult(
            action,
            False,
            f"Role **{action['name']}** not found"
        )


    # RENAME ROLE
    if action_type == "rename_role":

        ok = await roles.rename_role(
            guild,
            action["old_name"],
            action["new_name"]
        )

        if ok:
            return ActionResult(
                action,
                True,
                f"Role **{action['old_name']}** renamed to **{action['new_name']}**"
            )

        return ActionResult(
            action,
            False,
            f"Role **{action['old_name']}** not found"
        )


    return ActionResult(
        action,
        False,
        f"Unknown action type: {action_type}"
    )

        # RENAME CATEGORY
    if action_type == "rename_category":

        ok = await categories.rename_category(
            guild,
            action["old_name"],
            action["new_name"]
        )

        if ok:
            return ActionResult(
                action,
                True,
                f"Category **{action['old_name']}** renamed to **{action['new_name']}**"
            )

        return ActionResult(
            action,
            False,
            f"Category **{action['old_name']}** not found"
        )