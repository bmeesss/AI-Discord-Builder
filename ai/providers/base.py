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
    """Structural typing helper used by the provider factory in tests.

    Provider-specific keys and models are read through ``getattr`` against
    the env-var names in :mod:`ai.providers.registry`, so only the generic
    settings are part of this contract.
    """

    AI_PROVIDER: str
    AI_REQUEST_TIMEOUT_SECONDS: int

    def __getattr__(self, name: str) -> Any: ...


JSON = dict[str, Any]
