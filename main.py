"""
main.py

Entrypoint van AI-Discord-Builder.

Start:
- Flask webserver
- Discord bot
- Logging
- Slash commands
- Cogs/extensions
"""

import asyncio
import logging
import os
import threading

import discord
from discord.ext import commands

import config
from web.app import app



# =========================
# FLASK WEB SERVER
# =========================

def run_web():

    app.run(
        host="0.0.0.0",
        port=8080
    )


threading.Thread(
    target=run_web,
    daemon=True
).start()





# =========================
# LOGGING
# =========================

os.makedirs(
    os.path.dirname(
        config.LOG_FILE_PATH
    ) or ".",
    exist_ok=True
)


root_logger = logging.getLogger(
    "ai_discord_builder"
)

root_logger.setLevel(
    logging.INFO
)


if not root_logger.handlers:

    console_handler = logging.StreamHandler()

    console_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
        )
    )

    root_logger.addHandler(
        console_handler
    )



    file_handler = logging.FileHandler(
        config.LOG_FILE_PATH,
        encoding="utf-8"
    )

    file_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
        )
    )

    root_logger.addHandler(
        file_handler
    )



logger = logging.getLogger(
    "ai_discord_builder.main"
)





# =========================
# DISCORD BOT
# =========================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True



bot = commands.Bot(
    command_prefix="!",
    intents=intents
)





@bot.event
async def on_ready():

    logger.info(
        "Logged in as %s (ID: %s)",
        bot.user,
        bot.user.id
    )


    try:

        logger.info(
            "Loaded commands: %s",
            [
                cmd.name
                for cmd in bot.tree.get_commands()
            ]
        )


        # =========================
        # REMOVE OLD GLOBAL COMMANDS
        # =========================

        bot.tree.clear_commands(
            guild=None
        )


        await bot.tree.sync()


        logger.info(
            "Removed old global commands"
        )



        # =========================
        # GUILD SYNC
        # =========================

        for guild in bot.guilds:

            bot.tree.copy_global_to(
                guild=guild
            )


            synced = await bot.tree.sync(
                guild=guild
            )


            logger.info(
                "Synced %d command(s) naar %s",
                len(synced),
                guild.name
            )



    except Exception:

        logger.exception(
            "Slash command sync failed"
        )





# =========================
# EXTENSIONS
# =========================

async def load_extensions():

    extensions = [

        "commands.ask",

        "commands.rollback"

    ]


    for extension in extensions:

        try:

            await bot.load_extension(
                extension
            )


            logger.info(
                "Loaded extension: %s",
                extension
            )


        except Exception:

            logger.exception(
                "Failed loading extension: %s",
                extension
            )





# =========================
# START BOT
# =========================

async def main():

    config.validate_config()


    async with bot:

        await load_extensions()


        await bot.start(
            config.DISCORD_TOKEN
        )





if __name__ == "__main__":

    asyncio.run(
        main()
    )