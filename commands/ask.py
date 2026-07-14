"""
commands/ask.py
De /ask slash command: kern van AI-Discord-Builder.

Flow:
1. Gebruiker typt /ask <vraag>
2. Permissie check (alleen admins, tenzij REQUIRE_ADMIN=false)
3. AI genereert een plan (JSON, gevalideerd door ai/client.py)
4. Als de AI om verduidelijking vraagt -> toon vraag, stop
5. Anders: toon leesbaar plan + ✅/❌ knoppen
6. Bij bevestiging -> builder/executor.py voert het plan uit
7. Resultaat + logging
"""

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
from ai.client import AIClient, AIPlanError
from builder.executor import execute_plan
from security.permissions import can_use_builder, missing_permission_message, bot_has_required_permissions

logger = logging.getLogger("ai_discord_builder.ask")
audit_logger = logging.getLogger("ai_discord_builder.audit")


def format_plan_embed(summary: str, actions: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="🤖 AI Server Builder — Voorgesteld Plan",
        description=summary,
        color=discord.Color.blurple(),
    )

    categories_list = [a["name"] for a in actions if a["type"] == "create_category"]
    channels_list = [a for a in actions if a["type"] == "create_channel"]
    roles_list = [a for a in actions if a["type"] == "create_role"]
    other_actions = [
        a for a in actions
        if a["type"] not in ("create_category", "create_channel", "create_role")
    ]

    if categories_list:
        embed.add_field(
            name="📁 Categorieën",
            value="\n".join(f"- {c}" for c in categories_list),
            inline=False,
        )

    if channels_list:
        lines = []
        for c in channels_list:
            prefix = "🔊" if c.get("channel_type") == "voice" else "💬"
            cat = f" ({c['category']})" if c.get("category") else ""
            lines.append(f"{prefix} #{c['name']}{cat}")
        embed.add_field(name="Kanalen", value="\n".join(lines), inline=False)

    if roles_list:
        lines = []
        for r in roles_list:
            perms = ", ".join(r.get("permissions", [])) or "geen speciale rechten"
            lines.append(f"🎭 **{r['name']}** — {perms}")
        embed.add_field(name="Rollen", value="\n".join(lines), inline=False)

    if other_actions:
        lines = [f"- {a['type']}: {a}" for a in other_actions]
        embed.add_field(name="Overige acties", value="\n".join(lines)[:1024], inline=False)

    embed.set_footer(text=f"{len(actions)} actie(s) totaal • Wil je dit uitvoeren?")
    return embed


class ConfirmationView(discord.ui.View):
    """View met ✅ Bevestigen / ❌ Annuleren knoppen. Alleen de originele auteur mag klikken."""

    def __init__(self, author_id: int, guild: discord.Guild, actions: list[dict]):
        super().__init__(timeout=config.CONFIRMATION_TIMEOUT)
        self.author_id = author_id
        self.guild = guild
        self.actions = actions
        self.responded = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Alleen de persoon die dit commando gebruikte kan bevestigen/annuleren.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Bevestigen", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.responded = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="⏳ Plan wordt uitgevoerd...", embed=None, view=self
        )

        results = await execute_plan(self.guild, self.actions)

        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count

        result_lines = "\n".join(str(r) for r in results)
        result_embed = discord.Embed(
            title="✅ Plan uitgevoerd" if fail_count == 0 else "⚠️ Plan deels uitgevoerd",
            description=result_lines[:4000],
            color=discord.Color.green() if fail_count == 0 else discord.Color.orange(),
        )
        result_embed.set_footer(text=f"{success_count} gelukt, {fail_count} mislukt")

        await interaction.followup.send(embed=result_embed)

        # Audit log
        audit_logger.info(
            "USER=%s (%s) | GUILD=%s | ACTIES=%d gelukt / %d mislukt | TIJD=%s",
            interaction.user, interaction.user.id, self.guild.name,
            success_count, fail_count, datetime.now(timezone.utc).isoformat(),
        )

        self.stop()

    @discord.ui.button(label="Annuleren", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.responded = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="❌ Geannuleerd. Er zijn geen wijzigingen gemaakt.", embed=None, view=self
        )
        self.stop()


class AskCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ai_client = AIClient()

    @app_commands.command(name="ask", description="Beheer je Discord server met natuurlijke taal")
    @app_commands.describe(vraag="Wat wil je dat de AI bouwt of aanpast?")
    async def ask(self, interaction: discord.Interaction, vraag: str):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Dit commando werkt alleen binnen een server, niet in DMs.", ephemeral=True
            )
            return

        member = interaction.guild.get_member(interaction.user.id) or interaction.user
        if not can_use_builder(member):
            await interaction.response.send_message(missing_permission_message(), ephemeral=True)
            return

        bot_ok, missing = bot_has_required_permissions(interaction.guild)
        if not bot_ok:
            await interaction.response.send_message(
                f"❌ Ik mis zelf de volgende rechten om te kunnen bouwen: {', '.join(missing)}. "
                f"Geef mij **Manage Channels** en **Manage Roles** en probeer opnieuw.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            plan = await self.ai_client.generate_plan(vraag)
        except AIPlanError as e:
            await interaction.followup.send(f"❌ Kon geen plan maken: {e}")
            return

        if plan["needs_clarification"]:
            question = plan["clarification_question"] or "Kun je je vraag specifieker maken?"
            await interaction.followup.send(f"🤔 {question}")
            return

        if not plan["actions"]:
            await interaction.followup.send(
                f"ℹ️ {plan['summary']}\n\nEr zijn geen concrete acties om uit te voeren."
            )
            return

        embed = format_plan_embed(plan["summary"], plan["actions"])
        view = ConfirmationView(interaction.user.id, interaction.guild, plan["actions"])
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(AskCog(bot))
