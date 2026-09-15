"""Manifest creation, checksums and loading for migration exports.

The manifest is written **last**: an export directory without a (valid)
``manifest.json`` is by definition incomplete, which is exactly what
``verify-export`` checks first.  The manifest never contains credentials —
only the *host* of the Supabase project, never its key.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database.migration.model import (
    FORMAT_VERSION,
    IMPORT_ORDER,
    MANIFEST_FILENAME,
    TABLES,
    TableSpec,
)
from database.migration.secrets import ScanResult

SUPPORTED_FORMAT_VERSIONS = ("1.0",)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_slug(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y%m%d-%H%M%S")


def file_sha256(path: str | Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file, streamed so large exports stay cheap."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: str | Path, payload: Any) -> None:
    """Write JSON via a temporary file so a crash cannot corrupt it."""

    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def new_export_dir(
    root: str | Path,
    now: datetime | None = None,
    prefix: str = "supabase-export",
) -> Path:
    """Return (but do not create) ``<root>/<prefix>-YYYYMMDD-HHMMSS``."""

    return Path(root) / f"{prefix}-{timestamp_slug(now)}"


# --------------------------------------------------------------------------
# Per-table bookkeeping
# --------------------------------------------------------------------------


@dataclass
class TableExport:
    """Result of exporting one table."""

    table: str
    file: str
    count: int = 0
    bytes: int = 0
    sha256: str = ""
    status: str = "ok"
    error: str = ""
    pages: int = 0
    reported_total: int | None = None
    observed_columns: list[str] = field(default_factory=list)
    id_types: list[str] = field(default_factory=list)
    guild_counts: dict[str, int] = field(default_factory=dict)
    ordering: tuple[str, ...] = ()

    def as_manifest_entry(self, guild_counts_limit: int = 100) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "file": self.file,
            "count": self.count,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "status": self.status,
            "pages": self.pages,
            "reported_total": self.reported_total,
            "observed_columns": sorted(self.observed_columns),
            "id_types": sorted(set(self.id_types)),
            "guild_count": len(self.guild_counts),
            "ordering": list(self.ordering),
        }
        if self.error:
            entry["error"] = self.error
        if self.guild_counts and len(self.guild_counts) <= guild_counts_limit:
            entry["guild_counts"] = dict(sorted(self.guild_counts.items()))
        return entry


# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------


def schema_section() -> dict[str, Any]:
    """Describe the target schema the export was produced for."""

    from database.postgres.migrator import load_migrations

    migrations = [
        {
            "version": migration.version,
            "name": migration.name,
            "checksum": migration.checksum,
        }
        for migration in load_migrations()
    ]

    tables: dict[str, Any] = {}
    for name, spec in TABLES.items():
        tables[name] = {
            "primary_key": spec.primary_key,
            "id_policy": spec.id_policy,
            "conflict_key": list(spec.conflict_key),
            "conflict_reason": spec.conflict_reason,
            "columns": [
                {
                    "name": column.name,
                    "type": column.kind,
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "default": column.default,
                    "check": column.check,
                }
                for column in spec.columns
            ],
            "foreign_keys": [
                {
                    "column": fk.column,
                    "references": f"{fk.ref_table}.{fk.ref_column}",
                    "soft": fk.soft,
                    "on_delete": fk.on_delete,
                }
                for fk in spec.foreign_keys
            ],
            "uniques": [
                {
                    "name": unique.name,
                    "columns": list(unique.columns),
                    "partial": unique.partial,
                }
                for unique in spec.uniques
            ],
        }

    return {
        "target_backend": "postgres",
        "migrations": migrations,
        "tables": tables,
    }


def import_section() -> dict[str, Any]:
    """Documented import order and per-table conflict policy."""

    conflict_policy = {}
    for name in IMPORT_ORDER:
        spec: TableSpec = TABLES[name]
        behavior = (
            "skip rows that already exist (on conflict "
            f"({', '.join(spec.conflict_key)}) do nothing)"
            if spec.conflict_key
            else "skip rows whose content already exists "
            "(primary key is regenerated)"
        )
        conflict_policy[name] = {
            "conflict_key": list(spec.conflict_key),
            "behavior": behavior,
            "reason": spec.conflict_reason,
            "id_policy": spec.id_policy,
            "id_policy_reason": spec.id_policy_reason or None,
        }

    return {
        "order": list(IMPORT_ORDER),
        "conflict_policy": conflict_policy,
        "notes": [
            "Import is additive: existing PostgreSQL rows are never deleted, "
            "truncated or dropped.",
            "Rows are inserted in batches; each batch runs in its own "
            "transaction so a failed batch rolls back on its own.",
            "Re-running the same export is safe: already imported rows are "
            "skipped, not duplicated.",
        ],
    }


def build_manifest(
    *,
    tables: dict[str, TableExport],
    source: dict[str, Any],
    secret_scan: ScanResult,
    generated_at: str | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the manifest payload."""

    total_records = sum(entry.count for entry in tables.values())
    return {
        "format_version": FORMAT_VERSION,
        "generated_at": generated_at or utc_now_iso(),
        "tool": {
            "name": "ai-discord-builder",
            "package": "database.migration",
            "command": "export-supabase",
        },
        "source": source,
        "schema": schema_section(),
        "totals": {
            "records": total_records,
            "tables": len(tables),
            "failed_tables": sum(
                1 for entry in tables.values() if entry.status != "ok"
            ),
        },
        "tables": {
            name: tables[name].as_manifest_entry()
            for name in IMPORT_ORDER
            if name in tables
        },
        "secret_scan": secret_scan.as_dict(),
        "import": import_section(),
        "notes": notes or [],
    }


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


