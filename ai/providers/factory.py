"""Factory for the supported AI providers."""

from __future__ import annotations

from typing import Any

import config
from ai.providers.base import AIProvider, ProviderError, ProviderSettings
from ai.providers.groq import GroqProvider
from ai.providers.ollama import OllamaProvider
from ai.providers.openai import OpenAIProvider

SUPPORTED_PROVIDERS = frozenset({"groq", "openai", "ollama"})


def create_provider(
    provider_name: str | None = None,
    settings: ProviderSettings | Any | None = None,
) -> AIProvider:
    """Create a provider without coupling the provider to Discord code.

    ``settings`` is injectable so provider selection can be tested without
    mutating process environment variables.
    """

    values = settings or config
    name = (provider_name or values.AI_PROVIDER).strip().lower()
    timeout = int(getattr(values, "AI_REQUEST_TIMEOUT_SECONDS", 60))

    if name == "groq":
        return GroqProvider(
            api_key=values.GROQ_API_KEY,
            model=values.GROQ_MODEL,
            timeout=timeout,
        )

    if name == "openai":
        return OpenAIProvider(
            api_key=values.OPENAI_API_KEY,
            model=values.OPENAI_MODEL,
            base_url=getattr(values, "OPENAI_BASE_URL", None),
            timeout=timeout,
        )

    if name == "ollama":
        try:
            return OllamaProvider(
                base_url=values.OLLAMA_BASE_URL,
                model=values.OLLAMA_MODEL,
                timeout=timeout,
            )
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

    supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
    raise ProviderError(
        f"Unknown AI_PROVIDER={name!r}. Supported providers: {supported}."
    )
