"""Provider-neutrale storage-interfaces.

Application code depends on these protocols only.  Whether the concrete
backend is PostgreSQL or Supabase is decided by the storage factory and is
invisible to services, commands and the builder layer.

Security boundary: repositories persist state/history only.  They never
decide whether a Discord action is allowed.  Guild isolation is enforced
server-side inside every repository method; callers always pass the guild
scope explicitly and records from other guilds are never returned.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ai.models import (
    ConversationSummary,
    MemoryItem,
    ServerAnalysis,
    TemplateCandidate,
)


@runtime_checkable
class ActionRepository(Protocol):
    """Rollback history storage.

    All returned entries use the shape::

        {"action": <original action dict>, "timestamp": <iso string>}
    """

    async def add_action(
        self,
        guild_id: str,
        action: dict,
        user_id: str | None = None,
    ) -> None:
        """Persist one successfully executed action."""
        ...

    async def get_last_actions(
        self,
        guild_id: str,
        amount: int = 10,
    ) -> list[dict[str, Any]]:
        """Return the newest ``amount`` actions, newest first."""
        ...

    async def get_history(self, guild_id: str) -> list[dict[str, Any]]:
        """Return the full guild history, oldest first."""
        ...

    async def remove_last_actions(
        self,
        guild_id: str,
        amount: int = 1,
    ) -> None:
        """Delete the newest ``amount`` actions (after rollback)."""
        ...

    async def clear_history(self, guild_id: str) -> None:
        """Delete every stored action for the guild."""
        ...


@runtime_checkable
class ConversationRepository(Protocol):
    async def save_conversation(
        self,
        guild_id: str,
        user_id: str,
        username: str,
        request: str,
        ai_plan: dict,
        result: dict | None = None,
        feedback: dict | None = None,
    ) -> None:
        ...

    async def get_summaries(
        self,
        guild_id: str,
        limit: int = 3,
    ) -> list[ConversationSummary]:
        ...


@runtime_checkable
class MemoryRepository(Protocol):
    async def get_memories(
        self,
        guild_id: str,
        user_id: str | None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        ...

    async def upsert_memory(
        self,
        guild_id: str,
        user_id: str | None,
        key: str,
        value: str,
        memory_type: str,
        confidence: float,
    ) -> None:
        ...


@runtime_checkable
class AnalysisRepository(Protocol):
    async def save_analysis(self, analysis: ServerAnalysis) -> None:
        ...


@runtime_checkable
class TemplateRepository(Protocol):
    async def find_candidates(
        self,
        guild_id: str,
        user_request: str,
        member_count: int | None,
        limit: int = 5,
    ) -> list[TemplateCandidate]:
        ...


class StorageBackend(Protocol):
    """Lifecycle of one concrete storage implementation."""

    name: str

    async def initialize(self) -> None:
        """Connect, verify and (optionally) migrate.  Fail loudly."""
        ...

    async def close(self) -> None:
        """Release connections gracefully."""
        ...

    async def healthcheck(self) -> tuple[bool, str]:
        """Return ``(ok, detail)``; never raises."""
        ...