class ManifestError(Exception):
    """The manifest is missing, unreadable or structurally invalid."""


def manifest_path(export_path: str | Path) -> Path:
    return Path(export_path) / MANIFEST_FILENAME


def load_manifest(export_path: str | Path) -> dict[str, Any]:
    """Read and structurally validate ``manifest.json``."""

    path = manifest_path(export_path)
    if not path.is_file():
        raise ManifestError(
            f"No manifest found: {path}. The directory is not a complete "
            "export (the manifest is written last) or the path is wrong."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"Could not read {path}: {exc}") from exc

    problems = manifest_problems(payload)
    if problems:
        raise ManifestError(
            f"{path} is not a valid export manifest: " + "; ".join(problems)
        )
    return payload


def manifest_problems(payload: Any) -> list[str]:
    """Structural checks; returns a list of human-readable problems."""

    if not isinstance(payload, dict):
        return ["manifest is not a JSON object"]

    problems: list[str] = []
    version = payload.get("format_version")
    if not isinstance(version, str):
        problems.append("missing 'format_version'")
    elif version not in SUPPORTED_FORMAT_VERSIONS:
        supported = ", ".join(SUPPORTED_FORMAT_VERSIONS)
        problems.append(
            f"unsupported format_version {version!r} (supported: {supported})"
        )

    for key in ("generated_at", "source", "tables"):
        if key not in payload:
            problems.append(f"missing '{key}'")

    tables = payload.get("tables")
    if tables is not None and not isinstance(tables, dict):
        problems.append("'tables' is not an object")

    scan = payload.get("secret_scan")
    if scan is not None and not isinstance(scan, dict):
        problems.append("'secret_scan' is not an object")

    return problems


def table_file(export_path: str | Path, manifest: dict[str, Any], table: str) -> Path:
    entry = manifest.get("tables", {}).get(table)
    if not isinstance(entry, dict) or not entry.get("file"):
        raise ManifestError(
            f"Manifest has no file entry for table {table!r}; the export is "
            "incomplete."
        )
    return Path(export_path) / str(entry["file"])
