"""PostgreSQL implementation of the ConversationRepository protocol."""

from __future__ import annotations

import json

from ai.models import ConversationSummary
from database.postgres.repositories.base import (
    BasePostgresRepository,
    loads_json,
    to_iso,
)

_INSERT_CONVERSATION = """
insert into conversations (
    guild_id,
    user_id,
    username,
    message,
    response,
    ai_plan,
    result,
    feedback
)
values ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb)
"""

_SELECT_SUMMARIES = """
select guild_id, summary, preferences, goals, updated_at
from conversation_summaries
where guild_id = $1
and deleted_at is null
order by updated_at desc
limit $2
"""


class PostgresConversationRepository(BasePostgresRepository):
    async def save_conversation(
        self,
        guild_id: str,
        user_id: str,
        username: str,
        request: str,
        ai_plan: dict,
        result: dict | None = None,
        feedback: dict | None = None,
    ) -> None:
        response_text = json.dumps(ai_plan, default=str)
        async with await self._acquire() as conn:
            await conn.execute(
                _INSERT_CONVERSATION,
                str(guild_id),
                str(user_id) if user_id else None,
                username,
                request,
                response_text,
                json.dumps(ai_plan, default=str),
                json.dumps(result, default=str) if result is not None else None,
                json.dumps(feedback, default=str) if feedback is not None else None,
            )

    async def get_summaries(
        self,
        guild_id: str,
        limit: int = 3,
    ) -> list[ConversationSummary]:
        async with await self._acquire() as conn:
            rows = await conn.fetch(_SELECT_SUMMARIES, str(guild_id), int(limit))

        return [
            ConversationSummary(
                guild_id=str(row["guild_id"]),
                summary=row["summary"] or "",
                preferences=loads_json(row["preferences"], default=[]),
                goals=loads_json(row["goals"], default=[]),
                updated_at=to_iso(row["updated_at"]),
            )
            for row in rows
        ]
