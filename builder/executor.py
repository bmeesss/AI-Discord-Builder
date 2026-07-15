"""
builder/executor.py

Executes validated AI action plans.

Features:
- Create/Delete/Rename/Move channels
- Create/Rename/Delete categories
- Create/Rename/Delete roles
- Send messages
- Saves actions for rollback
"""

import logging

import discord

from builder import categories, channels, roles, history

from builder.finder import (
    find_channel
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





def save_history(
    guild: discord.Guild,
    action: dict
):
    """
    Save successful action.
    """

    history.add_action(
        guild.id,
        action
    )









async def execute_plan(
    guild: discord.Guild,
    actions: list[dict]
) -> list[ActionResult]:

    results = []


    for action in actions:

        action_type = action.get(
            "type"
        )


        try:

            result = await _execute_single_action(
                guild,
                action
            )

            results.append(
                result
            )


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


        save_history(
            guild,
            action
        )


        return ActionResult(
            action,
            True,
            f"Category {category.name} created"
        )





    if action_type == "rename_category":

        ok = await categories.rename_category(
            guild,
            action["old_name"],
            action["new_name"]
        )


        if ok:

            save_history(
                guild,
                action
            )


            return ActionResult(
                action,
                True,
                "Category renamed"
            )


        return ActionResult(
            action,
            False,
            "Category not found"
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


        save_history(
            guild,
            action
        )


        return ActionResult(
            action,
            True,
            f"Channel #{channel.name} created"
        )







    if action_type == "rename_channel":

        ok = await channels.rename_channel(
            guild,
            action["old_name"],
            action["new_name"]
        )


        if ok:

            save_history(
                guild,
                action
            )


            return ActionResult(
                action,
                True,
                "Channel renamed"
            )


        return ActionResult(
            action,
            False,
            "Channel not found"
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


        await channel.delete(
            reason="AI-Discord-Builder"
        )


        save_history(
            guild,
            action
        )


        return ActionResult(
            action,
            True,
            "Channel deleted"
        )







    if action_type == "move_channel":

        ok = await channels.move_channel(
            guild,
            action["name"],
            action["target_category"]
        )


        if ok:

            save_history(
                guild,
                action
            )


            return ActionResult(
                action,
                True,
                "Channel moved"
            )


        return ActionResult(
            action,
            False,
            "Channel/category not found"
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


        # Save rollback information separately

        history_action = action.copy()

        history_action["message_id"] = message.id
        history_action["channel_id"] = channel.id



        save_history(
            guild,
            history_action
        )


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


        save_history(
            guild,
            action
        )


        return ActionResult(
            action,
            True,
            f"Role {role.name} created"
        )







    if action_type == "rename_role":

        ok = await roles.rename_role(
            guild,
            action["old_name"],
            action["new_name"]
        )


        if ok:

            save_history(
                guild,
                action
            )


            return ActionResult(
                action,
                True,
                "Role renamed"
            )


        return ActionResult(
            action,
            False,
            "Role not found"
        )







    if action_type == "delete_role":

        ok = await roles.delete_role(
            guild,
            action["name"]
        )


        if ok:

            save_history(
                guild,
                action
            )


            return ActionResult(
                action,
                True,
                "Role deleted"
            )


        return ActionResult(
            action,
            False,
            "Role not found"
        )







    return ActionResult(
        action,
        False,
        f"Unknown action: {action_type}"
    )