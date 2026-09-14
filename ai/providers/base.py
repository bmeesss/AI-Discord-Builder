"""Provider contracts shared by cloud and local AI backends.

Providers only turn prompts into text.  They do not know anything about Discord,
permissions, action execution, or rollback.  Those concerns stay in the
existing planning and execution pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """A provider could not complete a request.

    Messages from this exception are intentionally safe to show to an operator.
    Provider implementations should log the original exception, but should not
    put response bodies or credentials in the message.
    """


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Result of a provider connectivity check."""

    ok: bool
    provider: str
    model: str
    message: str
    model_available: bool | None = None


class AIProvider(Protocol):
    """Minimal contract required by :class:`ai.client.AIClient`."""

    name: str
    model: str

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Return the provider's raw text response."""
        ...

    async def healthcheck(self) -> ProviderHealth:
        """Check provider connectivity without executing a Discord action."""
        ...

    async def test_model(self) -> ProviderHealth:
        """Run a small model-level smoke test."""
        ...


class ProviderSettings(Protocol):
    """Structural typing helper used by the provider factory in tests."""

    AI_PROVIDER: str
    GROQ_API_KEY: str | None
    GROQ_MODEL: str
    OPENAI_API_KEY: str | None
    OPENAI_MODEL: str
    OPENAI_BASE_URL: str | None
    OLLAMA_BASE_URL: str
    OLLAMA_MODEL: str
    AI_REQUEST_TIMEOUT_SECONDS: int


JSON = dict[str, Any]
