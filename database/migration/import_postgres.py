"""PostgreSQL import for a Supabase export (``import-postgres``).

Rules this module enforces:

* ``DATABASE_BACKEND=postgres`` is required (checked by the CLI);
* the target database must be reachable and fully migrated *before* anything
  is written — no pending migrations, no schema mismatch;
* every statement is parameterized (``$n``); nothing is ever string-formatted
  into SQL;
* no destructive SQL: no ``drop``, ``truncate``, ``delete``, ``update`` or
  ``alter`` — the import is purely additive;
* work is done in batches, each batch in its own transaction, so a failed
  batch rolls back on its own while earlier batches stay committed;
* re-running the same export is safe: rows that already exist are skipped,
  which makes the whole import idempotent;
* ``--dry-run`` performs every check (including "does this row already
  exist?") but writes nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import asyncpg

from database.errors import MigrationToolError
from database.migration.manifest import load_manifest
from database.migration.model import (
    CONTENT_DEDUPE_COLUMNS,
    Column,
    deterministic_uuid,
    DEFAULT_BATCH_SIZE,
    IMPORT_ORDER,
    TABLES,
    TableSpec,
    insert_sql,
    normalize_row,
    parse_uuid,
    row_fingerprint,
    select_action_fingerprints_sql,
    select_active_memory_keys_sql,
    select_count_sql,
    select_existing_prompt_versions_sql,
    select_orphan_sql,
    select_rows_by_ids_sql,
)
from database.migration.secrets import ScanResult
from database.migration.validate import iter_rows
from database.postgres.migrator import Migrator

logger = logging.getLogger("ai_discord_builder.database.migration.import")

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (0.2, 0.6, 1.5)
MAX_CONSECUTIVE_BATCH_FAILURES = 3
MAX_REPORTED_EXAMPLES = 5

# SQLSTATEs that are worth retrying (serialization failures, deadlocks,
# connection loss).  Data errors (23xxx) are deterministic: never retried.
RETRYABLE_SQLSTATES = frozenset(
    {
        "40001",  # serialization_failure
        "40P01",  # deadlock_detected
        "55P03",  # lock_not_available
        "08000",  # connection_exception
        "08003",  # connection_does_not_exist
        "08006",  # connection_failure
        "08001",  # sqlclient_unable_to_establish_sqlconnection
        "57P01",  # admin_shutdown
        "57P02",  # crash_shutdown
        "57P03",  # cannot_connect_now
        "53300",  # too_many_connections
    }
)

# information_schema type names that are acceptable for each column kind.
ACCEPTABLE_TYPES: dict[str, tuple[str, ...]] = {
    "uuid": ("uuid",),
    "text": ("text", "character varying", "varchar", "character"),
    "jsonb": ("jsonb",),
    "timestamptz": ("timestamp with time zone",),
    "integer": ("integer", "smallint", "bigint"),
    "bigint": ("bigint", "integer", "smallint"),
    "numeric": ("numeric", "decimal"),
    "boolean": ("boolean",),
}

SCHEMA_COLUMNS_SQL = """
select table_name, column_name, data_type, is_nullable
from information_schema.columns
where table_schema = any(current_schemas(false))
  and table_name = any($1::text[])
