"""OpenAI provider adapter.

Kept as a thin, signature-compatible wrapper around the shared
:class:`ai.providers.openai_compatible.OpenAICompatibleProvider` so existing
callers and tests keep working unchanged.
"""

from __future__ import annotations

from typing import Any

from ai.providers.openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        timeout: int = 60,
        client: Any | None = None,
    ) -> None:
        super().__init__(
            name="openai",
            display="OpenAI",
            api_key=api_key,
            model=model,
            key_env="OPENAI_API_KEY",
            base_url=base_url,
            timeout=timeout,
            json_mode=True,
            client=client,
        )
