"""Local JSON-file storage backend — deliberately database-free.

One small JSON file per concern inside ``DATA_DIR`` (default ``data/``):

- ``actions.json``       — rollback history (per guild, capped);
- ``conversations.json`` — conversation log feeding AI context (capped);
- ``memories.json``      — guild/user preferences (capped);
- ``analysis.json``      — server-analysis snapshots (capped, write-only);
- ``templates.json``     — OPTIONAL, user-provided template list (read-only).

Guarantees:

- Writes are atomic (temp file + ``os.replace``) so a crash can never leave a
  half-written file behind.
- A corrupt file is never fatal: it is moved aside as ``<name>.corrupt`` and
  the store starts empty for that file, with a warning in the log.
- Every method is guild-scoped: data from other guilds is never returned.
- All I/O is tiny and runs inside the bot's event loop; per-file asyncio
  locks serialize concurrent mutations.

On ephemeral hosts (e.g. Render Free) these files live on a temporary
filesystem: they survive normal operation but are lost on restart, redeploy
or spin-down.  See docs/self-hosting.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai.models import (
    ConversationSummary,
    MemoryItem,
    ServerAnalysis,
    TemplateCandidate,
)
from storage.errors import StorageUnavailableError
from storage.storage import Storage

logger = logging.getLogger("ai_discord_builder.storage.json")

# Per-guild caps: files stay small and bounded no matter how long the bot runs.
MAX_ACTIONS_PER_GUILD = 200
MAX_CONVERSATIONS_PER_GUILD = 50
MAX_MEMORIES_PER_GUILD = 50
MAX_ANALYSES_PER_GUILD = 10


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_request_tags(user_request: str) -> list[str]:
    """Keyword heuristic for template matching (same as the old backends)."""

    request = user_request.lower()
    tags: list[str] = []

    if "minecraft" in request or "smp" in request:
        tags.append("minecraft")
    if "gaming" in request:
        tags.append("gaming")
    if "support" in request or "helpdesk" in request:
        tags.append("support")
    if "community" in request:
        tags.append("community")
    if "education" in request or "school" in request:
        tags.append("education")
    if "podcast" in request or "creator" in request:
        tags.append("creator")

    return tags


class JsonFile:
    """One JSON document with atomic writes and corruption tolerance."""

    def __init__(self, path: Path, default: Any) -> None:
        self._path = path
        self._default = default
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> Any:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return copy.deepcopy(self._default)
        except OSError:
            logger.exception("Could not read %s; starting empty", self._path)
            return copy.deepcopy(self._default)

        try:
            return json.loads(raw)
        except ValueError:
            backup = self._path.with_name(self._path.name + ".corrupt")
            logger.warning(
                "Corrupt JSON file %s; moving it to %s and starting empty",
                self._path,
                backup,
            )
            with contextlib.suppress(OSError):
                self._path.replace(backup)
            return copy.deepcopy(self._default)

    def _write(self, data: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=self._path.name + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2, default=str)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    async def load(self) -> Any:
        async with self._lock:
            return self._read()

    async def mutate(self, fn: Callable[[Any], Any]) -> Any:
        """Apply ``fn`` to the document and persist the result atomically."""

        async with self._lock:
            data = self._read()
            result = fn(data)
            self._write(data)
            return result


def _guild_list(document: dict, guild_id: str) -> list:
    entries = document.setdefault(str(guild_id), [])
    if not isinstance(entries, list):
        entries = []
        document[str(guild_id)] = entries
    return entries


def _cap(entries: list, maximum: int) -> None:
    if len(entries) > maximum:
        del entries[:-maximum]


class JsonActionRepository:
    """Rollback history in ``actions.json``."""

    def __init__(self, file: JsonFile) -> None:
        self._file = file

    async def add_action(
        self,
        guild_id: str,
        action: dict,
        user_id: str | None = None,
    ) -> None:
        def _add(document: dict) -> None:
            entries = _guild_list(document, guild_id)
            entries.append(
                {
                    "action": dict(action),
                    "timestamp": _utcnow(),
                    "user_id": str(user_id) if user_id else None,
                }
            )
            _cap(entries, MAX_ACTIONS_PER_GUILD)

        await self._file.mutate(_add)

    async def get_last_actions(
        self,
        guild_id: str,
        amount: int = 10,
    ) -> list[dict[str, Any]]:
        """Newest first (mirrors the behavior builder/history relies on)."""

        if amount <= 0:
            return []

        document = await self._file.load()
        entries = _guild_list(document, guild_id) if guild_id in document else []
        return [
            self._to_entry(entry)
            for entry in reversed(entries[-amount:])
        ]

    async def get_history(self, guild_id: str) -> list[dict[str, Any]]:
        """Full history, oldest first."""

        document = await self._file.load()
        entries = document.get(str(guild_id)) or []
        return [self._to_entry(entry) for entry in entries]

    async def remove_last_actions(self, guild_id: str, amount: int = 1) -> None:
        if amount <= 0:
            return

        def _remove(document: dict) -> None:
            entries = document.get(str(guild_id))
            if isinstance(entries, list) and entries:
                del entries[max(0, len(entries) - amount):]

        await self._file.mutate(_remove)

    async def clear_history(self, guild_id: str) -> None:
        def _clear(document: dict) -> None:
            document.pop(str(guild_id), None)

        await self._file.mutate(_clear)

    @staticmethod
    def _to_entry(entry: Any) -> dict[str, Any]:
        if not isinstance(entry, dict):
            return {"action": {}, "timestamp": None}
        return {
            "action": entry.get("action") or {},
            "timestamp": entry.get("timestamp"),
        }


class JsonConversationRepository:
    """Conversation log in ``conversations.json``."""

    def __init__(self, file: JsonFile) -> None:
        self._file = file

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
        def _save(document: dict) -> None:
            entries = _guild_list(document, guild_id)
            entries.append(
                {
                    "user_id": str(user_id) if user_id else None,
                    "username": username,
                    "request": request,
                    "ai_plan": ai_plan,
                    "result": result,
                    "feedback": feedback,
                    "created_at": _utcnow(),
                }
            )
            _cap(entries, MAX_CONVERSATIONS_PER_GUILD)

        await self._file.mutate(_save)

    async def get_summaries(
        self,
        guild_id: str,
        limit: int = 3,
    ) -> list[ConversationSummary]:
        """Recent conversations condensed into lightweight summaries.

        Without a summarizer service the best available summary is the most
        recent request itself; this keeps the AI-context feature working.
        """

        if limit <= 0:
            return []

        document = await self._file.load()
        entries = document.get(str(guild_id)) or []
        summaries: list[ConversationSummary] = []
        for entry in reversed(entries[-limit:]):
            if not isinstance(entry, dict):
                continue
            request = str(entry.get("request") or "")
            username = str(entry.get("username") or "unknown")
            text = f"{username}: {request}"
            summaries.append(
                ConversationSummary(
                    guild_id=str(guild_id),
                    summary=text[:200],
                    preferences=[],
                    goals=[],
                    updated_at=entry.get("created_at"),
                )
            )
        return summaries


class JsonMemoryRepository:
    """Preferences in ``memories.json``."""

    def __init__(self, file: JsonFile) -> None:
        self._file = file

    async def get_memories(
        self,
        guild_id: str,
        user_id: str | None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        if limit <= 0:
            return []

        document = await self._file.load()
        entries = document.get(str(guild_id)) or []

        selected = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_user = entry.get("user_id")
            if user_id:
                # Guild-level memories and the user's own memories.
                if entry_user is not None and str(entry_user) != str(user_id):
                    continue
            elif entry_user is not None:
                continue
            selected.append(entry)

        selected.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
        return [self._to_item(guild_id, entry) for entry in selected[:limit]]

    async def upsert_memory(
        self,
        guild_id: str,
        user_id: str | None,
        key: str,
        value: str,
        memory_type: str,
        confidence: float,
    ) -> None:
        def _upsert(document: dict) -> None:
            entries = _guild_list(document, guild_id)
            for entry in entries:
                if (
                    isinstance(entry, dict)
                    and entry.get("key") == key
                    and entry.get("memory_type") == memory_type
                    and entry.get("user_id") == (str(user_id) if user_id else None)
                ):
                    entry["value"] = value
                    entry["confidence"] = float(confidence)
                    entry["updated_at"] = _utcnow()
                    return
            entries.append(
                {
                    "id": f"{guild_id}:{user_id or 'guild'}:{memory_type}:{key}",
                    "guild_id": str(guild_id),
                    "user_id": str(user_id) if user_id else None,
                    "key": key,
                    "value": value,
                    "memory_type": memory_type,
                    "confidence": float(confidence),
                    "created_at": _utcnow(),
                    "updated_at": _utcnow(),
                }
            )
            _cap(entries, MAX_MEMORIES_PER_GUILD)

        await self._file.mutate(_upsert)

    @staticmethod
    def _to_item(guild_id: str, entry: dict) -> MemoryItem:
        return MemoryItem(
            id=entry.get("id"),
            guild_id=str(entry.get("guild_id") or guild_id),
            user_id=entry.get("user_id"),
            key=str(entry.get("key") or ""),
            value=str(entry.get("value") or ""),
            memory_type=str(entry.get("memory_type") or "preference"),
            confidence=float(entry.get("confidence") or 0.5),
            created_at=entry.get("created_at"),
            updated_at=entry.get("updated_at"),
        )


class JsonAnalysisRepository:
    """Write-only analysis snapshots in ``analysis.json``."""

    def __init__(self, file: JsonFile) -> None:
        self._file = file

    async def save_analysis(self, analysis: ServerAnalysis) -> None:
        payload = {
            "guild_id": str(analysis.guild_id),
            "health_score": int(analysis.health_score),
            "issues": [
                {
                    "severity": issue.severity,
                    "category": issue.category,
                    "message": issue.message,
                    "recommendation": issue.recommendation,
                }
                for issue in analysis.issues
            ],
            "recommendations": list(analysis.recommendations),
            "created_at": analysis.created_at,
        }

        def _save(document: dict) -> None:
            entries = _guild_list(document, analysis.guild_id)
            entries.append(payload)
            _cap(entries, MAX_ANALYSES_PER_GUILD)

        await self._file.mutate(_save)


class JsonTemplateRepository:
    """Optional user-provided templates in ``templates.json`` (read-only)."""

    def __init__(self, file: JsonFile) -> None:
        self._file = file

    async def find_candidates(
        self,
        guild_id: str,
        user_request: str,
        member_count: int | None,
        limit: int = 5,
    ) -> list[TemplateCandidate]:
        if limit <= 0:
            return []

        document = await self._file.load()
        if not isinstance(document, list):
            return []

        request_tags = set(extract_request_tags(user_request))

        def enabled(entry: Any) -> bool:
            return isinstance(entry, dict) and entry.get("enabled", True)

        tagged = [
            entry
            for entry in document
            if enabled(entry)
            and request_tags
            and set(entry.get("tags") or []) & request_tags
        ]
        others = [
            entry
            for entry in document
            if enabled(entry) and entry not in tagged
        ]

        candidates: list[TemplateCandidate] = []
        for entry in (tagged + others)[:limit]:
            candidates.append(
                TemplateCandidate(
                    id=str(entry.get("id")) if entry.get("id") else None,
                    name=str(entry.get("name") or ""),
                    description=str(entry.get("description") or ""),
                    category=str(entry.get("category") or ""),
                    version=str(entry.get("version") or "1"),
                    tags=[str(tag) for tag in entry.get("tags") or []],
                    recommended_for=[
                        str(item) for item in entry.get("recommended_for") or []
                    ],
                )
            )
        return candidates


class JsonStorage:
    """The JSON-file storage backend (repositories + lifecycle)."""

    name = "json"

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)

        self._actions_file = JsonFile(self._data_dir / "actions.json", {})
        self._conversations_file = JsonFile(
            self._data_dir / "conversations.json", {}
        )
        self._memories_file = JsonFile(self._data_dir / "memories.json", {})
        self._analysis_file = JsonFile(self._data_dir / "analysis.json", {})
        self._templates_file = JsonFile(self._data_dir / "templates.json", [])

        self.actions = JsonActionRepository(self._actions_file)
        self.conversations = JsonConversationRepository(self._conversations_file)
        self.memories = JsonMemoryRepository(self._memories_file)
        self.analysis = JsonAnalysisRepository(self._analysis_file)
        self.templates = JsonTemplateRepository(self._templates_file)

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    async def initialize(self) -> None:
        """Create the data directory and verify it is usable.  Fails loudly."""

        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            probe = self._data_dir / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise StorageUnavailableError(
                f"Data directory {self._data_dir} is not usable: {exc}. "
                "Set DATA_DIR to a writable path."
            ) from exc

        # Touch-load every store once so corrupt files surface at startup.
        for file in (
            self._actions_file,
            self._conversations_file,
            self._memories_file,
            self._analysis_file,
            self._templates_file,
        ):
            file._read()  # noqa: SLF001 - internal warm-up

        logger.info("JSON storage ready (data dir: %s)", self._data_dir)

    async def close(self) -> None:
        """No persistent connections to close; kept for lifecycle symmetry."""

    async def healthcheck(self) -> tuple[bool, str]:
        try:
            if not self._data_dir.is_dir():
                return False, f"data directory {self._data_dir} is missing"
            probe = self._data_dir / ".health-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return False, f"json storage not writable: {exc.__class__.__name__}"
        return True, "json storage ok"


def create_json_storage(data_dir: str | Path | None = None) -> Storage:
    """Build the JSON-file storage container (no connection, no migration)."""

    if data_dir is None:
        import config

        data_dir = config.DATA_DIR

    backend = JsonStorage(data_dir)
    return Storage(
        backend="json",
        actions=backend.actions,
        conversations=backend.conversations,
        memories=backend.memories,
        analysis=backend.analysis,
        templates=backend.templates,
        _lifecycle=backend,
    )
