"""AI Discord Builder runtime entrypoint.

The runtime stays intentionally small: Discord remains the source of truth for
server state, while the AI provider only returns validated plan text.  The
optional local-AI setup is a separate CLI (``python -m setup``); bot startup
never installs software or downloads models.

Startup order is strict: configuration is validated and the database backend
(including migrations) is initialized *before* the Discord connection opens.
A broken database therefore stops startup immediately with a clear error
instead of crashing mid-session.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import threading

import discord
from discord.ext import commands

import config
import database
from database.errors import StorageError
from web.app import app, set_component, set_ready

logger = logging.getLogger("ai_discord_builder")
main_logger = logging.getLogger("ai_discord_builder.main")

STORAGE_HEALTH_INTERVAL_SECONDS = 15.0


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


async def run_bot() -> None:
    async with bot:
        await load_extensions()
        await bot.start(config.DISCORD_TOKEN)


async def monitor_storage(storage: database.Storage) -> None:
    """Keep the readiness component status of the database up to date."""

    while True:
        try:
            ok, detail = await storage.healthcheck()
        except Exception as exc:  # pragma: no cover - defensive
            ok, detail = False, f"healthcheck error: {exc}"
        set_component("database", ok, detail)
        await asyncio.sleep(STORAGE_HEALTH_INTERVAL_SECONDS)


async def main() -> None:
    configure_logging()
    config.validate_config()
    set_ready(False)

    try:
        storage = await database.initialize_storage()
    except StorageError as exc:
        raise SystemExit(
            "Database initialization failed "
            f"({exc.__class__.__name__}): {exc}. "
            "Check DATABASE_BACKEND/DATABASE_URL or your Supabase settings; "
            "see docs/self-hosting.md."
        ) from exc

    ok, detail = await storage.healthcheck()
    set_component("database", ok, detail)
    monitor = asyncio.create_task(monitor_storage(storage))

    start_web_thread()

    # Graceful shutdown on SIGINT/SIGTERM (e.g. `docker compose stop`).
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signum, stop_event.set)

    bot_task = asyncio.create_task(run_bot())
    stop_task = asyncio.create_task(stop_event.wait())

    try:
        done, _pending = await asyncio.wait(
            {bot_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if stop_task in done and not bot_task.done():
            main_logger.info("Shutdown signal received; stopping bot")
            bot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await bot_task

        stop_task.cancel()

        # Propagate unexpected bot errors (failed login, extension errors).
        if bot_task in done and not bot_task.cancelled():
            bot_task.result()
    finally:
        monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor
        await database.close_storage()
        main_logger.info("Database connections closed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
