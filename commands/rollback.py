"""
commands/rollback.py

Slash command for undoing AI-Discord-Builder actions.

Usage:
 /rollback amount:5
"""

import discord
from discord import app_commands
from discord.ext import commands

from builder.rollback import rollback_actions

from security.permissions import (
    can_use_builder,
    missing_permission_message,
    bot_has_required_permissions
)



class RollbackCog(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot
    ):

        self.bot = bot





    @app_commands.command(
        name="rollback",
        description="Undo the latest AI Discord Builder changes"
    )
    @app_commands.describe(
        amount="Number of actions to undo"
    )
    async def rollback(
        self,
        interaction: discord.Interaction,
        amount: int = 1
    ):


        # Must be inside server

        if interaction.guild is None:

            await interaction.response.send_message(
                "❌ This command only works inside a server.",
                ephemeral=True
            )

            return





        member = (
            interaction.guild.get_member(
                interaction.user.id
            )
            or interaction.user
        )



        # Permission check

        if not can_use_builder(
            member
        ):

            await interaction.response.send_message(
                missing_permission_message(),
                ephemeral=True
            )

            return





        # Bot permission check

        bot_ok, missing = bot_has_required_permissions(
            interaction.guild
        )


        if not bot_ok:

            await interaction.response.send_message(
                f"❌ Missing permissions: {', '.join(missing)}",
                ephemeral=True
            )

            return





        # Limit safety

        if amount < 1:

            amount = 1


        if amount > 25:

            amount = 25





        await interaction.response.defer(
            thinking=True
        )





        results = await rollback_actions(
            interaction.guild,
            amount
        )





        success = sum(
            1
            for r in results
            if r.success
        )


        failed = len(results) - success





        embed = discord.Embed(
            title=(
                "✅ Rollback completed"
                if failed == 0
                else "⚠️ Rollback partially completed"
            ),
            description="\n".join(
                str(r)
                for r in results
            )[:4000],
            color=(
                discord.Color.green()
                if failed == 0
                else discord.Color.orange()
            )
        )


        embed.set_footer(
            text=f"{success} restored • {failed} failed"
        )



        await interaction.followup.send(
            embed=embed
        )







async def setup(
    bot: commands.Bot
):

    await bot.add_cog(
        RollbackCog(bot)
    )