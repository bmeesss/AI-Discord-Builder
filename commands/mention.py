"""
commands/mention.py

AI Discord Builder mention handler.

Supports:
- @AI Server Builder vragen
- Same AI flow as /ask

Flow:
1. User mentions bot
2. Permission checks
3. AI creates plan
4. Show confirmation view
5. Execute through shared views

Shared logic:
- builder/flow.py handles AI planning
- commands/views.py handles buttons
"""

import logging

import discord

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
    "ai_discord_builder.mention"
)



class MentionCog(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot



    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ):


        # =============================
        # IGNORE BOTS
        # =============================

        if message.author.bot:

            return



        # =============================
        # GUILD CHECK
        # =============================

        if message.guild is None:

            return



        # =============================
        # ONLY DIRECT BOT MENTION
        # =============================

        if not self.bot.user:

            return



        if self.bot.user not in message.mentions:

            return



        # =============================
        # REMOVE MENTION
        # =============================

        prompt = message.content

        prompt = prompt.replace(
            f"<@{self.bot.user.id}>",
            "",
        )

        prompt = prompt.replace(
            f"<@!{self.bot.user.id}>",
            "",
        )


        prompt = prompt.strip()



        if not prompt:

            await message.reply(
                "🤖 Geef een opdracht na mijn mention.",
                mention_author=False,
            )

            return



        # =============================
        # USER PERMISSIONS
        # =============================

        member = (
            message.guild.get_member(
                message.author.id
            )
            or message.author
        )


        if not can_use_builder(member):

            await message.reply(
                missing_permission_message(),
                mention_author=False,
            )

            return



        # =============================
        # BOT PERMISSIONS
        # =============================

        bot_ok, missing = bot_has_required_permissions(
            message.guild
        )


        if not bot_ok:

            await message.reply(
                f"❌ Missing permissions: {', '.join(missing)}",
                mention_author=False,
            )

            return



        # =============================
        # PROCESS AI
        # =============================

        async with message.channel.typing():

            try:

                plan = await build_plan(
                    guild=message.guild,
                    user=message.author,
                    prompt=prompt,
                )


            except AIPlanError as e:

                await message.reply(
                    f"❌ AI error: {e}",
                    mention_author=False,
                )

                return



            except Exception as e:

                logger.exception(
                    "Mention plan failed"
                )


                await message.reply(
                    f"❌ Error creating plan: {e}",
                    mention_author=False,
                )

                return



        # =============================
        # CLARIFICATION
        # =============================

        if plan.get(
            "needs_clarification"
        ):

            await message.reply(
                f"🤔 {plan.get('clarification_question')}",
                mention_author=False,
            )

            return



        # =============================
        # EMPTY PLAN
        # =============================

        if not plan.get(
            "actions"
        ):

            await message.reply(
                f"ℹ️ {plan.get('summary', 'No actions needed.')}",
                mention_author=False,
            )

            return



        # =============================
        # SEND CONFIRMATION
        # =============================

        embed = format_plan_embed(
            plan["summary"],
            plan["actions"],
        )


        view = ConfirmationView(
            message.author.id,
            message.guild,
            plan["actions"],
        )


        await message.reply(
            embed=embed,
            view=view,
            mention_author=False,
        )



async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        MentionCog(bot)
    )