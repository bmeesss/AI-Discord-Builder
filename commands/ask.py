"""
commands/ask.py

The /ask slash command:
1. User sends /ask <question>
2. Permission checks
3. Collect current server context
4. AI creates validated JSON plan
5. User confirms with buttons
6. Executor runs actions
7. Results + audit logging
"""

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config

from ai.client import AIClient, AIPlanError
from builder.executor import execute_plan
from builder.context import get_server_context

from security.permissions import (
    can_use_builder,
    missing_permission_message,
    bot_has_required_permissions
)


logger = logging.getLogger(
    "ai_discord_builder.ask"
)

audit_logger = logging.getLogger(
    "ai_discord_builder.audit"
)



def format_plan_embed(
    summary: str,
    actions: list[dict]
) -> discord.Embed:

    embed = discord.Embed(
        title="🤖 AI Server Builder — Proposed Plan",
        description=summary,
        color=discord.Color.blurple()
    )


    categories = [
        a["name"]
        for a in actions
        if a["type"] == "create_category"
    ]


    channels = [
        a
        for a in actions
        if a["type"] == "create_channel"
    ]


    roles = [
        a
        for a in actions
        if a["type"] == "create_role"
    ]


    other = [
        a
        for a in actions
        if a["type"]
        not in (
            "create_category",
            "create_channel",
            "create_role"
        )
    ]


    if categories:
        embed.add_field(
            name="📁 Categories",
            value="\n".join(
                f"- {x}"
                for x in categories
            ),
            inline=False
        )


    if channels:

        lines = []

        for channel in channels:

            icon = (
                "🔊"
                if channel.get("channel_type") == "voice"
                else "💬"
            )

            category = (
                f" ({channel['category']})"
                if channel.get("category")
                else ""
            )

            lines.append(
                f"{icon} #{channel['name']}{category}"
            )


        embed.add_field(
            name="Channels",
            value="\n".join(lines),
            inline=False
        )


    if roles:

        lines = []

        for role in roles:

            perms = ", ".join(
                role.get(
                    "permissions",
                    []
                )
            )

            if not perms:
                perms = "No special permissions"


            lines.append(
                f"🎭 **{role['name']}** — {perms}"
            )


        embed.add_field(
            name="Roles",
            value="\n".join(lines),
            inline=False
        )


    if other:

        embed.add_field(
            name="Other actions",
            value="\n".join(
                f"- {x['type']}"
                for x in other
            ),
            inline=False
        )


    embed.set_footer(
        text=f"{len(actions)} action(s) total • Confirm?"
    )


    return embed




class ConfirmationView(
    discord.ui.View
):

    def __init__(
        self,
        author_id: int,
        guild: discord.Guild,
        actions: list[dict]
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
                "❌ Only the command user can confirm this.",
                ephemeral=True
            )

            return False


        return True



    async def on_timeout(self):

        for item in self.children:
            item.disabled = True



    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.success,
        emoji="✅"
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        for item in self.children:
            item.disabled = True


        await interaction.response.edit_message(
            content="⏳ Executing plan...",
            embed=None,
            view=self
        )


        results = await execute_plan(
            self.guild,
            self.actions
        )


        success = sum(
            1
            for r in results
            if r.success
        )


        failed = len(results) - success


        embed = discord.Embed(
            title=(
                "✅ Plan completed"
                if failed == 0
                else "⚠️ Plan partially completed"
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
            text=f"{success} successful • {failed} failed"
        )


        await interaction.followup.send(
            embed=embed
        )


        audit_logger.info(
            "USER=%s (%s) | GUILD=%s | %s/%s actions | TIME=%s",
            interaction.user,
            interaction.user.id,
            self.guild.name,
            success,
            failed,
            datetime.now(
                timezone.utc
            ).isoformat()
        )


        self.stop()



    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.danger,
        emoji="❌"
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):


        for item in self.children:
            item.disabled = True


        await interaction.response.edit_message(
            content="❌ Cancelled. No changes made.",
            embed=None,
            view=self
        )


        self.stop()




class AskCog(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot
    ):

        self.bot = bot
        self.ai_client = AIClient()



    @app_commands.command(
        name="ask",
        description="Manage your Discord server using AI"
    )
    @app_commands.describe(
        vraag="What should the AI build or change?"
    )
    async def ask(
        self,
        interaction: discord.Interaction,
        vraag: str
    ):


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


        if not can_use_builder(member):

            await interaction.response.send_message(
                missing_permission_message(),
                ephemeral=True
            )

            return



        bot_ok, missing = bot_has_required_permissions(
            interaction.guild
        )


        if not bot_ok:

            await interaction.response.send_message(
                f"❌ Missing permissions: {', '.join(missing)}",
                ephemeral=True
            )

            return



        await interaction.response.defer(
            thinking=True
        )



        try:

            server_context = get_server_context(
                interaction.guild
            )


            plan = await self.ai_client.generate_plan(
                vraag,
                server_context
            )


        except AIPlanError as e:

            await interaction.followup.send(
                f"❌ Could not create plan: {e}"
            )

            return



        if plan["needs_clarification"]:

            await interaction.followup.send(
                f"🤔 {plan['clarification_question']}"
            )

            return



        if not plan["actions"]:

            await interaction.followup.send(
                f"ℹ️ {plan['summary']}\n\nNo actions to execute."
            )

            return



        embed = format_plan_embed(
            plan["summary"],
            plan["actions"]
        )


        view = ConfirmationView(
            interaction.user.id,
            interaction.guild,
            plan["actions"]
        )


        await interaction.followup.send(
            embed=embed,
            view=view
        )




async def setup(
    bot: commands.Bot
):

    await bot.add_cog(
        AskCog(bot)
    )