"""PostgreSQL implementation of the AnalysisRepository protocol."""

from __future__ import annotations

import json

from ai.models import ServerAnalysis
from database.postgres.repositories.base import BasePostgresRepository

_INSERT_ANALYSIS = """
insert into server_analysis (guild_id, health_score, issues, recommendations)
values ($1, $2, $3::jsonb, $4::jsonb)
"""


class PostgresAnalysisRepository(BasePostgresRepository):
    async def save_analysis(self, analysis: ServerAnalysis) -> None:
        issues = [
            {
                "severity": issue.severity,
                "category": issue.category,
                "message": issue.message,
                "recommendation": issue.recommendation,
            }
            for issue in analysis.issues
        ]

        async with await self._acquire() as conn:
            await conn.execute(
                _INSERT_ANALYSIS,
                str(analysis.guild_id),
                int(analysis.health_score),
                json.dumps(issues, default=str),
                json.dumps(list(analysis.recommendations), default=str),
            )
