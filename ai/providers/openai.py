"""OpenAI provider adapter."""

from __future__ import annotations

import logging
from typing import Any

from ai.providers.base import ProviderError, ProviderHealth

logger = logging.getLogger("ai_discord_builder.ai.providers.openai")


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: int = 60,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is required when AI_PROVIDER=openai.")

        self.model = model
        self._timeout = timeout

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
            logger.exception("OpenAI request failed")
            raise ProviderError("OpenAI request failed. Check the provider logs.") from exc

        if not isinstance(content, str) or not content.strip():
            raise ProviderError("OpenAI returned an empty response.")
        return content

    async def healthcheck(self) -> ProviderHealth:
        try:
            await self._client.models.list()
        except Exception:
            logger.exception("OpenAI health check failed")
            return ProviderHealth(
                ok=False,
                provider=self.name,
                model=self.model,
                message="OpenAI is not reachable or the API key is invalid.",
            )

        return ProviderHealth(
            ok=True,
            provider=self.name,
            model=self.model,
            message="OpenAI is reachable.",
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
                message="OpenAI responded unsuccessfully to the model test.",
            )

        return ProviderHealth(
            ok=True,
            provider=self.name,
            model=self.model,
            message="OpenAI model test succeeded.",
        )
