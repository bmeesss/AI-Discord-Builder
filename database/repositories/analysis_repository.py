"""
Repository for server analysis snapshots.
"""

from __future__ import annotations

from ai.models import ServerAnalysis
from database.repositories.base import BaseRepository


class AnalysisRepository(BaseRepository):
    def save_analysis(
        self,
        analysis: ServerAnalysis,
    ) -> None:
        self.client.table("server_analysis").insert(
            {
                "guild_id": analysis.guild_id,
                "health_score": analysis.health_score,
                "issues": [
                    {
                        "severity": issue.severity,
                        "category": issue.category,
                        "message": issue.message,
                        "recommendation": issue.recommendation,
                    }
                    for issue in analysis.issues
                ],
                "recommendations": analysis.recommendations,
            }
        ).execute()
