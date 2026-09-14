"""AI provider adapters for Groq, OpenAI and Ollama.

The package initializer intentionally imports only the lightweight contracts.
Provider SDKs and application configuration are loaded when the factory selects
a provider, so importing local tooling does not initialize cloud clients.
"""

from typing import Any

from ai.providers.base import AIProvider, ProviderError, ProviderHealth

SUPPORTED_PROVIDERS = frozenset({"groq", "openai", "ollama"})


def create_provider(*args: Any, **kwargs: Any) -> AIProvider:
    """Lazily import the factory without initializing application config."""

    from ai.providers.factory import create_provider as _create_provider

    return _create_provider(*args, **kwargs)


__all__ = [
    "SUPPORTED_PROVIDERS",
    "AIProvider",
    "ProviderError",
    "ProviderHealth",
    "create_provider",
]
