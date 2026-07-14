"""
main.py
Entrypoint van AI-Discord-Builder. Zet logging op, laadt config, registreert
de /ask cog, en start de bot.
"""

import asyncio
import logging
import os

import discord
from discord.ext import commands

import config

# --- Logging setup ---
os.makedirs(os.path.dirname(config.LOG_FILE_PATH) or ".", exist_ok=True)

root_logger = logging.getLogger("ai_discord_builder")
root_logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
root_logger.addHandler(console_handler)

file_handler = logging.FileHandler(config.LOG_FILE_PATH, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
root_logger.addHandler(file_handler)

logger = logging.getLogger("ai_discord_builder.main")


# --- Bot setup ---
intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # nodig om member.guild_permissions goed te resolven

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logger.info("Ingelogd als %s (ID: %s)", bot.user, bot.user.id)
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %d slash command(s)", len(synced))
    except Exception:
        logger.exception("Slash command sync mislukt")


async def load_extensions():
    await bot.load_extension("commands.ask")


async def main():
    config.validate_config()
    async with bot:
        await load_extensions()
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
