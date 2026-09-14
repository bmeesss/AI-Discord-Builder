"""PostgreSQL implementation of the TemplateRepository protocol."""

from __future__ import annotations

import json

from ai.models import TemplateCandidate
from database.postgres.repositories.base import (
    BasePostgresRepository,
    loads_json,
)

_SELECT_TEMPLATES = """
select id, name, description, category, version, tags, recommended_for
from templates
where enabled
and deleted_at is null
limit $1
"""

_SELECT_TEMPLATES_BY_TAG = """
select id, name, description, category, version, tags, recommended_for
from templates
where enabled
and deleted_at is null
and tags @> $1::jsonb
limit $2
"""


def extract_request_tags(user_request: str) -> list[str]:
    """Keyword heuristic, identical to the Supabase implementation."""

    request = user_request.lower()
    tags: list[str] = []

    if "minecraft" in request or "smp" in request:
        tags.append("minecraft")
    if "gaming" in request:
        tags.append("gaming")
    if "professional" in request or "bedrijf" in request:
        tags.append("professional")

    return tags


class PostgresTemplateRepository(BasePostgresRepository):
    async def find_candidates(
        self,
        guild_id: str,
        user_request: str,
        member_count: int | None,
        limit: int = 5,
    ) -> list[TemplateCandidate]:
        tags = extract_request_tags(user_request)

        async with await self._acquire() as conn:
            if tags:
                rows = await conn.fetch(
                    _SELECT_TEMPLATES_BY_TAG,
                    json.dumps(tags[:1]),
                    int(limit),
                )
            else:
                rows = await conn.fetch(_SELECT_TEMPLATES, int(limit))

        return [
            TemplateCandidate(
                id=str(row["id"]) if row["id"] else None,
                name=row["name"] or "",
                description=row["description"] or "",
                category=row["category"] or "general",
                version=str(row["version"] or "1"),
                tags=loads_json(row["tags"], default=[]),
                recommended_for=loads_json(row["recommended_for"], default=[]),
            )
            for row in rows
        ]
