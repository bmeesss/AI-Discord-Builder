"""Backwards-compatible conversation persistence over the storage layer."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

from database import get_storage


logger = logging.getLogger(
    "ai_discord_builder.conversations"
)


async def save_conversation(
    guild_id: int,
    user_id: int,
    username: str,
    message: str,
    response: str
):

    try:
        try:
            ai_plan = json.loads(response)
        except Exception:
            ai_plan = {
                "raw": response,
            }

        await get_storage().conversations.save_conversation(
            guild_id=str(guild_id),
            user_id=str(user_id),
            username=username,
            request=message,
            ai_plan=ai_plan,
        )


        logger.info(
            "Saved conversation for %s",
            username
        )


    except Exception:

        logger.exception(
            "Failed saving conversation"
        )


async def get_recent_conversations(
    guild_id: int,
    limit: int = 10
):

    try:
        return [
            asdict(summary)
            for summary in await get_storage().conversations.get_summaries(
                guild_id=str(guild_id),
                limit=limit,
            )
        ]


    except Exception:

        logger.exception(
            "Failed loading conversations"
        )

        return []
