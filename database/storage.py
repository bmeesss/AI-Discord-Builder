"""Storage container: alle repositories + backend-lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from database.interfaces import (
    ActionRepository,
    AnalysisRepository,
    ConversationRepository,
    MemoryRepository,
    StorageBackend,
    TemplateRepository,
)


@dataclass
class Storage:
    """Wat applicatiecode te zien krijgt — nooit een concrete SDK."""

    backend: str
    actions: ActionRepository
    conversations: ConversationRepository
    memories: MemoryRepository
    analysis: AnalysisRepository
    templates: TemplateRepository
    _lifecycle: StorageBackend

    async def initialize(self) -> None:
        await self._lifecycle.initialize()

    async def close(self) -> None:
        await self._lifecycle.close()

    async def healthcheck(self) -> tuple[bool, str]:
        return await self._lifecycle.healthcheck()
