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
"""

import discord

from builder import history

from builder.finder import (
    find_channel,
    find_role,
    find_category
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









async def rollback_actions(
    guild: discord.Guild,
    amount: int = 1
) -> list[RollbackResult]:


    actions = history.get_last_actions(
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



    # newest first

    for entry in reversed(actions):

        result = await rollback_single_action(
            guild,
            entry["action"]
        )


        results.append(
            result
        )



    history.remove_last_actions(
        guild.id,
        amount
    )


    return results










async def rollback_single_action(
    guild: discord.Guild,
    action: dict
) -> RollbackResult:


    action_type = action.get(
        "type"
    )





    # =====================
    # CHANNELS
    # =====================


    if action_type == "create_channel":

        channel = find_channel(
            guild,
            action["name"]
        )


        if not channel:

            return RollbackResult(
                False,
                f"Channel {action['name']} not found"
            )


        await channel.delete(
            reason="AI-Discord-Builder rollback"
        )


        return RollbackResult(
            True,
            f"Deleted channel #{action['name']}"
        )







    if action_type == "rename_channel":

        channel = find_channel(
            guild,
            action["new_name"]
        )


        if not channel:

            return RollbackResult(
                False,
                "Renamed channel not found"
            )


        await channel.edit(
            name=action["old_name"],
            reason="AI-Discord-Builder rollback"
        )


        return RollbackResult(
            True,
            f"Restored channel #{action['old_name']}"
        )









    # =====================
    # CATEGORIES
    # =====================


    if action_type == "create_category":

        category = find_category(
            guild,
            action["name"]
        )


        if not category:

            return RollbackResult(
                False,
                "Category not found"
            )


        await category.delete(
            reason="AI-Discord-Builder rollback"
        )


        return RollbackResult(
            True,
            f"Deleted category {action['name']}"
        )









    if action_type == "rename_category":

        category = find_category(
            guild,
            action["new_name"]
        )


        if not category:

            return RollbackResult(
                False,
                "Category not found"
            )


        await category.edit(
            name=action["old_name"],
            reason="AI-Discord-Builder rollback"
        )


        return RollbackResult(
            True,
            "Restored category name"
        )









    # =====================
    # ROLES
    # =====================


    if action_type == "create_role":

        role = find_role(
            guild,
            action["name"]
        )


        if not role:

            return RollbackResult(
                False,
                "Role not found"
            )


        await role.delete(
            reason="AI-Discord-Builder rollback"
        )


        return RollbackResult(
            True,
            f"Deleted role {action['name']}"
        )









    if action_type == "rename_role":

        role = find_role(
            guild,
            action["new_name"]
        )


        if not role:

            return RollbackResult(
                False,
                "Role not found"
            )


        await role.edit(
            name=action["old_name"],
            reason="AI-Discord-Builder rollback"
        )


        return RollbackResult(
            True,
            "Restored role name"
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
            channel_id
        )


        if not channel:

            return RollbackResult(
                False,
                "Message channel not found"
            )



        try:

            message = await channel.fetch_message(
                message_id
            )


            await message.delete(
                reason="AI-Discord-Builder rollback"
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
        f"Rollback unsupported for {action_type}"
    )