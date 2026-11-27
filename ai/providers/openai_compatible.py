"""Adapter for OpenAI-compatible chat completion APIs.

Most cloud providers (OpenAI, Google Gemini, Mistral, OpenRouter, DeepSeek,
Anthropic, xAI, Together AI, Perplexity) expose the same Chat Completions
request shape, so they share this one adapter and differ only in their
``base_url`` and provider label.  No Discord-specific code belongs here.
"""

from __future__ import annotations

import logging
from typing import Any

from ai.providers.base import ProviderError, ProviderHealth

logger = logging.getLogger("ai_discord_builder.ai.providers.openai_compatible")


class OpenAICompatibleProvider:
    """Chat completions adapter parameterised per provider."""

    def __init__(
        self,
        *,
        name: str,
        display: str,
        api_key: str | None,
        model: str,
        key_env: str,
        base_url: str | None = None,
        timeout: int = 60,
        json_mode: bool = True,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError(f"{key_env} is required when AI_PROVIDER={name}.")

        self.name = name
        self.model = model
        self._display = display
        self._timeout = timeout
        self._json_mode = json_mode

        if client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover - environment-specific
                raise ProviderError(
                    "The OpenAI dependency is not installed. "
                    "Install the production requirements first."
                ) from exc

            kwargs: dict[str, Any] = {
                "api_key": api_key,
                "timeout": timeout,
            }
            if base_url:
                kwargs["base_url"] = base_url
            client = AsyncOpenAI(**kwargs)

        self._client = client

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        if self._json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
        except Exception as exc:
            logger.exception("%s request failed", self._display)
            raise ProviderError(
                f"{self._display} request failed. Check the provider logs."
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise ProviderError(f"{self._display} returned an empty response.")
        return content

    async def healthcheck(self) -> ProviderHealth:
        try:
            await self._client.models.list()
        except Exception:
            logger.exception("%s health check failed", self._display)
            return ProviderHealth(
                ok=False,
                provider=self.name,
                model=self.model,
                message=f"{self._display} is not reachable or the API key is invalid.",
            )

        return ProviderHealth(
            ok=True,
            provider=self.name,
            model=self.model,
            message=f"{self._display} is reachable.",
        )

    async def test_model(self) -> ProviderHealth:
        try:
            await self.generate(
                "Return a JSON object with one key named status.",
                'Return {"status":"ok"} and nothing else.',
            )
        except ProviderError:
            return ProviderHealth(
                ok=False,
                provider=self.name,
                model=self.model,
                message=f"{self._display} responded unsuccessfully to the model test.",
            )

        return ProviderHealth(
            ok=True,
            provider=self.name,
            model=self.model,
            message=f"{self._display} model test succeeded.",
        )
