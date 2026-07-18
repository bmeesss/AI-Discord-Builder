"""
Repository for conversations and conversation summaries.
"""

from __future__ import annotations

import json

from ai.models import ConversationSummary
from database.repositories.base import BaseRepository


class ConversationRepository(BaseRepository):
    def save_conversation(
        self,
        guild_id: str,
        user_id: str,
        username: str,
        request: str,
        ai_plan: dict,
        result: dict | None = None,
        feedback: dict | None = None,
    ) -> None:
        self.client.table("conversations").insert(
            {
                "guild_id": guild_id,
                "user_id": user_id,
                "username": username,
                "message": request,
                "response": json.dumps(ai_plan, default=str),
                "ai_plan": ai_plan,
                "result": result,
                "feedback": feedback,
            }
        ).execute()

    def get_summaries(
        self,
        guild_id: str,
        limit: int = 3,
    ) -> list[ConversationSummary]:
        result = (
            self.client.table("conversation_summaries")
            .select("*")
            .eq("guild_id", guild_id)
            .is_("deleted_at", "null")
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )

        return [
            ConversationSummary(
                guild_id=str(row["guild_id"]),
                summary=row.get("summary", ""),
                preferences=row.get("preferences") or [],
                goals=row.get("goals") or [],
                updated_at=row.get("updated_at"),
            )
            for row in result.data
        ]
