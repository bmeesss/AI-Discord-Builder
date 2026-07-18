"""
Repository for guild/user memories.
"""

from __future__ import annotations

from ai.models import MemoryItem
from database.repositories.base import BaseRepository


class MemoryRepository(BaseRepository):
    def get_memories(
        self,
        guild_id: str,
        user_id: str | None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        query = (
            self.client.table("memories")
            .select("*")
            .eq("guild_id", guild_id)
            .is_("deleted_at", "null")
            .order("confidence", desc=True)
            .limit(limit)
        )

        if user_id:
            query = query.or_(
                f"user_id.is.null,user_id.eq.{user_id}"
            )
        else:
            query = query.is_("user_id", "null")

        result = query.execute()

        return [
            MemoryItem(
                id=str(row.get("id")) if row.get("id") else None,
                guild_id=str(row["guild_id"]),
                user_id=str(row["user_id"]) if row.get("user_id") else None,
                key=row.get("memory_key", ""),
                value=row.get("memory_value", ""),
                memory_type=row.get("memory_type", "preference"),
                confidence=float(row.get("confidence") or 0.5),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
            for row in result.data
        ]

    def upsert_memory(
        self,
        guild_id: str,
        user_id: str | None,
        key: str,
        value: str,
        memory_type: str,
        confidence: float,
    ) -> None:
        self.client.table("memories").upsert(
            {
                "guild_id": guild_id,
                "user_id": user_id,
                "memory_key": key,
                "memory_value": value,
                "memory_type": memory_type,
                "confidence": confidence,
            },
            on_conflict="guild_id,user_id,memory_type,memory_key",
        ).execute()
