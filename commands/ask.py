"""
commands/ask.py

AI Discord Builder main command.

Flow:
1. User uses /ask
2. Permission checks
3. AI creates plan
4. User confirms
5. Execute actions
6. Save results + history

Shared logic:
- builder/flow.py handles AI planning, formatting and logging.
- executor.py only executes Discord actions.
"""

import logging
from datetime import datetime, timezone

import config
import discord

from discord import app_commands
from discord.ext import commands

from ai.client import AIPlanError

from builder.executor import execute_plan

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



    async def on_timeout(
        self
    ):

        for item in self.children:

            item.disabled = True



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
                self.actions
            )


        except Exception as e:

            logger.exception(
                "Execution failed"
            )


            log_conversation(
                guild_id=self.guild.id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                message="Executed AI plan",
                response=f"ERROR: {e}",
            )


            await interaction.followup.send(
                f"❌ Execution error: {e}"
            )


            self.stop()

            return



        success = sum(
            1
            for r in results
            if r.success
        )


        failed = len(results) - success



        result_output = "\n".join(
            str(r)
            for r in results
        )



        embed = discord.Embed(
            title=(
                "✅ Plan completed"
                if failed == 0
                else "⚠️ Plan partially completed"
            ),
            description=result_output[:4000],
            color=(
                discord.Color.green()
                if failed == 0
                else discord.Color.orange()
            ),
        )


        embed.set_footer(
            text=f"{success} successful • {failed} failed"
        )



        await interaction.followup.send(
            embed=embed
        )



        log_conversation(
            guild_id=self.guild.id,
            user_id=interaction.user.id,
            username=str(interaction.user),
            message="Executed AI plan",
            response=result_output[:2000],
        )



        log_action_history(
            guild_id=self.guild.id,
            user_id=interaction.user.id,
            results=results,
        )



        audit_logger.info(
            "USER=%s (%s) | GUILD=%s | %s/%s actions | TIME=%s",
            interaction.user,
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
            embed=None,
            view=self,
        )



        log_conversation(
            guild_id=self.guild.id,
            user_id=interaction.user.id,
            username=str(interaction.user),
            message="Cancelled AI plan",
            response="User cancelled the plan",
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
        bot: commands.Bot
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



        if not can_use_builder(
            member
        ):

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

            logger.exception(
                "AI plan failed"
            )


            await interaction.followup.send(
                f"❌ Could not create plan: {e}"
            )

            return



        except Exception as e:

            logger.exception(
                "Unexpected error"
            )


            await interaction.followup.send(
                f"❌ Unexpected error: {e}"
            )

            return




        if plan.get(
            "needs_clarification"
        ):

            await interaction.followup.send(
                f"🤔 {plan.get('clarification_question')}"
            )

            return



        if not plan.get(
            "actions"
        ):

            await interaction.followup.send(
                f"ℹ️ {plan.get('summary')}\n\nNo actions needed."
            )

            return




        embed = format_plan_embed(
            plan["summary"],
            plan["actions"],
        )



        view = ConfirmationView(
            interaction.user.id,
            interaction.guild,
            plan["actions"],
        )



        await interaction.followup.send(
            embed=embed,
            view=view,
        )



# =====================================
# EXTENSION SETUP
# =====================================


async def setup(
    bot: commands.Bot
):

    await bot.add_cog(
        AskCog(bot)
    )