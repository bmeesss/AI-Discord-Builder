"""Declarative datamodel for the Supabase → PostgreSQL migration tooling.

The definitions in this module are transcribed from the SQL that this
repository actually ships:

* source: ``database/migrations/001_intelligence_tables.sql`` (Supabase) plus
  the ``actions``/``conversations`` tables that Supabase projects created
  themselves (the repository only ever ``alter``ed ``conversations``);
* target: ``database/postgres/migrations/001_core_tables.sql`` and
  ``database/postgres/migrations/002_intelligence_tables.sql``.

Nothing here creates tables: the migration tool only *reads* the source and
*inserts* into the target.  Every SQL statement used by the importer is built
from these specs with ``$n`` placeholders, never with interpolated values.

Conventions
-----------
``kind`` values map to PostgreSQL types:

    uuid, text, jsonb, timestamptz, integer, bigint, numeric, boolean
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

# --------------------------------------------------------------------------
# Export format
# --------------------------------------------------------------------------

FORMAT_VERSION = "1.0"
MANIFEST_FILENAME = "manifest.json"
EXPORT_DIR_PREFIX = "supabase-export"
DEFAULT_EXPORT_ROOT = "backups"
DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 1000  # PostgREST hard limit for a single range() request.
DEFAULT_BATCH_SIZE = 500

# Deterministic namespace for regenerated identifiers: uuid5 keeps a legacy id
# that cannot be stored (e.g. a non-UUID conversation id) stable across runs,
# which is what makes a repeated import of the same export idempotent.
ID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://github.com/bmeesss/AI-Discord-Builder/migration",
)


@dataclass(frozen=True)
class Column:
    """One column of a migrated table."""

    name: str
    kind: str
    nullable: bool = True
    primary_key: bool = False
    default: str | None = None
    check: str | None = None


@dataclass(frozen=True)
class ForeignKey:
    """A foreign key (``soft`` ones have no FK constraint in the schema)."""

    column: str
    ref_table: str
    ref_column: str = "id"
    soft: bool = False
    on_delete: str | None = None

    def describe(self) -> str:
        kind = "soft reference" if self.soft else "foreign key"
        extra = f" on delete {self.on_delete}" if self.on_delete else ""
        return f"{self.column} -> {self.ref_table}.{self.ref_column} ({kind}{extra})"


@dataclass(frozen=True)
class UniqueConstraint:
    """A unique constraint or unique index (may be partial)."""

    name: str
    columns: tuple[str, ...]
    partial: str | None = None
    nulls_not_distinct: bool = False


@dataclass(frozen=True)
class TableSpec:
    """Everything the migration tool needs to know about one table."""

    name: str
    columns: tuple[Column, ...]
    primary_key: str
    conflict_key: tuple[str, ...]
    conflict_reason: str
    foreign_keys: tuple[ForeignKey, ...] = ()
    uniques: tuple[UniqueConstraint, ...] = ()
    id_policy: str = "preserve"  # or "regenerate"
    id_policy_reason: str = ""
    required: tuple[str, ...] = ()
    order_by: tuple[str, ...] = ("created_at", "id")
    notes: str = ""

    # -- column helpers ----------------------------------------------------

    def column(self, name: str) -> Column:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(f"table {self.name!r} has no column {name!r}")

    def has(self, name: str) -> bool:
        return any(column.name == name for column in self.columns)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    @property
    def insert_columns(self) -> tuple[Column, ...]:
        """Columns written by the importer (regenerated PKs are excluded)."""

        return tuple(c for c in self.columns if not self._is_regenerated_pk(c))

    @property
    def jsonb_columns(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.kind == "jsonb")

    @property
    def timestamp_columns(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.kind == "timestamptz")

    @property
    def uuid_columns(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.kind == "uuid")

    def _is_regenerated_pk(self, column: Column) -> bool:
        return self.id_policy == "regenerate" and column.name == self.primary_key

    # -- relation helpers --------------------------------------------------

    @property
    def dependencies(self) -> tuple[str, ...]:
        """Tables that must be imported before this one (hard FKs only)."""

        return tuple(
            sorted({fk.ref_table for fk in self.foreign_keys if not fk.soft})
        )

    @property
    def references(self) -> tuple[ForeignKey, ...]:
        return self.foreign_keys

    def foreign_key_for(self, column: str) -> ForeignKey | None:
        for fk in self.foreign_keys:
            if fk.column == column:
                return fk
        return None


# --------------------------------------------------------------------------
# The real schemas
# --------------------------------------------------------------------------

ACTIONS = TableSpec(
    name="actions",
    columns=(
        Column("id", "bigint", nullable=False, primary_key=True,
               default="generated always as identity"),
        Column("guild_id", "text", nullable=False),
        Column("user_id", "text"),
        Column("action_type", "text"),
        Column("data", "jsonb", nullable=False, default="'{}'::jsonb"),
        Column("created_at", "timestamptz", nullable=False, default="now()"),
    ),
    primary_key="id",
    conflict_key=(),
    conflict_reason=(
        "No primary key is migrated: the target column is "
        "'bigint generated always as identity' and the legacy Supabase id "
        "type is unknown, so PostgreSQL generates a new id. Rows are "
        "de-duplicated on (guild_id, user_id, action_type, data, created_at) "
        "to keep repeated imports idempotent."
    ),
    id_policy="regenerate",
    id_policy_reason=(
        "database/postgres/migrations/001_core_tables.sql defines "
        "actions.id as 'bigint generated always as identity'. Inserting an "
        "explicit value requires OVERRIDING SYSTEM VALUE and would leave the "
        "identity sequence behind the migrated rows (future inserts could "
        "collide). The legacy Supabase actions.id type is not defined by any "
        "SQL in this repository, so it cannot be assumed compatible. All "
        "content (guild_id, user_id, action_type, data, created_at) is "
        "preserved and rows are inserted in chronological order so the "
        "generated ids keep history ordering intact."
    ),
    required=("guild_id", "data", "created_at"),
    order_by=("created_at", "id"),
    notes="Rollback history. Nothing references actions.id.",
)

PROMPT_VERSIONS = TableSpec(
    name="prompt_versions",
    columns=(
        Column("id", "uuid", nullable=False, primary_key=True,
               default="gen_random_uuid()"),
        Column("name", "text", nullable=False),
        Column("version", "text", nullable=False),
        Column("provider", "text"),
        Column("model", "text"),
        Column("system_prompt", "text", nullable=False),
        Column("schema", "jsonb", nullable=False, default="'{}'::jsonb"),
        Column("active", "boolean", nullable=False, default="false"),
        Column("notes", "text"),
        Column("created_at", "timestamptz", nullable=False, default="now()"),
        Column("deleted_at", "timestamptz"),
    ),
    primary_key="id",
    conflict_key=("name", "version"),
    conflict_reason=(
        "unique (name, version) is the business key in both schemas; the same "
        "prompt/version already present in the target must not be duplicated."
    ),
    uniques=(
        UniqueConstraint("prompt_versions_name_version_key",
                         ("name", "version")),
    ),
    required=("name", "version", "system_prompt", "created_at"),
    order_by=("created_at", "id"),
)

CONVERSATIONS = TableSpec(
    name="conversations",
    columns=(
        Column("id", "uuid", nullable=False, primary_key=True,
               default="gen_random_uuid()"),
        Column("guild_id", "text", nullable=False),
        Column("user_id", "text"),
        Column("username", "text"),
        Column("message", "text"),
        Column("response", "text"),
        Column("ai_plan", "jsonb"),
        Column("result", "jsonb"),
        Column("feedback", "jsonb"),
        Column("prompt_version_id", "uuid"),
        Column("risk", "text"),
        Column("selected_template", "text"),
        Column("error", "text"),
        Column("created_at", "timestamptz", nullable=False, default="now()"),
    ),
    primary_key="id",
    conflict_key=("id",),
    conflict_reason=(
        "Append-only log rows: the same conversation id is already the same "
        "row, so a repeated import skips it."
    ),
    foreign_keys=(
        ForeignKey("prompt_version_id", "prompt_versions", "id"),
    ),
    required=("guild_id", "created_at"),
    order_by=("created_at", "id"),
    notes=(
        "The Supabase migration only ALTERs this table (adds ai_plan, result, "
        "feedback, prompt_version_id, risk, selected_template, error); the "
        "table itself is created in the Supabase project, so the legacy id "
        "type is verified per export."
    ),
)

MEMORIES = TableSpec(
    name="memories",
    columns=(
        Column("id", "uuid", nullable=False, primary_key=True,
               default="gen_random_uuid()"),
        Column("guild_id", "text", nullable=False),
        Column("user_id", "text"),
        Column("memory_key", "text", nullable=False),
        Column("memory_value", "text", nullable=False),
        Column("memory_type", "text", nullable=False, default="'preference'"),
        Column("confidence", "numeric", nullable=False, default="0.500",
               check="confidence >= 0 and confidence <= 1"),
        Column("source", "text"),
        Column("created_at", "timestamptz", nullable=False, default="now()"),
        Column("updated_at", "timestamptz", nullable=False, default="now()"),
        Column("deleted_at", "timestamptz"),
    ),
    primary_key="id",
    conflict_key=("id",),
    conflict_reason=(
        "Stable identity: the same memory id is already the same row. The "
        "partial unique index on (guild_id, user_id, memory_type, memory_key) "
        "is checked explicitly before inserting — a conflicting active key is "
        "reported and skipped, never silently dropped."
    ),
    uniques=(
        UniqueConstraint(
            "memories_unique_active_idx",
            ("guild_id", "user_id", "memory_type", "memory_key"),
            partial="deleted_at is null",
            nulls_not_distinct=True,
        ),
    ),
    required=("guild_id", "memory_key", "memory_value", "created_at"),
    order_by=("created_at", "id"),
)

MEMORY_EMBEDDINGS = TableSpec(
    name="memory_embeddings",
    columns=(
        Column("id", "uuid", nullable=False, primary_key=True,
               default="gen_random_uuid()"),
        Column("memory_id", "uuid", nullable=False),
        Column("provider", "text"),
        Column("model", "text"),
        Column("embedding", "jsonb"),
        Column("created_at", "timestamptz", nullable=False, default="now()"),
    ),
    primary_key="id",
    conflict_key=("id",),
    conflict_reason=(
        "Stable identity: the same embedding id is already the same row."
    ),
    foreign_keys=(
        ForeignKey("memory_id", "memories", "id", on_delete="cascade"),
    ),
    required=("memory_id", "created_at"),
    order_by=("created_at", "id"),
)

CONVERSATION_SUMMARIES = TableSpec(
    name="conversation_summaries",
    columns=(
        Column("id", "uuid", nullable=False, primary_key=True,
               default="gen_random_uuid()"),
        Column("guild_id", "text", nullable=False),
        Column("user_id", "text"),
        Column("summary", "text", nullable=False),
        Column("goals", "jsonb", nullable=False, default="'[]'::jsonb"),
        Column("preferences", "jsonb", nullable=False, default="'[]'::jsonb"),
        Column("created_at", "timestamptz", nullable=False, default="now()"),
        Column("updated_at", "timestamptz", nullable=False, default="now()"),
        Column("deleted_at", "timestamptz"),
    ),
    primary_key="id",
    conflict_key=("id",),
    conflict_reason=(
        "Stable identity: the same summary id is already the same row."
    ),
    required=("guild_id", "summary", "created_at"),
    order_by=("created_at", "id"),
)

SERVER_ANALYSIS = TableSpec(
    name="server_analysis",
    columns=(
        Column("id", "uuid", nullable=False, primary_key=True,
               default="gen_random_uuid()"),
        Column("guild_id", "text", nullable=False),
        Column("health_score", "integer", nullable=False,
               check="health_score >= 0 and health_score <= 100"),
        Column("issues", "jsonb", nullable=False, default="'[]'::jsonb"),
        Column("recommendations", "jsonb", nullable=False,
               default="'[]'::jsonb"),
        Column("created_at", "timestamptz", nullable=False, default="now()"),
        Column("deleted_at", "timestamptz"),
    ),
    primary_key="id",
    conflict_key=("id",),
    conflict_reason=(
        "Stable identity: the same analysis id is already the same row."
    ),
    required=("guild_id", "health_score", "created_at"),
    order_by=("created_at", "id"),
)

FEEDBACK = TableSpec(
    name="feedback",
    columns=(
        Column("id", "uuid", nullable=False, primary_key=True,
               default="gen_random_uuid()"),
        Column("guild_id", "text", nullable=False),
        Column("user_id", "text"),
        Column("conversation_id", "uuid"),
        Column("execution_id", "uuid"),
        Column("rating", "integer",
               check="rating is null or (rating >= 1 and rating <= 5)"),
        Column("comment", "text"),
        Column("metadata", "jsonb", nullable=False, default="'{}'::jsonb"),
        Column("created_at", "timestamptz", nullable=False, default="now()"),
        Column("deleted_at", "timestamptz"),
    ),
    primary_key="id",
    conflict_key=("id",),
    conflict_reason=(
        "Stable identity: the same feedback id is already the same row."
    ),
    foreign_keys=(
        # No FK constraint exists in either schema, but the column does point
        # at conversations, so it is treated as a (soft) dependency.
        ForeignKey("conversation_id", "conversations", "id", soft=True),
    ),
    required=("guild_id", "created_at"),
    order_by=("created_at", "id"),
    notes="conversation_id/execution_id have no FK constraint in the schema.",
)

TEMPLATES = TableSpec(
    name="templates",
    columns=(
        Column("id", "uuid", nullable=False, primary_key=True,
               default="gen_random_uuid()"),
        Column("name", "text", nullable=False),
        Column("description", "text", nullable=False, default="''"),
        Column("category", "text", nullable=False, default="'general'"),
        Column("version", "text", nullable=False, default="'1'"),
        Column("tags", "jsonb", nullable=False, default="'[]'::jsonb"),
        Column("recommended_for", "jsonb", nullable=False,
               default="'[]'::jsonb"),
        Column("member_min", "integer"),
        Column("member_max", "integer"),
        Column("actions", "jsonb", nullable=False, default="'[]'::jsonb"),
        Column("enabled", "boolean", nullable=False, default="true"),
        Column("created_at", "timestamptz", nullable=False, default="now()"),
        Column("updated_at", "timestamptz", nullable=False, default="now()"),
        Column("deleted_at", "timestamptz"),
    ),
    primary_key="id",
    conflict_key=("id",),
    conflict_reason=(
        "Stable identity: the same template id is already the same row."
    ),
    required=("name", "created_at"),
    order_by=("created_at", "id"),
)


TABLES: dict[str, TableSpec] = {
    spec.name: spec
    for spec in (
        ACTIONS,
        PROMPT_VERSIONS,
        CONVERSATIONS,
        MEMORIES,
        MEMORY_EMBEDDINGS,
        CONVERSATION_SUMMARIES,
        SERVER_ANALYSIS,
        FEEDBACK,
        TEMPLATES,
    )
}

# Import order follows the real foreign keys:
#   prompt_versions  -> conversations     (conversations.prompt_version_id)
#   memories         -> memory_embeddings (memory_embeddings.memory_id)
#   conversations    -> feedback          (soft reference, ordering only)
# ``tests/test_migration_model.py`` asserts that this order is a valid
# topological order of every declared foreign key.
IMPORT_ORDER: tuple[str, ...] = (
    "actions",
    "prompt_versions",
    "conversations",
    "memories",
    "memory_embeddings",
    "conversation_summaries",
    "server_analysis",
    "feedback",
    "templates",
)

# Tables whose primary key is not migrated and therefore need content-based
# de-duplication to stay idempotent.
CONTENT_DEDUPE_TABLES = frozenset({"actions"})

# Columns used to recognise an already-imported row for those tables.
CONTENT_DEDUPE_COLUMNS: dict[str, tuple[str, ...]] = {
    "actions": ("guild_id", "user_id", "action_type", "data", "created_at"),
}


def topological_order(tables: dict[str, TableSpec] | None = None) -> list[str]:
    """Return a deterministic topological order for ``tables``.

    Ties are broken by declaration order.  Used by the tests to prove that
    ``IMPORT_ORDER`` satisfies every real foreign key.
    """

    specs = dict(tables if tables is not None else TABLES)
    order: list[str] = []
    remaining = set(specs)

    while remaining:
        ready = [
            name
            for name in remaining
            if all(
                dependency not in remaining
                for dependency in specs[name].dependencies
            )
        ]
        if not ready:  # pragma: no cover - guarded by tests
            raise ValueError(
                f"Cyclic foreign keys between tables: {sorted(remaining)}"
            )
        # Deterministic: ties follow the documented import order.
        ready.sort(
            key=lambda name: (
                IMPORT_ORDER.index(name) if name in IMPORT_ORDER
                else len(IMPORT_ORDER)
            )
        )
        order.extend(ready)
        remaining.difference_update(ready)

    return order


# --------------------------------------------------------------------------
# Value normalisation (shared by the export validator and the importer)
# --------------------------------------------------------------------------


def deterministic_uuid(table: str, value: Any) -> uuid.UUID:
    """Stable uuid5 replacement for an id that cannot be stored as-is.

    Used when a source id is not a UUID (a legacy integer ``conversations.id``
    for example).  The result is stable across runs, which is what keeps a
    repeated import idempotent and lets references point at the new id.
    """

    material = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, default=str)
    )
    return uuid.uuid5(ID_NAMESPACE, f"{table}:{material}")


def parse_timestamp(value: Any) -> tuple[Any, str | None]:
    """Parse an ISO-8601 timestamp into a tz-aware datetime.

    Returns ``(value, error)``; naive timestamps are interpreted as UTC
    (PostgreSQL stores them as ``timestamptz`` anyway).
    """

    if value is None:
        return None, None
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return _truncate_microseconds(parsed), None

    if not isinstance(value, str) or not value.strip():
        return None, f"invalid timestamp {value!r}"

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, f"invalid timestamp {value!r}"

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _truncate_microseconds(parsed), None


def _truncate_microseconds(value: datetime) -> datetime:
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def parse_uuid(value: Any) -> tuple[Any, str | None]:
    """Parse a UUID value; returns ``(UUID | None, error)``."""

    if value is None:
        return None, None
    if isinstance(value, uuid.UUID):
        return value, None
    if isinstance(value, int):  # legacy bigint ids are remapped by the caller
        return None, f"non-uuid id {value!r}"
    if not isinstance(value, str) or not value.strip():
        return None, f"invalid uuid {value!r}"
    try:
        return uuid.UUID(value.strip()), None
    except (ValueError, AttributeError, TypeError):
        return None, f"invalid uuid {value!r}"


def parse_jsonb(value: Any) -> tuple[Any, str | None]:
    """Normalise a JSONB value to a Python object (or ``None``)."""

    if value is None:
        return None, None
    if isinstance(value, (dict, list)):
        return value, None
    if isinstance(value, str):
        try:
            return json.loads(value), None
        except ValueError:
            return None, "invalid json value"
    if isinstance(value, (int, float, bool)):
        # jsonb scalars are legal; keep them as-is.
        return value, None
    return None, f"unsupported jsonb value of type {type(value).__name__}"


def parse_numeric(value: Any) -> tuple[Any, str | None]:
    """Parse ``numeric(4, 3)`` (memory confidence)."""

    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, f"invalid numeric {value!r}"
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None, f"invalid numeric {value!r}"
    return decimal.quantize(Decimal("0.001")), None


def parse_integer(value: Any) -> tuple[Any, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, f"invalid integer {value!r}"
    if isinstance(value, int):
        return value, None
    if isinstance(value, float) and value.is_integer():
        return int(value), None
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip()), None
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value), None
    return None, f"invalid integer {value!r}"


def parse_boolean(value: Any) -> tuple[Any, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return value, None
    if isinstance(value, str) and value.strip().lower() in {
        "true",
        "false",
        "t",
        "f",
        "yes",
        "no",
    }:
        return value.strip().lower() in {"true", "t", "yes"}, None
    return None, f"invalid boolean {value!r}"


def parse_text(value: Any) -> tuple[Any, str | None]:
    if value is None:
        return None, None
    if isinstance(value, str):
        return value, None
    if isinstance(value, bool):
        return None, f"invalid text {value!r}"
    if isinstance(value, (int, float, Decimal)):
        # Legacy schemas sometimes stored ids as numbers; text columns in the
        # target are text, so the value is preserved verbatim.
        return str(value), None
    return None, f"unsupported text value of type {type(value).__name__}"


_PARSERS = {
    "uuid": parse_uuid,
    "text": parse_text,
    "jsonb": parse_jsonb,
    "timestamptz": parse_timestamp,
    "integer": parse_integer,
    "bigint": parse_integer,
    "numeric": parse_numeric,
    "boolean": parse_boolean,
}


def normalize_value(column: Column, value: Any) -> tuple[Any, str | None]:
    """Coerce ``value`` to the type the target column expects."""

    parser = _PARSERS.get(column.kind)
    if parser is None:  # pragma: no cover - guards future column kinds
        return value, f"unsupported column kind {column.kind!r}"
    return parser(value)


def check_constraints(spec: TableSpec, values: dict[str, Any]) -> list[str]:
    """Apply the CHECK constraints that are declared in the SQL schemas."""

    errors: list[str] = []
    if spec.name == "memories":
        confidence = values.get("confidence")
        if confidence is not None and not (
            Decimal("0") <= confidence <= Decimal("1")
        ):
            errors.append(
                f"confidence {confidence} violates "
                "memories_confidence_range (0..1)"
            )
    if spec.name == "server_analysis":
        score = values.get("health_score")
        if score is not None and not 0 <= score <= 100:
            errors.append(
                f"health_score {score} violates "
                "server_analysis_score_range (0..100)"
            )
    if spec.name == "feedback":
        rating = values.get("rating")
        if rating is not None and not 1 <= rating <= 5:
            errors.append(
                f"rating {rating} violates feedback_rating_range (1..5)"
            )
    return errors


def normalize_row(
    spec: TableSpec,
    row: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Validate and coerce one exported row.

    Returns ``(values, errors)`` where ``values`` only contains columns the
    importer writes (regenerated primary keys are absent).
    """

    if not isinstance(row, dict):
        return {}, [f"row is not a JSON object (got {type(row).__name__})"]

    errors: list[str] = []
    values: dict[str, Any] = {}

    for column in spec.insert_columns:
        if column.name == spec.primary_key:
            # The primary key is assigned by the importer (preserved UUIDs or
            # a deterministic uuid5 replacement); it is not validated here.
            continue
        if spec.foreign_key_for(column.name) is not None:
            # References are resolved (and remapped) by the importer: a
            # legacy integer reference is valid input until resolution fails.
            raw_reference = row.get(column.name)
            values[column.name] = (
                None if raw_reference in (None, "") else raw_reference
            )
            continue
        raw = row.get(column.name)
        value, error = normalize_value(column, raw)
        if error:
            errors.append(f"{column.name}: {error}")
            continue
        if value is None and column.name in spec.required:
            errors.append(f"{column.name}: missing required value")
            continue
        values[column.name] = value

    for name in spec.required:
        if name == spec.primary_key and spec.id_policy == "regenerate":
            continue  # PostgreSQL generates this value.
        if values.get(name) is not None:
            continue
        if any(error.startswith(f"{name}:") for error in errors):
            continue
        errors.append(f"{name}: missing required value")

    errors.extend(check_constraints(spec, values))
    return values, errors


