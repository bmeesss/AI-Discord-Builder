"""Supabase storage backend — optioneel alternatief voor PostgreSQL.

De Supabase SDK is synchroon; deze facade biedt dezelfde async interfaces
als de PostgreSQL-backend door elke call via ``asyncio.to_thread`` uit te
voeren.  De bestaande sync repositories uit ``database/repositories``
blijven de bron van waarheid voor de Supabase-queries; deze module voegt
alleen lifecycle (initialize/close/healthcheck) en de async vorm toe.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from database.errors import (
    StorageNotConfiguredError,
    StorageUnavailableError,
)
from database.repositories.analysis_repository import AnalysisRepository
from database.repositories.conversation_repository import (
    ConversationRepository,
)
from database.repositories.memory_repository import MemoryRepository
from database.repositories.template_repository import TemplateRepository

logger = logging.getLogger("ai_discord_builder.database.supabase_backend")


def create_supabase_client(url: str | None, key: str | None):
    """Create a Supabase client with clear config errors (no secrets logged)."""

    if not url or not key:
        raise StorageNotConfiguredError(
            "DATABASE_BACKEND=supabase requires SUPABASE_URL and SUPABASE_KEY."
        )

    try:
        from supabase import create_client
    except ImportError as exc:
        raise StorageNotConfiguredError(
            "The 'supabase' package is not installed but "
            "DATABASE_BACKEND=supabase was selected."
        ) from exc

    return create_client(url, key)


class SupabaseActionRepository:
    """Action history via PostgREST (same queries as before this refactor)."""

    def __init__(self, client) -> None:
        self._client = client

    # -- sync internals, kept identical to the pre-refactor behavior -------

    def _insert(self, guild_id: str, action: dict, user_id: str | None) -> None:
        self._client.table("actions").insert(
            {
                "guild_id": str(guild_id),
                "user_id": str(user_id) if user_id else None,
                "action_type": action.get("type"),
                "data": action,
            }
        ).execute()

    def _last_actions(self, guild_id: str, amount: int) -> list[dict]:
        result = (
            self._client.table("actions")
            .select("*")
            .eq("guild_id", str(guild_id))
            .order("created_at", desc=True)
            .limit(int(amount))
            .execute()
        )
        return [
            {
                "action": row["data"],
                "timestamp": row["created_at"],
            }
            for row in result.data
        ]

    def _history(self, guild_id: str) -> list[dict]:
        result = (
            self._client.table("actions")
            .select("*")
            .eq("guild_id", str(guild_id))
            .order("created_at", desc=False)
            .execute()
        )
        return [
            {
                "action": row["data"],
                "timestamp": row["created_at"],
            }
            for row in result.data
        ]

    def _remove_last(self, guild_id: str, amount: int) -> None:
        rows = (
            self._client.table("actions")
            .select("id")
            .eq("guild_id", str(guild_id))
            .order("created_at", desc=True)
            .limit(int(amount))
            .execute()
        )
        for row in rows.data:
            self._client.table("actions").delete().eq("id", row["id"]).execute()

    def _clear(self, guild_id: str) -> None:
        self._client.table("actions").delete().eq("guild_id", str(guild_id)).execute()

    # -- async protocol surface --------------------------------------------

    async def add_action(
        self,
        guild_id: str,
        action: dict,
        user_id: str | None = None,
    ) -> None:
        await asyncio.to_thread(self._insert, guild_id, action, user_id)

    async def get_last_actions(
        self,
        guild_id: str,
        amount: int = 10,
    ) -> list[dict[str, Any]]:
        if amount <= 0:
            return []
        return await asyncio.to_thread(self._last_actions, guild_id, amount)

    async def get_history(self, guild_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._history, guild_id)

    async def remove_last_actions(
        self,
        guild_id: str,
        amount: int = 1,
    ) -> None:
        if amount <= 0:
            return
        await asyncio.to_thread(self._remove_last, guild_id, amount)

    async def clear_history(self, guild_id: str) -> None:
        await asyncio.to_thread(self._clear, guild_id)


class _AsyncFacade:
    """Wrap a sync repository's methods with asyncio.to_thread."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str):
        attribute = getattr(self._delegate, name)
        if not callable(attribute):
            return attribute

        async def run(*args, **kwargs):
            return await asyncio.to_thread(attribute, *args, **kwargs)

        return run


class SupabaseBackend:
    name = "supabase"

    def __init__(self, url: str | None, key: str | None) -> None:
        self._client = create_supabase_client(url, key)

        self.actions = SupabaseActionRepository(self._client)
        self.conversations = _AsyncFacade(ConversationRepository(self._client))
        self.memories = _AsyncFacade(MemoryRepository(self._client))
        self.analysis = _AsyncFacade(AnalysisRepository(self._client))
        self.templates = _AsyncFacade(TemplateRepository(self._client))

    def _ping_sync(self) -> None:
        self._client.table("actions").select("id").limit(1).execute()

    async def initialize(self) -> None:
        """Verify reachability clearly instead of failing mid-session."""

        logger.info("Initializing Supabase backend")
        try:
            await asyncio.to_thread(self._ping_sync)
        except Exception as exc:
            raise StorageUnavailableError(
                "Could not reach the configured Supabase project or its "
                f"'actions' table: {exc}"
            ) from exc
        logger.info("Supabase backend ready")

    async def close(self) -> None:
        """The Supabase SDK keeps no connections that need closing."""

    async def healthcheck(self) -> tuple[bool, str]:
        try:
            await asyncio.to_thread(self._ping_sync)
        except Exception as exc:  # noqa: BLE001 - healthchecks nooit laten crashen
            return False, f"Supabase healthcheck failed: {exc}"
        return True, "supabase ok"
