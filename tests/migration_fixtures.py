"""Synthetic Supabase fixtures for the migration tests.

Everything here is generated: no production data, no network and no real
Supabase project.  The fixtures deliberately cover the awkward cases the tool
must survive: empty tables, several guilds, NULL values, JSONB payloads, very
long strings, far more than 1000 rows (multi-page pagination), conflicting
business keys, unresolvable dependencies and legacy non-UUID ids.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

from database.migration.export import ExportOptions, SupabaseExporter
from database.migration.model import IMPORT_ORDER

GUILD_A = "1000000000000000001"
GUILD_B = "1000000000000000002"
USER_A = "2000000000000000001"
USER_B = "2000000000000000002"

PROMPT_VERSION_ID = "11111111-1111-4111-8111-111111111111"
CONVERSATION_ID = "22222222-2222-4222-8222-222222222222"
CONVERSATION_ID_2 = "33333333-3333-4333-8333-333333333333"
MEMORY_ID = "44444444-4444-4444-8444-444444444444"
MEMORY_ID_2 = "55555555-5555-4555-8555-555555555555"
EMBEDDING_ID = "66666666-6666-4666-8666-666666666666"
SUMMARY_ID = "77777777-7777-4777-8777-777777777777"
ANALYSIS_ID = "88888888-8888-4888-8888-888888888888"
FEEDBACK_ID = "99999999-9999-4999-8999-999999999999"
TEMPLATE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TEMPLATE_ID_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

LONG_SUMMARY = (
    "Deze server begon als een kleine Minecraft SMP-community en groeide in "
    "enkele maanden uit tot een volwaardige hub met aparte kanalen voor "
    "moderatie, aankondigingen en community-evenementen. " * 40
)


def action_row(index: int, guild_id: str = GUILD_A) -> dict:
    return {
        "id": index,
        "guild_id": guild_id,
        "user_id": USER_A if index % 2 else None,
        "action_type": "create_channel" if index % 2 else "create_role",
        "data": {
            "type": "create_channel" if index % 2 else "create_role",
            "name": f"kanaal-{index}",
            "channel_id": str(900000000000000000 + index),
        },
        "created_at": f"2026-01-01T00:00:{index % 60:02d}+00:00",
    }


def base_rows() -> dict[str, list[dict]]:
    """A small but realistic dataset covering every migrated table."""

    return {
        "actions": [
            action_row(1),
            action_row(2),
            action_row(3, guild_id=GUILD_B),
        ],
        "prompt_versions": [
            {
                "id": PROMPT_VERSION_ID,
                "name": "server_plan",
                "version": "1",
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "system_prompt": "Je bent een Discord server planner.",
                "schema": {"type": "object", "required": ["actions"]},
                "active": True,
                "notes": None,
                "created_at": "2025-12-01T10:00:00+00:00",
                "deleted_at": None,
            }
        ],
        "conversations": [
            {
                "id": CONVERSATION_ID,
                "guild_id": GUILD_A,
                "user_id": USER_A,
                "username": "tester",
                "message": "maak een minecraft smp server",
                "response": json.dumps({"summary": "plan"}),
                "ai_plan": {
                    "summary": "Minecraft SMP",
                    "actions": [
                        {"type": "create_category", "name": "SMP"},
                        {"type": "create_channel", "name": "general"},
                    ],
                },
                "result": {"executed": 2, "failed": 0},
                "feedback": {"rating": 5},
                "prompt_version_id": PROMPT_VERSION_ID,
                "risk": "low",
                "selected_template": "minecraft-smp",
                "error": None,
                "created_at": "2026-02-01T12:00:00+00:00",
            },
            {
                "id": CONVERSATION_ID_2,
                "guild_id": GUILD_B,
                "user_id": None,
                "username": None,
                "message": "verwijder kanaal test",
                "response": None,
                "ai_plan": None,
                "result": None,
                "feedback": None,
                "prompt_version_id": None,
                "risk": None,
                "selected_template": None,
                "error": "timeout",
                "created_at": "2026-02-02T12:00:00+00:00",
            },
        ],
        "memories": [
            {
                "id": MEMORY_ID,
                "guild_id": GUILD_A,
                "user_id": None,
                "memory_key": "style",
                "memory_value": "compact",
                "memory_type": "preference",
                "confidence": 0.85,
                "source": "conversation",
                "created_at": "2026-02-01T12:05:00+00:00",
                "updated_at": "2026-02-01T12:05:00+00:00",
                "deleted_at": None,
            },
            {
                "id": MEMORY_ID_2,
                "guild_id": GUILD_B,
                "user_id": USER_B,
                "memory_key": "taal",
                "memory_value": "nederlands",
                "memory_type": "preference",
                "confidence": 0.5,
                "source": None,
                "created_at": "2026-02-02T12:05:00+00:00",
                "updated_at": "2026-02-02T12:05:00+00:00",
                "deleted_at": None,
            },
        ],
        "memory_embeddings": [
            {
                "id": EMBEDDING_ID,
                "memory_id": MEMORY_ID,
                "provider": "openai",
                "model": "text-embedding-3-small",
                "embedding": [0.1, 0.2, 0.3, -0.4],
                "created_at": "2026-02-01T12:10:00+00:00",
            }
        ],
        "conversation_summaries": [
            {
                "id": SUMMARY_ID,
                "guild_id": GUILD_A,
                "user_id": USER_A,
                "summary": LONG_SUMMARY,
                "goals": ["kanaalstructuur", "moderatie"],
                "preferences": ["compact", "nederlands"],
                "created_at": "2026-02-01T12:15:00+00:00",
                "updated_at": "2026-02-01T12:15:00+00:00",
                "deleted_at": None,
            }
        ],
        "server_analysis": [
            {
                "id": ANALYSIS_ID,
                "guild_id": GUILD_A,
                "health_score": 78,
                "issues": [
                    {
                        "severity": "medium",
                        "category": "structure",
                        "message": "geen categorie",
                        "recommendation": "voeg categorie toe",
                    }
                ],
                "recommendations": ["voeg categorie toe"],
                "created_at": "2026-02-01T12:20:00+00:00",
                "deleted_at": None,
            }
        ],
        "feedback": [
            {
                "id": FEEDBACK_ID,
                "guild_id": GUILD_A,
                "user_id": USER_A,
                "conversation_id": CONVERSATION_ID,
                "execution_id": None,
                "rating": 5,
                "comment": "werkt goed",
                "metadata": {"source": "button"},
                "created_at": "2026-02-01T12:25:00+00:00",
                "deleted_at": None,
            }
        ],
        "templates": [
            {
                "id": TEMPLATE_ID,
                "name": "minecraft-smp",
                "description": "Server voor een Minecraft SMP community",
                "category": "gaming",
                "version": "1",
                "tags": ["minecraft", "gaming"],
                "recommended_for": ["smp", " survival"],
                "member_min": 5,
                "member_max": 500,
                "actions": [
                    {"type": "create_category", "name": "SMP"},
                    {"type": "create_channel", "name": "algemeen"},
                ],
                "enabled": True,
                "created_at": "2025-11-01T09:00:00+00:00",
                "updated_at": "2025-11-01T09:00:00+00:00",
                "deleted_at": None,
            },
            {
                "id": TEMPLATE_ID_2,
                "name": "bedrijfs-hub",
                "description": "",
                "category": "professional",
                "version": "2",
                "tags": ["professional"],
                "recommended_for": [],
                "member_min": None,
                "member_max": None,
                "actions": [],
                "enabled": False,
                "created_at": "2025-11-02T09:00:00+00:00",
                "updated_at": "2025-11-02T09:00:00+00:00",
                "deleted_at": None,
            },
        ],
    }


def empty_rows() -> dict[str, list[dict]]:
    """Every table present, every table empty."""

    return {name: [] for name in IMPORT_ORDER}


def conflicting_rows() -> dict[str, list[dict]]:
    """Rows that violate the unique constraints of the target schema."""

    rows = empty_rows()
    rows["prompt_versions"] = [
        _prompt_version("dup-prompt", "1", PROMPT_VERSION_ID),
        _prompt_version(
            "dup-prompt", "1", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        ),
    ]
    rows["memories"] = [
        _memory(MEMORY_ID, GUILD_A, "style", "compact"),
        _memory(MEMORY_ID_2, GUILD_A, "style", "verbose"),
    ]
    return rows


def missing_dependency_rows() -> dict[str, list[dict]]:
    """An embedding whose memory is absent, plus a dangling soft reference."""

    rows = empty_rows()
    rows["memories"] = [_memory(MEMORY_ID, GUILD_A, "style", "compact")]
    rows["memory_embeddings"] = [
        {
            "id": EMBEDDING_ID,
            "memory_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "provider": "openai",
            "model": "text-embedding-3-small",
            "embedding": [0.5],
            "created_at": "2026-02-01T12:10:00+00:00",
        }
    ]
    rows["feedback"] = [
        {
            "id": FEEDBACK_ID,
            "guild_id": GUILD_A,
            "user_id": USER_A,
            "conversation_id": CONVERSATION_ID,  # conversation is not exported
            "execution_id": None,
            "rating": 4,
            "comment": "zwevende referentie",
            "metadata": {},
            "created_at": "2026-02-01T12:25:00+00:00",
            "deleted_at": None,
        }
    ]
    return rows


def legacy_int_id_rows() -> dict[str, list[dict]]:
    """Conversations with legacy integer ids (not storable as uuid)."""

    rows = empty_rows()
    rows["conversations"] = [
        {
            "id": 41,
            "guild_id": GUILD_A,
            "user_id": USER_A,
            "username": "legacy",
            "message": "oude conversatie",
            "response": None,
            "ai_plan": {"actions": []},
            "result": None,
            "feedback": None,
            "prompt_version_id": None,
            "risk": None,
            "selected_template": None,
            "error": None,
            "created_at": "2025-06-01T08:00:00+00:00",
        }
    ]
    rows["feedback"] = [
        {
            "id": FEEDBACK_ID,
            "guild_id": GUILD_A,
            "user_id": USER_A,
            "conversation_id": 41,  # references the legacy integer id
            "execution_id": None,
            "rating": 3,
            "comment": "legacy referentie",
            "metadata": {},
            "created_at": "2025-06-01T08:05:00+00:00",
            "deleted_at": None,
        }
    ]
    return rows


def large_rows(count: int = 2500) -> dict[str, list[dict]]:
    """More rows than one PostgREST page can return (default 1000)."""

    rows = empty_rows()
    rows["actions"] = [
        action_row(index, guild_id=GUILD_A if index % 2 else GUILD_B)
        for index in range(1, count + 1)
    ]
    rows["memories"] = [
        _memory(
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"memory-{index}")),
            GUILD_A if index % 2 else GUILD_B,
            f"key-{index}",
            f"value-{index}",
        )
        for index in range(count)
    ]
    return rows


def _prompt_version(name: str, version: str, identifier: str) -> dict:
    return {
        "id": identifier,
        "name": name,
        "version": version,
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "system_prompt": f"prompt {name} {version}",
        "schema": {},
        "active": False,
        "notes": None,
        "created_at": "2025-12-01T10:00:00+00:00",
        "deleted_at": None,
    }


def _memory(
    identifier: str,
    guild_id: str,
    key: str,
    value: str,
    user_id: str | None = None,
) -> dict:
    return {
        "id": identifier,
        "guild_id": guild_id,
        "user_id": user_id,
        "memory_key": key,
        "memory_value": value,
        "memory_type": "preference",
        "confidence": 0.75,
        "source": "conversation",
        "created_at": "2026-02-01T12:05:00+00:00",
        "updated_at": "2026-02-01T12:05:00+00:00",
        "deleted_at": None,
    }


# --------------------------------------------------------------------------
# Fake Supabase (PostgREST) client
# --------------------------------------------------------------------------


class FakeQuery:
    """Fluent stand-in for the PostgREST request builder."""

    def __init__(self, table: "FakeTable", count: str | None) -> None:
        self._table = table
        self._count = count
        self.orders: list[tuple[str, bool]] = []
        self.start: int | None = None
        self.end: int | None = None

    def order(self, column: str, desc: bool = False, **_kwargs) -> "FakeQuery":
        self.orders.append((column, desc))
        return self

    def limit(self, _size: int, **_kwargs) -> "FakeQuery":
        return self

    def range(self, start: int, end: int, **_kwargs) -> "FakeQuery":
        self.start = start
        self.end = end
        return self

    def execute(self) -> SimpleNamespace:
        return self._table.execute(self)


class FakeTable:
    """One table of fake Supabase data."""

    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self.rows = rows
        self.requests: list[FakeQuery] = []
        self.error: Exception | None = None
        self.missing_columns: set[str] = set()

    def select(self, *_columns: str, count: str | None = None, **_kwargs):
        return FakeQuery(self, count)

    def execute(self, query: FakeQuery) -> SimpleNamespace:
        self.requests.append(query)
        if self.error is not None:
            raise self.error

        rows = list(self.rows)
        for column, _desc in reversed(query.orders):
            if column in self.missing_columns:
                raise RuntimeError(
                    f"column {self.name}.{column} does not exist (PGRST204)"
                )
            rows.sort(
                key=lambda row: (row.get(column) is None, str(row.get(column)))
            )

        if query.start is not None and query.end is not None:
            rows = rows[query.start: query.end + 1]

        total = len(self.rows) if query._count == "exact" else None
        return SimpleNamespace(data=rows, count=total)


class FakeSupabaseClient:
    """Minimal Supabase SDK double: ``client.table(name).select(...).range()``."""

    def __init__(self, tables: dict[str, list[dict]] | None = None) -> None:
        self.tables: dict[str, FakeTable] = {}
        for name, rows in (tables or {}).items():
            self.tables[name] = FakeTable(name, list(rows))

    def table(self, name: str) -> FakeTable:
        if name not in self.tables:
            raise RuntimeError(
                f"relation \"public.{name}\" does not exist (PGRST205)"
            )
        return self.tables[name]

    def page_requests(self, name: str) -> list[FakeQuery]:
        table = self.tables.get(name)
        return list(table.requests) if table else []


# --------------------------------------------------------------------------
# Export helpers
# --------------------------------------------------------------------------


def make_export(
    directory: Path,
    rows: dict[str, list[dict]] | None = None,
    page_size: int = 250,
    client: FakeSupabaseClient | None = None,
    tables: Iterable[str] | None = None,
) -> tuple[Path, FakeSupabaseClient]:
    """Run the real exporter against fake Supabase data."""

    data = rows if rows is not None else base_rows()
    fake_client = client or FakeSupabaseClient(data)
    options = ExportOptions(
        output_dir=Path(directory),
        page_size=page_size,
        tables=tuple(tables) if tables else IMPORT_ORDER,
    )
    exporter = SupabaseExporter(fake_client, options)
    exporter.export({"backend": "supabase", "url_host": "example.supabase.co"})
    return Path(directory), fake_client
