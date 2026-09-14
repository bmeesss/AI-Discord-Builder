"""
AI planning service.

Orchestrates context rendering, AI plan generation and self-correction retries.
"""

from __future__ import annotations

import asyncio
import logging

import discord

import config
from ai.client import AIClient, AIPlanError
from builder.context import build_server_context, render_server_context
from database.repositories.analysis_repository import AnalysisRepository

logger = logging.getLogger("ai_discord_builder.ai_planning_service")


class AIPlanningService:
    def __init__(
        self,
        ai_client: AIClient | None = None,
        analysis_repository: AnalysisRepository | None = None,
    ):
        self.ai_client = ai_client or AIClient()
        self.analysis_repository = analysis_repository or AnalysisRepository()

    async def build_plan(
        self,
        guild: discord.Guild,
        user: discord.abc.User,
        prompt: str,
    ) -> dict:
        context = await asyncio.to_thread(
            build_server_context,
            guild,
            user,
            prompt,
        )

        if context.analysis:
            try:
                await asyncio.to_thread(
                    self.analysis_repository.save_analysis,
                    context.analysis,
                )
            except Exception:
                logger.exception("Failed saving server analysis")

        rendered_context = render_server_context(context)
        validation_errors: list[str] = []
        last_error: AIPlanError | None = None

        for attempt in range(config.MAX_AI_RETRIES + 1):
            try:
                return await asyncio.wait_for(
                    self.ai_client.generate_plan(
                        prompt,
                        rendered_context,
                        validation_errors=validation_errors or None,
                    ),
                    timeout=config.AI_REQUEST_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                raise AIPlanError("AI request timed out")
            except AIPlanError as e:
                last_error = e
                validation_errors = [
                    str(e),
                    (
                        "Return only the strict JSON schema. Use only available "
                        "capabilities and safe Discord actions."
                    ),
                ]

                if attempt >= config.MAX_AI_RETRIES:
                    break

                logger.info(
                    "AI plan rejected, retrying correction attempt %s/%s",
                    attempt + 1,
                    config.MAX_AI_RETRIES,
                )

        raise last_error or AIPlanError("AI plan generation failed")
