"""AI Discord Builder runtime entrypoint.

The runtime stays intentionally small: Discord remains the source of truth for
server state, while the AI provider only returns validated plan text.  The
optional local-AI setup is a separate CLI (``python -m setup``); bot startup
never installs software or downloads models.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading

import discord
from discord.ext import commands

import config
from web.app import app, set_ready

logger = logging.getLogger("ai_discord_builder")
main_logger = logging.getLogger("ai_discord_builder.main")


def configure_logging() -> None:
    """Configure console and optional file logging once."""

    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    logger.propagate = False

    if logger.handlers:
        return

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if config.LOG_FILE_PATH:
        os.makedirs(
            os.path.dirname(config.LOG_FILE_PATH) or ".",
            exist_ok=True,
        )
        file_handler = logging.FileHandler(
            config.LOG_FILE_PATH,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def run_web() -> None:
    # Flask is retained for the current lightweight health endpoint.  A future
    # public web UI should run as a separately authenticated service.
    app.run(
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        use_reloader=False,
    )


def start_web_thread() -> threading.Thread:
    thread = threading.Thread(
        target=run_web,
        name="health-http",
        daemon=True,
    )
    thread.start()
    return thread


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
# Required only for the optional @mention command handler.
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


@bot.event
async def on_ready():
    main_logger.info(
        "Logged in as %s (ID: %s); connected to %s guild(s)",
        bot.user,
        bot.user.id if bot.user else "unknown",
        len(bot.guilds),
    )

    try:
        for guild in bot.guilds:
            # Commands are synced per guild for predictable self-hosted startup.
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            main_logger.info(
                "Synced %s commands to guild ID %s",
                len(synced),
                guild.id,
            )
    except Exception:
        set_ready(False)
        main_logger.exception("Slash command sync failed")
        return

    set_ready(True)


async def load_extensions() -> None:
    extensions = [
        "commands.ask",
        "commands.rollback",
        "commands.mention",
    ]
    failures: list[str] = []

    for extension in extensions:
        try:
            await bot.load_extension(extension)
            main_logger.info("Loaded extension: %s", extension)
        except Exception:
            failures.append(extension)
            main_logger.exception("Failed loading extension: %s", extension)

    if failures:
        raise RuntimeError(
            "Failed to load Discord extensions: " + ", ".join(failures)
        )


async def main() -> None:
    configure_logging()
    config.validate_config()
    set_ready(False)
    start_web_thread()

    async with bot:
        await load_extensions()
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