def row_fingerprint(spec: TableSpec, values: dict[str, Any]) -> tuple:
    """Content fingerprint used to de-duplicate tables without a stable id."""

    columns = CONTENT_DEDUPE_COLUMNS.get(spec.name, ())
    parts: list[Any] = []
    for name in columns:
        value = values.get(name)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, sort_keys=True, default=str)
        parts.append(value)
    return tuple(parts)


# --------------------------------------------------------------------------
# SQL builders — every statement is fully parameterized
# --------------------------------------------------------------------------


def insert_sql(spec: TableSpec) -> str:
    """Build the (idempotent) INSERT statement for one table.

    Values are always bound with ``$n`` placeholders; ``jsonb`` columns are
    cast explicitly because asyncpg cannot infer their type from a string.
    """

    columns = spec.insert_columns
    placeholders = []
    for index, column in enumerate(columns, start=1):
        cast = "::jsonb" if column.kind == "jsonb" else ""
        placeholders.append(f"${index}{cast}")

    statement = (
        f"insert into {spec.name} ({', '.join(c.name for c in columns)}) "
        f"values ({', '.join(placeholders)})"
    )
    if spec.conflict_key:
        # ON CONFLICT DO NOTHING is only used where the conflict key is the
        # real identity of the row; see TableSpec.conflict_reason.
        statement += (
            f" on conflict ({', '.join(spec.conflict_key)}) do nothing"
        )
    return statement


