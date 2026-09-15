"""Supabase → files exporter (paginated, secret-safe).

The exporter only *reads* from Supabase (PostgREST) and writes JSONL files
plus a manifest.  It never touches Supabase writes, never connects to
PostgreSQL and never needs PostgreSQL to be running.

Pagination
----------
PostgREST returns at most ``MAX_PAGE_SIZE`` rows per request and defaults to
1000, so a plain ``select("*")`` silently truncates big tables.  Every table
is therefore read with ``range(start, end)`` in pages, ordered by
``(created_at, id)`` — a total order, because ``id`` is the primary key, which
makes paging deterministic (no skipped or duplicated rows).  If the source
table has no such columns the exporter falls back to unordered paging and
records that in the manifest.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from database.migration import manifest as manifest_module
from database.migration.manifest import TableExport
from database.migration.model import (
    DEFAULT_PAGE_SIZE,
    IMPORT_ORDER,
    MAX_PAGE_SIZE,
    TABLES,
    TableSpec,
)
from database.migration.secrets import ScanResult, SecretScanner

logger = logging.getLogger("ai_discord_builder.database.migration.export")

ProgressCallback = Callable[[str], None]


def _noop(message: str) -> None:  # pragma: no cover - default sink
    return None


@dataclass
class ExportOptions:
    output_dir: Path
    page_size: int = DEFAULT_PAGE_SIZE
    tables: tuple[str, ...] = IMPORT_ORDER
    progress: ProgressCallback = _noop
    secret_values: Iterable[str] | None = None


@dataclass
class ExportResult:
    directory: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, TableExport] = field(default_factory=dict)
    secret_scan: ScanResult = field(default_factory=ScanResult)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.secret_scan.ok

    @property
    def total_records(self) -> int:
        return sum(entry.count for entry in self.tables.values())


class SupabaseExporter:
    """Export the migrated tables from a Supabase project to disk."""

    def __init__(self, client: Any, options: ExportOptions) -> None:
        self._client = client
        self._options = options
        self._scanner = SecretScanner(secret_values=options.secret_values)
        self._page_size = _clamp_page_size(options.page_size)
        self._result = ExportResult(directory=Path(options.output_dir))
        self._progress = options.progress or _noop

    # -- public API --------------------------------------------------------

    def export(self, source: dict[str, Any] | None = None) -> ExportResult:
        """Run the export.  Never raises for per-table failures."""

        directory = Path(self._options.output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self._progress(f"Exporting to {directory}")

        for name in self._options.tables:
            spec = TABLES.get(name)
            if spec is None:  # pragma: no cover - CLI validates table names
                self._result.errors.append(f"unknown table {name!r}")
                continue
            try:
                table_export = self._export_table(spec, directory)
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                message = _mask(str(exc))
                self._result.errors.append(f"{name}: {message}")
                self._progress(f"  {name}: FAILED ({message})")
                table_export = TableExport(
                    table=name,
                    file=f"{name}.jsonl",
                    status="error",
                    error=message,
                    ordering=spec.order_by,
                )
            self._result.tables[name] = table_export

        self._result.manifest = manifest_module.build_manifest(
            tables=self._result.tables,
            source=source or {},
            secret_scan=self._result.secret_scan,
            notes=[
                "This export is a read-only snapshot: the Supabase project is "
                "never modified and no Supabase data is deleted.",
                "Exports contain conversation and memory data — treat them as "
                "sensitive and keep them out of version control.",
            ],
        )
        manifest_module.write_json_atomic(
            directory / manifest_module.MANIFEST_FILENAME,
            self._result.manifest,
        )
        self._progress(f"Manifest written: {directory / 'manifest.json'}")
        return self._result

    # -- internals ---------------------------------------------------------

    def _export_table(self, spec: TableSpec, directory: Path) -> TableExport:
        file_name = f"{spec.name}.jsonl"
        path = directory / file_name
        export = TableExport(table=spec.name, file=file_name, ordering=spec.order_by)

        ordered = list(spec.order_by)
        start = 0
        page = 0

        with open(path, "w", encoding="utf-8") as handle:
            while True:
                rows, reported_total, ordered = self._fetch_page(
                    spec, start, ordered
                )
                export.ordering = tuple(ordered)
                if reported_total is not None:
                    export.reported_total = reported_total

                if not rows:
                    break

                page += 1
                export.pages = page
                for row in rows:
                    line = json.dumps(row, ensure_ascii=False, default=str)
                    handle.write(line + "\n")
                    export.count += 1
                    export.bytes += len(line.encode("utf-8")) + 1
                    self._observe(spec, export, row, index=export.count)

                self._progress(
                    self._progress_message(spec, export, reported_total)
                )

                if len(rows) < self._page_size:
                    break
                start += self._page_size

        if export.count == 0 and export.status == "ok":
            self._progress(f"  {spec.name}: no rows")

        export.sha256 = manifest_module.file_sha256(path)
        export.bytes = path.stat().st_size
        return export

    def _fetch_page(
        self,
        spec: TableSpec,
        start: int,
        ordered: list[str],
    ) -> tuple[list[dict], int | None, list[str]]:
        """Fetch one page; falls back to unordered paging when needed."""

        end = start + self._page_size - 1
        try:
            response = self._run_query(spec, start, end, ordered)
        except Exception as exc:  # noqa: BLE001 - decide whether to fall back
            if ordered and _is_ordering_error(exc, ordered):
                logger.warning(
                    "Table %s has no %s column(s); falling back to unordered "
                    "pagination",
                    spec.name,
                    ", ".join(ordered),
                )
                response = self._run_query(spec, start, end, [])
                ordered = []
            else:
                raise

        rows = list(getattr(response, "data", None) or [])
        count = getattr(response, "count", None)
        return rows, count if isinstance(count, int) else None, ordered

    def _run_query(
        self,
        spec: TableSpec,
        start: int,
        end: int,
        ordered: list[str],
    ) -> Any:
        query = self._client.table(spec.name).select("*", count="exact")
        for column in ordered:
            query = query.order(column)
        return query.range(start, end).execute()

    def _observe(
        self,
        spec: TableSpec,
        export: TableExport,
        row: Any,
        index: int,
    ) -> None:
        if not isinstance(row, dict):
            return

        for key in row:
            if key not in export.observed_columns:
                export.observed_columns.append(key)

        raw_id = row.get("id")
        if raw_id is not None:
            kind = "uuid" if _looks_like_uuid(raw_id) else type(raw_id).__name__
            if kind not in export.id_types:
                export.id_types.append(kind)

        guild_id = row.get("guild_id")
        if guild_id is not None:
            key = str(guild_id)
            export.guild_counts[key] = export.guild_counts.get(key, 0) + 1

        for finding in self._scanner.scan_record(
            row, path=f"{spec.name}[{index - 1}]"
        ):
            if len(self._result.secret_scan.findings) >= 50:
                continue
            self._result.secret_scan.add(finding)
        self._result.secret_scan.scanned_records += 1

    def _progress_message(
        self,
        spec: TableSpec,
        export: TableExport,
        reported_total: int | None,
    ) -> str:
        total = reported_total
        if total and total > 0:
            percentage = min(100, int(export.count * 100 / total))
            return (
                f"  {spec.name}: {export.count}/{total} rows "
                f"({percentage}%, page {export.pages})"
            )
        return f"  {spec.name}: {export.count} rows (page {export.pages})"


def _clamp_page_size(value: int) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return max(1, min(size, MAX_PAGE_SIZE))


def _looks_like_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.strip().split("-")
    return len(parts) == 5 and all(
        len(part) in {8, 4, 12} for part in parts
    ) and len(value.strip()) == 36


def _is_ordering_error(exc: Exception, ordered: list[str]) -> bool:
    """True when the error is caused by the ORDER BY columns."""

    message = str(exc).lower()
    if any(column.lower() in message for column in ordered):
        return True
    return "does not exist" in message or "pgrst100" in message


def source_section(url: str | None, page_size: int) -> dict[str, Any]:
    """Describe the export source without ever exposing the API key."""

    host = ""
    if url:
        parsed = urlparse(url)
        host = parsed.hostname or ""
    return {
        "backend": "supabase",
        "url_host": host,
        "page_size": page_size,
        "method": "postgrest range() pagination",
        "tables": list(IMPORT_ORDER),
    }


def _mask(text: str) -> str:
    """Keep credentials out of recorded error messages."""

    from database.migration.secrets import redact

    return redact(text)
