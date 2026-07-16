```python
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
    os.path.dirname(config.LOG_FILE_PATH) or ".",
    exist_ok=True
)


logger = logging.getLogger(
    "ai_discord_builder"
)

logger.setLevel(
    logging.INFO
)


if not logger.handlers:

    console_handler = logging.StreamHandler()

    console_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
        )
    )

    logger.addHandler(
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

    logger.addHandler(
        file_handler
    )


main_logger = logging.getLogger(
    "ai_discord_builder.main"
)


# =========================
# DISCORD BOT
# =========================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True

# Required for @mention command handler
intents.message_content = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# READY EVENT
# =========================

@bot.event
async def on_ready():

    main_logger.info(
        "Logged in as %s (ID: %s)",
        bot.user,
        bot.user.id
    )

    main_logger.info(
        "Guilds: %s",
        [
            guild.name
            for guild in bot.guilds
        ]
    )

    main_logger.info(
        "Loaded commands: %s",
        [
            command.name
            for command in bot.tree.get_commands()
        ]
    )

    try:

        for guild in bot.guilds:

            # Kopieer globale commands naar server
            bot.tree.copy_global_to(
                guild=guild
            )

            synced = await bot.tree.sync(
                guild=guild
            )

            main_logger.info(
                "Synced %s commands naar %s",
                len(synced),
                guild.name
            )

    except Exception:

        main_logger.exception(
            "Slash command sync failed"
        )


# =========================
# LOAD EXTENSIONS
# =========================

async def load_extensions():

    extensions = [

        "commands.ask",
        "commands.rollback",
        "commands.mention",

    ]

    for extension in extensions:

        try:

            await bot.load_extension(
                extension
            )

            main_logger.info(
                "Loaded extension: %s",
                extension
            )

        except Exception:

            main_logger.exception(
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
```
