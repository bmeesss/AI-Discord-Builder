"""
commands/views.py

Shared Discord UI views for AI Discord Builder.

Contains:
- ConfirmationView
- RollbackView

Used by:
- /ask command
- @mention handler

This file handles:
- Confirming AI plans
- Executing actions
- Saving history
- Rolling back actions

It does NOT:
- Generate AI plans
- Handle slash commands
- Handle message events
"""

import logging
from datetime import datetime, timezone

import config
import discord

from builder.executor import execute_plan
from builder.rollback import rollback_actions

from builder.flow import (
    log_conversation,
    log_action_history,
)


logger = logging.getLogger(
    "ai_discord_builder.views"
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
        interaction: discord.Interaction,
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
                str(result)
                for result in results
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
        risk: str = "low",
    ):

        super().__init__(
            timeout=config.CONFIRMATION_TIMEOUT
        )


        self.author_id = author_id
        self.guild = guild
        self.actions = actions
        self.risk = risk
        self._risk_confirmed = False



    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:


        if interaction.user.id != self.author_id:


            await interaction.response.send_message(
                "❌ Only the user who created this plan can confirm it.",
                ephemeral=True,
            )


            return False


        return True



    async def on_timeout(
        self,
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


        if (
            self.risk in ("high", "critical")
            and not self._risk_confirmed
        ):

            self._risk_confirmed = True

            await interaction.response.edit_message(
                content=(
                    "⚠️ This is a high-risk AI plan. Review the proposed "
                    "changes carefully, then press Confirm again to execute."
                    if self.risk == "high"
                    else (
                        "🚨 This is a CRITICAL AI plan. It may make destructive "
                        "or dangerous changes. Press Confirm again only if you "
                        "fully understand the risk."
                    )
                ),
                view=self,
            )

            return


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



        await log_conversation(
            guild_id=self.guild.id,
            user_id=interaction.user.id,
            username=str(interaction.user),
            message="Executed AI plan",
            response=output[:2000],
        )



        await log_action_history(
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



        await log_conversation(
            guild_id=self.guild.id,
            user_id=interaction.user.id,
            username=str(interaction.user),
            message="Cancelled AI plan",
            response="User cancelled plan",
        )



        self.stop()
