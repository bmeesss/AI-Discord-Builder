"""Factory for the supported AI providers."""

from __future__ import annotations

from typing import Any

import config
from ai.providers.base import AIProvider, ProviderError, ProviderSettings
from ai.providers.groq import GroqProvider
from ai.providers.ollama import OllamaProvider
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.providers.registry import CLOUD_PRESETS, SUPPORTED_PROVIDERS

__all__ = ["SUPPORTED_PROVIDERS", "create_provider"]


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

    if name == "ollama":
        try:
            return OllamaProvider(
                base_url=values.OLLAMA_BASE_URL,
                model=values.OLLAMA_MODEL,
                timeout=timeout,
            )
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

    preset = CLOUD_PRESETS.get(name)
    if preset is not None:
        base_url = preset.base_url
        if name == "openai":
            # Optional OpenAI-compatible endpoint override (kept for
            # backwards compatibility); the other presets use their
            # provider's own fixed endpoint.
            base_url = getattr(values, "OPENAI_BASE_URL", None) or None
        return OpenAICompatibleProvider(
            name=preset.name,
            display=preset.display,
            api_key=getattr(values, preset.api_key_env, None),
            key_env=preset.api_key_env,
            model=getattr(values, preset.model_env, None) or preset.default_model,
            base_url=base_url,
            timeout=timeout,
            json_mode=preset.json_mode,
        )

    supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
    raise ProviderError(
        f"Unknown AI_PROVIDER={name!r}. Supported providers: {supported}."
    )
