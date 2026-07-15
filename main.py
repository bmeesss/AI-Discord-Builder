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
# FLASK
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
    os.path.dirname(config.LOG_FILE_PATH) or ".",
    exist_ok=True
)


logger_root = logging.getLogger(
    "ai_discord_builder"
)

logger_root.setLevel(
    logging.INFO
)


if not logger_root.handlers:

    handler = logging.StreamHandler()

    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
        )
    )

    logger_root.addHandler(
        handler
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

    logger_root.addHandler(
        file_handler
    )


logger = logging.getLogger(
    "ai_discord_builder.main"
)



# =========================
# BOT
# =========================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)



# =========================
# READY
# =========================

@bot.event
async def on_ready():

    logger.info(
        "Logged in as %s",
        bot.user
    )


    logger.info(
        "Loaded commands: %s",
        [
            cmd.name
            for cmd in bot.tree.get_commands()
        ]
    )


    try:

        # DEVELOPMENT GUILD SYNC
        for guild in bot.guilds:

            synced = await bot.tree.sync(
                guild=guild
            )

            logger.info(
                "Synced %s commands naar %s",
                len(synced),
                guild.name
            )


    except Exception:

        logger.exception(
            "Command sync failed"
        )



# =========================
# EXTENSIONS
# =========================

async def load_extensions():

    extensions = [

        "commands.ask",
        "commands.rollback"

    ]


    for ext in extensions:

        try:

            await bot.load_extension(
                ext
            )


            logger.info(
                "Loaded extension: %s",
                ext
            )


        except Exception:

            logger.exception(
                "Failed loading %s",
                ext
            )



# =========================
# START
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