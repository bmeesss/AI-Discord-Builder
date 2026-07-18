"""
Guild/user memory service.

Memory supports preferences and long-term context, but Discord state always
remains the source of truth.
"""

from __future__ import annotations

import logging

from ai.models import MemoryItem
from database.repositories.memory_repository import MemoryRepository


logger = logging.getLogger("ai_discord_builder.memory_service")


class MemoryService:
    def __init__(
        self,
        repository: MemoryRepository | None = None,
    ):
        self.repository = repository or MemoryRepository()

    def get_relevant_memories(
        self,
        guild_id: int,
        user_id: int | None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        try:
            return self.repository.get_memories(
                guild_id=str(guild_id),
                user_id=str(user_id) if user_id else None,
                limit=limit,
            )
        except Exception:
            logger.exception("Failed loading memories")
            return []

    def remember_preference(
        self,
        guild_id: int,
        key: str,
        value: str,
        user_id: int | None = None,
        confidence: float = 0.7,
    ) -> None:
        try:
            self.repository.upsert_memory(
                guild_id=str(guild_id),
                user_id=str(user_id) if user_id else None,
                key=key,
                value=value,
                memory_type="preference",
                confidence=confidence,
            )
        except Exception:
            logger.exception("Failed saving memory")
