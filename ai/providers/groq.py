"""Groq provider adapter.

The adapter deliberately exposes the same small interface as the OpenAI and
Ollama adapters.  No Discord-specific code belongs here.
"""

from __future__ import annotations

import logging
from typing import Any

from ai.providers.base import ProviderError, ProviderHealth

logger = logging.getLogger("ai_discord_builder.ai.providers.groq")


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int = 60,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError("GROQ_API_KEY is required when AI_PROVIDER=groq.")

        self.model = model
        self._timeout = timeout

        if client is None:
            try:
                from groq import AsyncGroq
            except ImportError as exc:  # pragma: no cover - environment-specific
                raise ProviderError(
                    "The Groq dependency is not installed. "
                    "Install the production requirements first."
                ) from exc

            client = AsyncGroq(api_key=api_key, timeout=timeout)

        self._client = client

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
        except Exception as exc:
            logger.exception("Groq request failed")
            raise ProviderError("Groq request failed. Check the provider logs.") from exc

        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Groq returned an empty response.")
        return content

    async def healthcheck(self) -> ProviderHealth:
        try:
            await self._client.models.list()
        except Exception:
            logger.exception("Groq health check failed")
            return ProviderHealth(
                ok=False,
                provider=self.name,
                model=self.model,
                message="Groq is not reachable or the API key is invalid.",
            )

        return ProviderHealth(
            ok=True,
            provider=self.name,
            model=self.model,
            message="Groq is reachable.",
        )

    async def test_model(self) -> ProviderHealth:
        try:
            await self.generate(
                "Return a JSON object with one key named status.",
                "Return {\"status\":\"ok\"} and nothing else.",
            )
        except ProviderError:
            return ProviderHealth(
                ok=False,
                provider=self.name,
                model=self.model,
                message="Groq responded unsuccessfully to the model test.",
            )

        return ProviderHealth(
            ok=True,
            provider=self.name,
            model=self.model,
            message="Groq model test succeeded.",
        )