def select_existing_ids_sql(spec: TableSpec) -> str:
    """Return the ids (uuid PK) of this table that already exist."""

    if spec.primary_key != "id" or spec.conflict_key != ("id",):
        raise ValueError(f"{spec.name}: no uuid primary key to check")
    return f"select id from {spec.name} where id = any($1::uuid[])"


def select_existing_prompt_versions_sql() -> str:
    return (
        "select name, version from prompt_versions "
        "where name = any($1::text[])"
    )


def select_active_memory_keys_sql() -> str:
    return (
        "select guild_id, user_id, memory_type, memory_key from memories "
        "where deleted_at is null and guild_id = any($1::text[])"
    )


def select_action_fingerprints_sql() -> str:
    return (
        "select guild_id, user_id, action_type, data, created_at from actions "
        "where guild_id = any($1::text[]) "
        "and created_at >= $2 and created_at <= $3"
    )


def select_count_sql(spec: TableSpec) -> str:
    return f"select count(*) as total from {spec.name}"


def select_rows_by_ids_sql(spec: TableSpec) -> str:
    return f"select id from {spec.name} where id = any($1::uuid[])"


def select_orphan_sql(spec: TableSpec, fk: ForeignKey) -> str:
    """Count rows whose foreign key points at a missing parent row."""

    return (
        f"select count(*) as total from {spec.name} child "
        f"where child.{fk.column} is not null "
        f"and not exists ("
        f"select 1 from {fk.ref_table} parent "
        f"where parent.{fk.ref_column} = child.{fk.column})"
    )


def select_invalid_jsonb_sql(spec: TableSpec, column: str) -> str:
    """Rows where a jsonb column is NULL (the schema declares it NOT NULL)."""

    return f"select count(*) as total from {spec.name} where {column} is null"


def select_null_timestamps_sql(spec: TableSpec, column: str) -> str:
    return f"select count(*) as total from {spec.name} where {column} is null"


def select_guild_counts_sql(spec: TableSpec) -> str:
    return (
        f"select guild_id, count(*) as total from {spec.name} "
        f"group by guild_id"
    )


# Statements the importer is allowed to execute.  Anything outside this set is
# a programming error; the tests assert that no destructive SQL exists.
DESTRUCTIVE_SQL_KEYWORDS = ("drop ", "truncate ", "delete from", "alter ", "update ")


def assert_non_destructive(sql: str) -> None:
    """Raise ``ValueError`` when ``sql`` contains a destructive statement."""

    lowered = " ".join(sql.lower().split())
    for keyword in DESTRUCTIVE_SQL_KEYWORDS:
        if keyword in lowered:
            raise ValueError(
                f"refusing to run destructive SQL ({keyword.strip()!r}): {sql}"
            )