"""


def _noop(message: str) -> None:
    return None


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


@dataclass
class TableImportStats:
    """Per-table outcome of an import (or dry-run)."""

    table: str
    source_rows: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    skipped_conflict: int = 0
    invalid_rows: int = 0
    dependency_problems: int = 0
    soft_dependency_warnings: int = 0
    id_remapped: int = 0
    errors: int = 0
    batches: int = 0
    failed_batches: int = 0
    target_total: int | None = None
    examples: list[str] = field(default_factory=list)

    @property
    def skipped(self) -> int:
        return self.skipped_existing + self.skipped_conflict

    def note(self, message: str) -> None:
        if len(self.examples) < MAX_REPORTED_EXAMPLES:
            self.examples.append(message)


@dataclass
class VerificationCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class VerificationReport:
    checks: list[VerificationCheck] = field(default_factory=list)
    target_counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


@dataclass
class ImportReport:
    export_path: Path
    dry_run: bool = False
    aborted: bool = False
    tables: dict[str, TableImportStats] = field(default_factory=dict)
    verification: VerificationReport | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    secret_scan: ScanResult = field(default_factory=ScanResult)
    started_at: str = ""
    finished_at: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors and all(
            stats.errors == 0 for stats in self.tables.values()
        )

    @property
    def totals(self) -> dict[str, int]:
        return {
            "source_rows": sum(s.source_rows for s in self.tables.values()),
            "inserted": sum(s.inserted for s in self.tables.values()),
            "skipped": sum(s.skipped for s in self.tables.values()),
            "invalid_rows": sum(s.invalid_rows for s in self.tables.values()),
            "dependency_problems": sum(
                s.dependency_problems for s in self.tables.values()
            ),
            "errors": sum(s.errors for s in self.tables.values()),
        }


@dataclass
class ImportOptions:
    batch_size: int = DEFAULT_BATCH_SIZE
    dry_run: bool = False
    assume_yes: bool = False
    verify: bool = True
    progress: Callable[[str], None] = _noop
    confirm: Callable[[str], bool] | None = None
    secret_values: Iterable[str] | None = None


# --------------------------------------------------------------------------
# Deterministic id handling
# --------------------------------------------------------------------------


class IdMapper:
    """Maps source ids to the ids that are actually stored.

    UUID primary keys are preserved as-is.  Anything else (a legacy integer
    conversation id, or a missing id) is replaced by a deterministic
    ``uuid5`` so that a repeated import of the same export always produces the
    same identifier — that is what keeps the import idempotent while foreign
    keys keep pointing at the right parent row.
    """

    def __init__(self) -> None:
        self._map: dict[str, dict[str, uuid.UUID]] = {}
        self._remapped: dict[str, int] = {}

    def register(self, table: str, raw: Any, mapped: uuid.UUID) -> None:
        self._map.setdefault(table, {})[_key(raw)] = mapped

    def lookup(self, table: str, raw: Any) -> uuid.UUID | None:
        return self._map.get(table, {}).get(_key(raw))

    def resolve(self, table: str, raw: Any) -> uuid.UUID | None:
        """Resolve a *reference* to ``table`` (not a row of ``table``)."""

        known = self.lookup(table, raw)
        if known is not None:
            return known
        parsed, error = parse_uuid(raw)
        if error or parsed is None:
            return None
        return parsed

    def map_primary(
        self,
        table: str,
        raw: Any,
        fallback: Any = None,
    ) -> tuple[uuid.UUID, bool]:
        """Return ``(id, remapped)`` for a source row; remembers the mapping."""

        known = self.lookup(table, raw)
        if known is not None:
            return known, False

        parsed, error = parse_uuid(raw)
        if parsed is not None and error is None:
            self.register(table, raw, parsed)
            return parsed, False

        generated = deterministic_uuid(table, raw if raw is not None else fallback)
        self.register(table, raw, generated)
        self._remapped[table] = self._remapped.get(table, 0) + 1
        return generated, True

    @property
    def remapped_counts(self) -> dict[str, int]:
        return dict(self._remapped)


def _key(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


# --------------------------------------------------------------------------
# Importer
# --------------------------------------------------------------------------


class PostgresImporter:
    """Imports an export directory into PostgreSQL."""

    def __init__(
        self,
        pool: Any,
        export_path: str | Path,
        options: ImportOptions | None = None,
    ) -> None:
        self._pool = pool
        self._path = Path(export_path)
        self._options = options or ImportOptions()
        self._progress = self._options.progress or _noop
        self._ids = IdMapper()
        self._report = ImportReport(
            export_path=self._path, dry_run=self._options.dry_run
        )
        self._batch_size = max(1, int(self._options.batch_size))
        self._manifest: dict[str, Any] = {}
        # Ids this run has written (or will write).  Needed by the dry run:
        # parents are inserted by earlier batches, so a reference to a row
        # from the same export is satisfied even though nothing was written.
        self._available: dict[str, set[uuid.UUID]] = {}

    # -- public API --------------------------------------------------------

    async def run(self) -> ImportReport:
        """Run preflight, (optionally) confirm, import and verify."""

        self._report.started_at = _now_iso()

        if not self._path.exists():
            raise MigrationToolError(
                f"Export path does not exist: {self._path}"
            )
        if not self._path.is_dir():
            raise MigrationToolError(
                f"Export path is not a directory: {self._path}"
            )

        self._manifest = load_manifest(self._path)
        self._check_manifest_secrets()

        await self._pool.ping()

        real_pool = await self._pool.pool()
        async with real_pool.acquire() as conn:
            await self._preflight(conn)

        if not self._options.dry_run and not self._options.assume_yes:
            if not self._confirm():
                self._report.aborted = True
                self._report.finished_at = _now_iso()
                return self._report

        for index, name in enumerate(IMPORT_ORDER, start=1):
            spec = TABLES[name]
            stats = await self._import_table(spec, index)
            self._report.tables[name] = stats

        for table, count in self._ids.remapped_counts.items():
            if count:
                self._report.warnings.append(
                    f"{table}: {count} id(s) could not be preserved and were "
                    "replaced by deterministic uuid5 values; references to "
                    "them were remapped automatically."
                )

        if self._options.verify and not self._options.dry_run:
            self._report.verification = await self._verify()

        self._report.finished_at = _now_iso()
        return self._report

    # -- preflight ---------------------------------------------------------

    def _check_manifest_secrets(self) -> None:
        """Refuse to import an export that failed its secret scan."""

        scan = self._manifest.get("secret_scan") or {}
        status = scan.get("status")

        self._report.secret_scan = ScanResult()
        self._report.secret_scan.scanned_records = int(
            scan.get("scanned_records") or 0
        )

        if status == "failed":
            raise MigrationToolError(
                "This export failed its secret scan "
                f"({scan.get('critical_count', 0)} critical finding(s)); it "
                "may contain credentials. Review it, remove the secret from "
                "Supabase and export again — the import is aborted and "
                "nothing was written."
            )
        if status == "warnings":
            self._report.warnings.append(
                "this export contains sensitive-looking values (secret scan: "
                f"{scan.get('suspicious_count', 0)} suspicious finding(s)); "
                "review them before trusting this data"
            )

    async def _preflight(self, conn: Any) -> None:
        warnings = self._report.warnings

        await self._check_migrations(conn)
        await self._check_schema(conn)

        if warnings:
            for warning in warnings:
                self._progress(f"warning: {warning}")

    async def _check_migrations(self, conn: Any) -> None:
        migrator = Migrator(self._pool)
        try:
            status = await migrator.status()
        except Exception as exc:  # noqa: BLE001 - surfaced as a clear error
            raise MigrationToolError(
                "Could not read the migration state of the target database: "
                f"{exc}"
            ) from exc

        applied = {
            str(entry["version"]): str(entry.get("checksum"))
            for entry in status.get("applied", [])
        }
        pending = [entry for entry in status.get("pending", [])]
        if pending:
            names = ", ".join(
                f"{entry.get('version')}_{entry.get('name')}"
                for entry in pending
            )
            raise MigrationToolError(
                "The target database has pending migrations "
                f"({names}). Run 'python -m database migrate' first; the "
                "migration tool never changes the schema."
            )

        expected = {
            str(entry.get("version")): str(entry.get("checksum"))
            for entry in (self._manifest.get("schema") or {}).get(
                "migrations", []
            )
        }
        for version, checksum in sorted(expected.items()):
            if version not in applied:
                raise MigrationToolError(
                    f"The target database is missing migration {version} that "
                    "this export expects (the export was made against a newer "
                    "schema). Run 'python -m database migrate' first."
                )
            if applied[version] != checksum:
                raise MigrationToolError(
                    f"Migration {version} is applied with a different "
                    "checksum than this export expects; the database schema "
                    "does not match the export."
                )

        extra = sorted(set(applied) - set(expected))
        if extra:
            self._report.warnings.append(
                "target database has newer migrations than the export "
                f"({', '.join(extra)}); import continues with the columns "
                "both schemas share."
            )
            self._progress(
                "note: target schema is newer than the export "
                f"({', '.join(extra)})"
            )

    async def _check_schema(self, conn: Any) -> None:
        rows = await conn.fetch(SCHEMA_COLUMNS_SQL, list(TABLES))
        found: dict[str, dict[str, str]] = {}
        for row in rows:
            found.setdefault(str(row["table_name"]), {})[
                str(row["column_name"])
            ] = str(row["data_type"])

        problems: list[str] = []
        for name in IMPORT_ORDER:
            spec = TABLES[name]
            columns = found.get(name)
            if columns is None:
                problems.append(f"table {name!r} does not exist")
                continue
            for column in spec.insert_columns:
                if column.name not in columns:
                    problems.append(f"{name}.{column.name} does not exist")
                    continue
                expected_types = ACCEPTABLE_TYPES.get(column.kind, ())
                actual = columns[column.name]
                if expected_types and actual not in expected_types:
                    problems.append(
                        f"{name}.{column.name} is {actual}, expected "
                        f"{'/'.join(expected_types)}"
                    )

        if problems:
            raise MigrationToolError(
                "The target schema does not match the export: "
                + "; ".join(problems[:8])
                + ". Run 'python -m database migrate'."
            )

    # -- confirmation ------------------------------------------------------

    def _confirm(self) -> bool:
        confirm = self._options.confirm
        summary = self.confirmation_text()
        if confirm is None:
            # No interactive callback wired (non-interactive caller): refuse
            # instead of silently importing.
            return False
        return bool(confirm(summary))

    def confirmation_text(self) -> str:
        lines = [
            "About to import a Supabase export into PostgreSQL.",
            f"  export:  {self._path}",
            "  target:  DATABASE_BACKEND=postgres",
            "",
            "WARNING: existing PostgreSQL data is NOT deleted, truncated or "
            "reset by this tool.",
            "         Rows that already exist are skipped; everything else is "
            "added.",
            "         Make a backup (pg_dump) before you continue.",
            "",
            "Per table (source rows):",
        ]
        for name in IMPORT_ORDER:
            entry = (self._manifest.get("tables") or {}).get(name) or {}
            count = entry.get("count")
            lines.append(f"  {name:<24} {count if count is not None else '?'}")
        lines.append("")
        total = (self._manifest.get("totals") or {}).get("records")
        lines.append(f"Total records: {total if total is not None else '?'}")
        return "\n".join(lines)

    # -- import ------------------------------------------------------------

    async def _import_table(self, spec: TableSpec, index: int) -> TableImportStats:
        stats = TableImportStats(table=spec.name)
        manifest_entry = (self._manifest.get("tables") or {}).get(spec.name) or {}

        if manifest_entry.get("status") not in (None, "ok"):
            stats.errors += 1
            stats.note(
                f"export status {manifest_entry.get('status')!r}: "
                f"{manifest_entry.get('error', '')}"
            )
            self._report.errors.append(
                f"{spec.name}: the export reported status "
                f"{manifest_entry.get('status')!r}"
            )
            return stats

        try:
            rows_path = _table_path(self._path, self._manifest, spec.name)
        except MigrationToolError as exc:
            stats.errors += 1
            stats.note(str(exc))
            self._report.errors.append(str(exc))
            return stats

        if spec.name in CONTENT_DEDUPE_COLUMNS:
            # Chronological order keeps regenerated ids aligned with history
            # ordering (rollback reads the newest rows first).
            source = _sorted_rows(rows_path, spec)
        else:
            source = iter_rows(rows_path)

        real_pool = await self._pool.pool()
        statement = insert_sql(spec)
        consecutive_failures = 0

        async with real_pool.acquire() as conn:
            batch: list[tuple[int, dict]] = []
            for line_number, row in source:
                batch.append((line_number, row))
                if len(batch) < self._batch_size:
                    continue

                ok = await self._process_batch(
                    conn, spec, statement, batch, stats, index
                )
                batch = []
                consecutive_failures = 0 if ok else consecutive_failures + 1
                if consecutive_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                    self._report.errors.append(
                        f"{spec.name}: aborted after "
                        f"{consecutive_failures} consecutive batch failures"
                    )
                    stats.errors += 1
                    break

            if batch and consecutive_failures < MAX_CONSECUTIVE_BATCH_FAILURES:
                await self._process_batch(
                    conn, spec, statement, batch, stats, index
                )

        self._progress(
            f"[{index}/{len(IMPORT_ORDER)}] {spec.name}: "
            f"{stats.source_rows} source rows, "
            f"{'would insert' if self._options.dry_run else 'inserted'} "
            f"{stats.inserted}, skipped {stats.skipped}, "
            f"invalid {stats.invalid_rows}, dependencies "
            f"{stats.dependency_problems}, errors {stats.errors}"
        )
        return stats

    async def _process_batch(
        self,
        conn: Any,
        spec: TableSpec,
        statement: str,
        batch: list[tuple[int, dict]],
        stats: TableImportStats,
        index: int,
    ) -> bool:
        """Validate, de-duplicate and insert one batch. Returns success."""

        stats.batches += 1
        stats.source_rows += len(batch)

        prepared: list[tuple[int, dict, dict]] = []  # (line, row, values)
        for line_number, row in batch:
            values, errors = normalize_row(spec, row)
            if errors:
                stats.invalid_rows += 1
                stats.note(f"line {line_number}: {'; '.join(errors[:2])}")
                continue

            if spec.id_policy == "preserve":
                identifier, remapped = self._ids.map_primary(
                    spec.name, row.get("id"), fallback=row
                )
                values["id"] = identifier
                if remapped:
                    stats.id_remapped += 1

            prepared.append((line_number, row, values))

        if not prepared:
            return True

        # 1. Foreign keys: rows whose parent is missing cannot be inserted.
        await self._resolve_dependencies(conn, spec, prepared, stats)

        # 2. Which of the remaining rows are already present in the target?
        await self._mark_existing(conn, spec, prepared, stats)

        # 3. Insert what is left (nothing at all in dry-run mode).
        to_insert = [item for item in prepared if not item[2].get("_skip")]
        if not to_insert:
            return True

        if self._options.dry_run:
            stats.inserted += len(to_insert)
            self._remember_available(spec, to_insert)
            return True

        columns = spec.insert_columns
        params = [
            tuple(
                _encode_value(column, values[column.name])
                for column in columns
            )
            for _line, _row, values in to_insert
        ]

        try:
            await self._execute_batch(conn, statement, params)
        except Exception as exc:  # noqa: BLE001 - classified below
            stats.failed_batches += 1
            stats.errors += 1
            stats.note(f"batch failed: {_safe_error(exc)}")
            self._report.errors.append(
                f"{spec.name}: batch failed: {_safe_error(exc)}"
            )
            return False

        self._remember_available(spec, to_insert)
        inserted = await self._count_inserted(conn, spec, to_insert)
        stats.inserted += inserted
        stats.skipped_conflict += len(to_insert) - inserted
        if len(to_insert) - inserted:
            stats.note(
                f"{len(to_insert) - inserted} row(s) skipped by the database "
                "conflict policy"
            )
        return True

    def _remember_available(
        self,
        spec: TableSpec,
        rows: list[tuple[int, dict, dict]],
    ) -> None:
        """Track ids whose parents are now (or would be) available.

        Only ids of rows that were really stored are remembered: when a batch
        fails, its children are reported as dependency problems instead of
        hitting a foreign key violation.
        """

        for _line, _row, values in rows:
            identifier = values.get("id")
            if identifier is not None:
                self._available.setdefault(spec.name, set()).add(identifier)

    async def _execute_batch(
        self,
        conn: Any,
        statement: str,
        params: Sequence[tuple],
    ) -> None:
        """Insert one batch inside a transaction, with a safe retry."""

        attempt = 0
        while True:
            attempt += 1
            try:
                async with conn.transaction():
                    await conn.executemany(statement, params)
                return
            except Exception as exc:  # noqa: BLE001 - classify and re-raise
                if attempt >= MAX_RETRIES or not _is_retryable(exc):
                    raise
                delay = RETRY_BACKOFF_SECONDS[
                    min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)
                ]
                logger.warning(
                    "Transient database error during import (attempt %s/%s), "
                    "retrying in %.1fs: %s",
                    attempt,
                    MAX_RETRIES,
                    delay,
                    _safe_error(exc),
                )
                self._progress(
                    f"  transient database error, retry {attempt}/{MAX_RETRIES}"
                )
                await asyncio.sleep(delay)

    # -- dependency resolution --------------------------------------------

    async def _resolve_dependencies(
        self,
        conn: Any,
        spec: TableSpec,
        prepared: list[tuple[int, dict, dict]],
        stats: TableImportStats,
    ) -> None:
        for fk in spec.references:
            needed: set[uuid.UUID] = set()
            raw_by_value: dict[uuid.UUID, list[tuple[int, dict, dict]]] = {}

            for item in prepared:
                if item[2].get("_skip"):
                    continue
                raw = item[1].get(fk.column)
                if raw in (None, ""):
                    continue
                resolved = self._ids.resolve(fk.ref_table, raw)
                if resolved is None:
                    _mark_skipped(item, "dependency")
                    stats.dependency_problems += 1
                    if fk.soft:
                        stats.soft_dependency_warnings += 1
                    stats.note(
                        f"line {item[0]}: {fk.column} "
                        f"{str(raw)[:12]}… cannot be resolved"
                    )
                    continue
                item[2][fk.column] = resolved
                needed.add(resolved)
                raw_by_value.setdefault(resolved, []).append(item)

            if not needed:
                continue

            existing = await _fetch_ids(conn, fk.ref_table, sorted(needed))
            written_now = self._available.get(fk.ref_table, set())
            for value, items in raw_by_value.items():
                if value in existing or value in written_now:
                    continue
                for item in items:
                    if fk.soft:
                        # No FK constraint: keep the row, warn about it.
                        stats.soft_dependency_warnings += 1
                        stats.note(
                            f"line {item[0]}: {fk.column} points at a missing "
                            f"{fk.ref_table} row (soft reference, row kept)"
                        )
                        continue
                    _mark_skipped(item, "dependency")
                    stats.dependency_problems += 1
                    stats.note(
                        f"line {item[0]}: {fk.column} points at a missing "
                        f"{fk.ref_table} row"
                    )

    # -- existing/conflicting detection ------------------------------------

    async def _mark_existing(
        self,
        conn: Any,
        spec: TableSpec,
        prepared: list[tuple[int, dict, dict]],
        stats: TableImportStats,
    ) -> None:
        if spec.name in CONTENT_DEDUPE_COLUMNS:
            await self._mark_existing_actions(conn, spec, prepared, stats)
            return

        if spec.name == "prompt_versions":
            names = sorted(
                {str(values["name"]) for _l, _r, values in prepared
                 if not values.get("_skip")}
            )
            existing: set[tuple[str, str]] = set()
            if names:
                rows = await conn.fetch(
                    select_existing_prompt_versions_sql(), names
                )
                existing = {
                    (str(row["name"]), str(row["version"])) for row in rows
                }
            for item in prepared:
                values = item[2]
                if values.get("_skip"):
                    continue
                key = (str(values["name"]), str(values["version"]))
                if key in existing:
                    _mark_skipped(item, "existing")
                    stats.skipped_existing += 1
            return

        ids = [
            values["id"]
            for _l, _r, values in prepared
            if not values.get("_skip") and values.get("id") is not None
        ]
        existing_ids = await _fetch_ids(conn, spec.name, ids) if ids else set()

        for item in prepared:
            values = item[2]
            if values.get("_skip"):
                continue
            if values.get("id") in existing_ids:
                _mark_skipped(item, "existing")
                stats.skipped_existing += 1

        if spec.name == "memories":
            await self._mark_conflicting_memories(conn, prepared, stats)

    async def _mark_conflicting_memories(
        self,
        conn: Any,
        prepared: list[tuple[int, dict, dict]],
        stats: TableImportStats,
    ) -> None:
        """Honour the partial unique index on active memories."""

        candidates = [
            item
            for item in prepared
            if not item[2].get("_skip") and item[2].get("deleted_at") is None
        ]
        if not candidates:
            return

        guilds = sorted(
            {str(values["guild_id"]) for _l, _r, values in candidates
             if values.get("guild_id") is not None}
        )
        rows = await conn.fetch(
            select_active_memory_keys_sql(), guilds
        ) if guilds else []

        existing_keys = {
            (
                str(row["guild_id"]),
                str(row["user_id"]) if row["user_id"] is not None else None,
                str(row["memory_type"]),
                str(row["memory_key"]),
            )
            for row in rows
        }
        seen_in_batch: set[tuple] = set()

        for item in candidates:
            values = item[2]
            key = (
                str(values["guild_id"]),
                str(values["user_id"]) if values.get("user_id") is not None
                else None,
                str(values["memory_type"]) if values.get("memory_type")
                else "preference",
                str(values["memory_key"]),
            )
            if key in existing_keys or key in seen_in_batch:
                _mark_skipped(item, "conflict")
                stats.skipped_conflict += 1
                stats.note(
                    f"line {item[0]}: active memory {key[3]!r} already exists "
                    "for this guild/user/type"
                )
            else:
                seen_in_batch.add(key)

    async def _mark_existing_actions(
        self,
        conn: Any,
        spec: TableSpec,
        prepared: list[tuple[int, dict, dict]],
        stats: TableImportStats,
    ) -> None:
        """Actions have no preserved id: de-duplicate on content."""

        candidates = [item for item in prepared if not item[2].get("_skip")]
        if not candidates:
            return

        guilds = sorted(
            {
                str(values["guild_id"])
                for _l, _r, values in candidates
                if values.get("guild_id") is not None
            }
        )
        timestamps = [
            values["created_at"]
            for _l, _r, values in candidates
            if values.get("created_at") is not None
        ]
        if not guilds or not timestamps:
            return

        rows = await conn.fetch(
            select_action_fingerprints_sql(),
            guilds,
            min(timestamps),
            max(timestamps),
        )

        existing = {
            (
                str(row["guild_id"]),
                str(row["user_id"]) if row["user_id"] is not None else None,
                str(row["action_type"]) if row["action_type"] is not None
                else None,
                _fingerprint_json(row["data"]),
                row["created_at"],
            )
            for row in rows
        }

        for item in candidates:
            values = item[2]
            fingerprint = row_fingerprint(spec, values)
            if fingerprint in existing:
                _mark_skipped(item, "existing")
                stats.skipped_existing += 1
            else:
                existing.add(fingerprint)

    # -- counting ----------------------------------------------------------

    async def _count_inserted(
        self,
        conn: Any,
        spec: TableSpec,
        inserted: list[tuple[int, dict, dict]],
    ) -> int:
        """Exact number of rows the database actually stored."""

        if spec.name in CONTENT_DEDUPE_COLUMNS:
            # Every row was checked against the content fingerprint first.
            return len(inserted)

        if spec.name == "prompt_versions":
            keys = {
                (str(values["name"]), str(values["version"]))
                for _l, _r, values in inserted
            }
            rows = await conn.fetch(
                select_existing_prompt_versions_sql(),
                sorted({name for name, _version in keys}),
            )
            present = {
                (str(row["name"]), str(row["version"])) for row in rows
            }
            # Distinct keys: two rows sharing one key can only be stored once.
            return len(keys & present)

        ids = [
            values["id"]
            for _l, _r, values in inserted
            if values.get("id") is not None
        ]
        if not ids:
            return len(inserted)
        existing = await _fetch_ids(conn, spec.name, ids)
        return sum(1 for value in ids if value in existing)

    # -- post-import verification -----------------------------------------

    async def _verify(self) -> VerificationReport:
        report = VerificationReport()
        real_pool = await self._pool.pool()

        async with real_pool.acquire() as conn:
            for name in IMPORT_ORDER:
                spec = TABLES[name]
                row = await conn.fetchrow(select_count_sql(spec))
                total = int(row["total"]) if row else 0
                report.target_counts[name] = total
                stats = self._report.tables.get(name)
                if stats is None:
                    continue
                stats.target_total = total

                expected = stats.inserted + stats.skipped_existing
                report.checks.append(
                    VerificationCheck(
                        f"{name}.row_count",
                        total >= expected,
                        f"target={total} expected>={expected} "
                        f"(inserted={stats.inserted}, "
                        f"already_present={stats.skipped_existing})",
                    )
                )
                if stats.errors or stats.invalid_rows:
                    report.checks.append(
                        VerificationCheck(
                            f"{name}.errors",
                            False,
                            f"errors={stats.errors} "
                            f"invalid_rows={stats.invalid_rows}",
                        )
                    )

            # Foreign keys must not have orphans.
            for name in IMPORT_ORDER:
                spec = TABLES[name]
                for fk in spec.references:
                    row = await conn.fetchrow(select_orphan_sql(spec, fk))
                    orphans = int(row["total"]) if row else 0
                    if fk.soft:
                        report.checks.append(
                            VerificationCheck(
                                f"{name}.{fk.column}_reference",
                                True,
                                f"{orphans} dangling (soft) reference(s)",
                            )
                        )
                        continue
                    report.checks.append(
                        VerificationCheck(
                            f"{name}.{fk.column}_fk",
                            orphans == 0,
                            f"{orphans} orphan row(s)",
                        )
                    )

            # NOT NULL jsonb / timestamp columns.
            for name in IMPORT_ORDER:
                spec = TABLES[name]
                for column in spec.columns:
                    if column.nullable:
                        continue
                    row = await conn.fetchrow(
                        f"select count(*) as total from {spec.name} "
                        f"where {column.name} is null"
                    )
                    nulls = int(row["total"]) if row else 0
                    if nulls:
                        report.checks.append(
                            VerificationCheck(
                                f"{name}.{column.name}_not_null",
                                False,
                                f"{nulls} row(s) with NULL "
                                f"{column.name}",
                            )
                        )

            # Guild isolation: every row belongs to exactly one guild.
            for name in IMPORT_ORDER:
                if not TABLES[name].has("guild_id"):
                    continue
                row = await conn.fetchrow(
                    f"select count(*) as total from {name} "
                    f"where guild_id is null or guild_id = ''"
                )
                broken = int(row["total"]) if row else 0
                report.checks.append(
                    VerificationCheck(
                        f"{name}.guild_scope",
                        broken == 0,
                        f"{broken} row(s) without a guild_id",
                    )
                )

        return report


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _table_path(export_path: Path, manifest: dict, table: str) -> Path:
    entry = (manifest.get("tables") or {}).get(table) or {}
    file_name = entry.get("file")
    if not file_name:
        raise MigrationToolError(
            f"Manifest has no file entry for table {table!r}"
        )
    path = export_path / str(file_name)
    if not path.is_file():
        raise MigrationToolError(
            f"Export file for table {table!r} is missing: {path}"
        )
    return path


def _encode_value(column: Column, value: Any) -> Any:
    """asyncpg needs JSON as text for the ``::jsonb`` cast."""

    if value is None:
        return None
    if column.kind == "jsonb":
        return json.dumps(value, default=str)
    return value


def _sorted_rows(path: Path, spec: TableSpec):
    """Rows sorted by created_at (then id) for stable regenerated ids."""

    rows = [(number, row) for number, row in iter_rows(path)]

    def sort_key(item: tuple[int, dict]) -> tuple:
        row = item[1]
        created = row.get("created_at") or ""
        raw_id = row.get("id")
        identifier = (
            (0, int(raw_id))
            if isinstance(raw_id, int)
            else (1, str(raw_id))
        )
        return (str(created), identifier)

    rows.sort(key=sort_key)
    yield from rows


def _fingerprint_json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, str):
        try:
            return json.dumps(json.loads(value), sort_keys=True, default=str)
        except ValueError:
            return value
    return json.dumps(value, default=str)


def _mark_skipped(item: tuple[int, dict, dict], reason: str) -> None:
    item[2]["_skip"] = True
    item[2]["_skip_reason"] = reason


async def _fetch_ids(
    conn: Any, table: str, ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    if not ids:
        return set()
    rows = await conn.fetch(select_rows_by_ids_sql(TABLES[table]), list(ids))
    return {row["id"] for row in rows}


def _is_retryable(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate is not None and str(sqlstate) in RETRYABLE_SQLSTATES:
        return True
    return isinstance(
        exc,
        (
            asyncpg.PostgresConnectionError,
            asyncio.TimeoutError,
            ConnectionError,
            OSError,
        ),
    )


def _safe_error(exc: Exception) -> str:
    """Error text with credentials removed, safe for logs and output."""

    from database.migration.secrets import redact

    return redact(f"{type(exc).__name__}: {exc}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
