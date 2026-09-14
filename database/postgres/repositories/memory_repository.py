"""PostgreSQL implementation of the MemoryRepository protocol."""

from __future__ import annotations

from ai.models import MemoryItem
from database.postgres.repositories.base import (
    BasePostgresRepository,
    to_iso,
)

# Two fixed query shapes; user input is only ever bound to parameters.
_SELECT_MEMORIES_WITH_USER = """
select id, guild_id, user_id, memory_key, memory_value,
       memory_type, confidence, created_at, updated_at
from memories
where guild_id = $1
and deleted_at is null
and (user_id is null or user_id = $2)
order by confidence desc
limit $3
"""

_SELECT_MEMORIES_GUILD_ONLY = """
select id, guild_id, user_id, memory_key, memory_value,
       memory_type, confidence, created_at, updated_at
from memories
where guild_id = $1
and deleted_at is null
and user_id is null
order by confidence desc
limit $2
"""

_UPSERT_MEMORY = """
insert into memories (
    guild_id,
    user_id,
    memory_key,
    memory_value,
    memory_type,
    confidence
)
values ($1, $2, $3, $4, $5, $6)
on conflict (guild_id, user_id, memory_type, memory_key)
where deleted_at is null
do update set
    memory_value = excluded.memory_value,
    confidence = excluded.confidence,
    updated_at = now()
"""


class PostgresMemoryRepository(BasePostgresRepository):
    async def get_memories(
        self,
        guild_id: str,
        user_id: str | None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        async with await self._acquire() as conn:
            if user_id:
                rows = await conn.fetch(
                    _SELECT_MEMORIES_WITH_USER,
                    str(guild_id),
                    str(user_id),
                    int(limit),
                )
            else:
                # Guild-level memories only.
                rows = await conn.fetch(
                    _SELECT_MEMORIES_GUILD_ONLY,
                    str(guild_id),
                    int(limit),
                )

        return [
            MemoryItem(
                id=str(row["id"]) if row["id"] else None,
                guild_id=str(row["guild_id"]),
                user_id=str(row["user_id"]) if row["user_id"] else None,
                key=row["memory_key"] or "",
                value=row["memory_value"] or "",
                memory_type=row["memory_type"] or "preference",
                confidence=float(row["confidence"] or 0.5),
                created_at=to_iso(row["created_at"]),
                updated_at=to_iso(row["updated_at"]),
            )
            for row in rows
        ]

    async def upsert_memory(
        self,
        guild_id: str,
        user_id: str | None,
        key: str,
        value: str,
        memory_type: str,
        confidence: float,
    ) -> None:
        async with await self._acquire() as conn:
            await conn.execute(
                _UPSERT_MEMORY,
                str(guild_id),
                str(user_id) if user_id else None,
                key,
                value,
                memory_type,
                float(confidence),
            )
