"""
commands/ask.py

AI Discord Builder main command.

Supports:
- /ask command
- AI plan generation
- Confirmation system

Shared logic:
- builder/flow.py handles AI planning and logging.
- builder/executor.py executes actions.
- builder/rollback.py handles undoing actions.
- commands/views.py handles Discord buttons.
"""

import logging

import discord

from discord import app_commands
from discord.ext import commands

from ai.client import AIPlanError

from builder.flow import (
    build_plan,
    format_plan_embed,
)

from commands.views import ConfirmationView

from security.permissions import (
    bot_has_required_permissions,
    can_use_builder,
    missing_permission_message,
)


logger = logging.getLogger(
    "ai_discord_builder.ask"
)



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


        # =============================
        # GUILD CHECK
        # =============================

        if interaction.guild is None:

            await interaction.response.send_message(
                "❌ This command only works inside a server.",
                ephemeral=True,
            )

            return



        # =============================
        # USER PERMISSIONS
        # =============================

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



        # =============================
        # BOT PERMISSIONS
        # =============================

        bot_ok, missing = bot_has_required_permissions(
            interaction.guild
        )


        if not bot_ok:

            await interaction.response.send_message(
                f"❌ Missing permissions: {', '.join(missing)}",
                ephemeral=True,
            )

            return



        # =============================
        # THINKING
        # =============================

        await interaction.response.defer(
            thinking=True
        )



        # =============================
        # BUILD AI PLAN
        # =============================

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
                "Plan generation failed"
            )


            await interaction.followup.send(
                f"❌ Error creating plan: {e}"
            )

            return



        # =============================
        # CLARIFICATION
        # =============================

        if plan.get(
            "needs_clarification"
        ):

            await interaction.followup.send(
                f"🤔 {plan.get('clarification_question')}"
            )

            return



        # =============================
        # EMPTY PLAN
        # =============================

        if not plan.get(
            "actions"
        ):

            await interaction.followup.send(
                f"ℹ️ {plan.get('summary', 'No actions needed.')}"
            )

            return



        # =============================
        # SEND CONFIRMATION
        # =============================

        embed = format_plan_embed(
            plan["summary"],
            plan["actions"],
            risk=plan.get(
                "risk",
                "low",
            ),
            recommendations=plan.get(
                "recommendations",
                [],
            ),
        )


        view = ConfirmationView(
            interaction.user.id,
            interaction.guild,
            plan["actions"],
            risk=plan.get(
                "risk",
                "low",
            ),
        )


        await interaction.followup.send(
            embed=embed,
            view=view,
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
