"""
Template intelligence service.

Selects candidate templates for the AI based on prompt and guild size.
"""

from __future__ import annotations

import logging

from ai.models import TemplateCandidate
from database import get_storage
from database.interfaces import TemplateRepository


logger = logging.getLogger("ai_discord_builder.template_service")


class TemplateService:
    def __init__(
        self,
        repository: TemplateRepository | None = None,
    ):
        self.repository = repository or get_storage().templates

    async def get_candidates(
        self,
        guild_id: int,
        user_request: str,
        member_count: int | None,
        limit: int = 5,
    ) -> list[TemplateCandidate]:
        try:
            return await self.repository.find_candidates(
                guild_id=str(guild_id),
                user_request=user_request,
                member_count=member_count,
                limit=limit,
            )
        except Exception:
            logger.exception("Failed loading template candidates")
            return []
