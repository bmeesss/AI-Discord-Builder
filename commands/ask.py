"""
commands/ask.py

AI Discord Builder main command.

Supports:
- /ask command
- AI plan generation
- Confirmation system
- Plan execution
- Rollback button after execution

Shared logic:
- builder/flow.py handles AI planning and logging.
- builder/executor.py executes actions.
- builder/rollback.py handles undoing actions.
"""

import logging
from datetime import datetime, timezone

import config
import discord

from discord import app_commands
from discord.ext import commands

from ai.client import AIPlanError

from builder.executor import execute_plan
from builder.rollback import rollback_actions

from builder.flow import (
    build_plan,
    format_plan_embed,
    log_conversation,
    log_action_history,
)

from security.permissions import (
    bot_has_required_permissions,
    can_use_builder,
    missing_permission_message,
)


logger = logging.getLogger(
    "ai_discord_builder.ask"
)

audit_logger = logging.getLogger(
    "ai_discord_builder.audit"
)


# =====================================
# ROLLBACK VIEW
# =====================================


class RollbackView(
    discord.ui.View
):

    def __init__(
        self,
        author_id: int,
        guild: discord.Guild,
    ):

        super().__init__(
            timeout=config.CONFIRMATION_TIMEOUT
        )

        self.author_id = author_id
        self.guild = guild



    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if interaction.user.id != self.author_id:

            await interaction.response.send_message(
                "❌ Only the user who created this plan can rollback it.",
                ephemeral=True,
            )

            return False


        return True



    @discord.ui.button(
        label="Rollback",
        style=discord.ButtonStyle.danger,
        emoji="↩️",
    )
    async def rollback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        button.disabled = True


        await interaction.response.edit_message(
            content="⏳ Rolling back...",
            view=self,
        )


        try:

            results = await rollback_actions(
                self.guild,
                amount=1,
            )


            output = "\n".join(
                str(x)
                for x in results
            )


            embed = discord.Embed(
                title="↩️ Rollback completed",
                description=output[:4000],
                color=discord.Color.orange(),
            )


            await interaction.followup.send(
                embed=embed
            )


        except Exception as e:

            logger.exception(
                "Rollback failed"
            )


            await interaction.followup.send(
                f"❌ Rollback error: {e}"
            )


        self.stop()



# =====================================
# CONFIRMATION VIEW
# =====================================


class ConfirmationView(
    discord.ui.View
):

    def __init__(
        self,
        author_id: int,
        guild: discord.Guild,
        actions: list[dict],
    ):

        super().__init__(
            timeout=config.CONFIRMATION_TIMEOUT
        )

        self.author_id = author_id
        self.guild = guild
        self.actions = actions



    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:


        if interaction.user.id != self.author_id:

            await interaction.response.send_message(
                "❌ Only the user who created this plan can confirm it.",
                ephemeral=True,
            )

            return False


        return True



    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):


        for item in self.children:

            item.disabled = True



        await interaction.response.edit_message(
            content="⏳ Executing plan...",
            view=self,
        )


        try:

            results = await execute_plan(
                self.guild,
                self.actions,
            )


        except Exception as e:

            logger.exception(
                "Execution failed"
            )


            await interaction.followup.send(
                f"❌ Execution error: {e}"
            )

            self.stop()

            return



        success = sum(
            1
            for result in results
            if result.success
        )


        failed = len(results) - success



        output = "\n".join(
            str(result)
            for result in results
        )



        embed = discord.Embed(
            title=(
                "✅ Plan completed"
                if failed == 0
                else "⚠️ Plan partially completed"
            ),
            description=output[:4000],
            color=(
                discord.Color.green()
                if failed == 0
                else discord.Color.orange()
            ),
        )


        embed.set_footer(
            text=f"{success} successful • {failed} failed"
        )



        log_conversation(
            guild_id=self.guild.id,
            user_id=interaction.user.id,
            username=str(interaction.user),
            message="Executed AI plan",
            response=output[:2000],
        )


        log_action_history(
            guild_id=self.guild.id,
            user_id=interaction.user.id,
            results=results,
        )



        await interaction.followup.send(
            embed=embed,
            view=RollbackView(
                interaction.user.id,
                self.guild,
            ),
        )



        audit_logger.info(
            "USER=%s | GUILD=%s | %s/%s actions | TIME=%s",
            interaction.user.id,
            self.guild.name,
            success,
            failed,
            datetime.now(timezone.utc).isoformat(),
        )


        self.stop()



    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.danger,
        emoji="❌",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):


        for item in self.children:

            item.disabled = True



        await interaction.response.edit_message(
            content="❌ Cancelled. No changes were made.",
            view=self,
        )


        log_conversation(
            guild_id=self.guild.id,
            user_id=interaction.user.id,
            username=str(interaction.user),
            message="Cancelled AI plan",
            response="User cancelled plan",
        )


        self.stop()



# =====================================
# ASK COG
# =====================================


class AskCog(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot



    @app_commands.command(
        name="ask",
        description="Manage your Discord server using AI",
    )
    @app_commands.describe(
        vraag="What should the AI build or change?",
    )
    async def ask(
        self,
        interaction: discord.Interaction,
        vraag: str,
    ):


        if interaction.guild is None:

            await interaction.response.send_message(
                "❌ This command only works inside a server.",
                ephemeral=True,
            )

            return



        member = (
            interaction.guild.get_member(
                interaction.user.id
            )
            or interaction.user
        )


        if not can_use_builder(member):

            await interaction.response.send_message(
                missing_permission_message(),
                ephemeral=True,
            )

            return



        bot_ok, missing = bot_has_required_permissions(
            interaction.guild
        )


        if not bot_ok:

            await interaction.response.send_message(
                f"❌ Missing permissions: {', '.join(missing)}",
                ephemeral=True,
            )

            return



        await interaction.response.defer(
            thinking=True
        )



        try:

            plan = await build_plan(
                guild=interaction.guild,
                user=interaction.user,
                prompt=vraag,
            )


        except AIPlanError as e:

            await interaction.followup.send(
                f"❌ AI error: {e}"
            )

            return



        except Exception as e:

            logger.exception(
                "Plan error"
            )

            await interaction.followup.send(
                f"❌ Error: {e}"
            )

            return



        if plan.get(
            "needs_clarification"
        ):

            await interaction.followup.send(
                plan.get(
                    "clarification_question"
                )
            )

            return



        if not plan.get(
            "actions"
        ):

            await interaction.followup.send(
                "ℹ️ No actions needed."
            )

            return



        embed = format_plan_embed(
            plan["summary"],
            plan["actions"],
        )


        await interaction.followup.send(
            embed=embed,
            view=ConfirmationView(
                interaction.user.id,
                interaction.guild,
                plan["actions"],
            ),
        )



# =====================================
# SETUP
# =====================================


async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        AskCog(bot)
    )