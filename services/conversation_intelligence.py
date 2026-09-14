"""
Conversation intelligence service.

Loads summaries for prompts and stores richer request/plan/result records.
"""

from __future__ import annotations

import logging

from ai.models import ConversationSummary
from database import get_storage
from database.interfaces import ConversationRepository

logger = logging.getLogger("ai_discord_builder.conversation_intelligence")


class ConversationIntelligence:
    def __init__(
        self,
        repository: ConversationRepository | None = None,
    ):
        self.repository = repository or get_storage().conversations

    async def get_summaries(
        self,
        guild_id: int,
        limit: int = 3,
    ) -> list[ConversationSummary]:
        try:
            return await self.repository.get_summaries(
                guild_id=str(guild_id),
                limit=limit,
            )
        except Exception:
            logger.exception("Failed loading conversation summaries")
            return []

    async def save_request_plan(
        self,
        guild_id: int,
        user_id: int,
        username: str,
        request: str,
        plan: dict,
    ) -> None:
        try:
            await self.repository.save_conversation(
                guild_id=str(guild_id),
                user_id=str(user_id),
                username=username,
                request=request,
                ai_plan=plan,
            )
        except Exception:
            logger.exception("Failed saving conversation intelligence")
