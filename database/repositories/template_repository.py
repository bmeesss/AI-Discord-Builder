"""
Repository for template candidates.
"""

from __future__ import annotations

from ai.models import TemplateCandidate
from database.repositories.base import BaseRepository


class TemplateRepository(BaseRepository):
    def find_candidates(
        self,
        guild_id: str,
        user_request: str,
        member_count: int | None,
        limit: int = 5,
    ) -> list[TemplateCandidate]:
        request = user_request.lower()
        tags = []

        if "minecraft" in request or "smp" in request:
            tags.append("minecraft")
        if "gaming" in request:
            tags.append("gaming")
        if "professional" in request or "bedrijf" in request:
            tags.append("professional")

        query = (
            self.client.table("templates")
            .select("*")
            .eq("enabled", True)
            .is_("deleted_at", "null")
            .limit(limit)
        )

        if tags:
            query = query.contains("tags", tags[:1])

        result = query.execute()

        return [
            TemplateCandidate(
                id=str(row.get("id")) if row.get("id") else None,
                name=row.get("name", ""),
                description=row.get("description", ""),
                category=row.get("category", "general"),
                version=str(row.get("version", "1")),
                tags=row.get("tags") or [],
                recommended_for=row.get("recommended_for") or [],
            )
            for row in result.data
        ]
