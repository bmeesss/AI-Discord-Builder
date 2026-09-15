"""Offline validation of a migration export (``verify-export``).

Strictly read-only: the validator opens files, parses them and reports.  It
never writes, never connects to a database and never contacts Supabase.

Checks
------
* manifest presence, structure and supported format version;
* per table: file exists, JSONL syntax, record count vs. manifest, SHA-256;
* duplicate primary keys inside a table file;
* required fields, types and CHECK constraints (:mod:`database.migration.model`);
* column compatibility between the exported rows and the target schema;
* relational consistency (real foreign keys are errors, soft references are
  warnings);
* secret scan (critical findings are errors, suspicious ones warnings).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from database.migration import manifest as manifest_module
from database.migration.manifest import ManifestError, load_manifest
from database.migration.model import (
    IMPORT_ORDER,
    TABLES,
    TableSpec,
    normalize_row,
)
from database.migration.secrets import ScanResult, SecretScanner

MAX_REPORTED_ISSUES = 25
MAX_ISSUES_PER_TABLE = 10


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    kind: str
    message: str
    table: str = ""
    location: str = ""

    def format(self) -> str:
        prefix = "ERROR  " if self.severity == "error" else "WARNING"
        where = f" [{self.table}]" if self.table else ""
        at = f" at {self.location}" if self.location else ""
        return f"{prefix}{where} {self.kind}: {self.message}{at}"


@dataclass
class TableValidation:
    table: str
    file: str = ""
    declared_count: int | None = None
    actual_count: int = 0
    checksum_ok: bool | None = None
    status: str = "ok"
    invalid_rows: int = 0
    duplicate_ids: int = 0
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ValidationReport:
    export_path: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, TableValidation] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    secret_scan: ScanResult = field(default_factory=ScanResult)
    fatal: str | None = None

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        return self.fatal is None and not self.errors

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)
        if issue.table and issue.table in self.tables:
            if issue.severity == "error":
                self.tables[issue.table].errors.append(issue)
            else:
                self.tables[issue.table].warnings.append(issue)


class ExportValidator:
    """Validate an export directory."""

    def __init__(
        self,
        export_path: str | Path,
        secret_values: Iterable[str] | None = None,
    ) -> None:
        self._path = Path(export_path)
        self._scanner = SecretScanner(secret_values=secret_values)
        self._report = ValidationReport(export_path=self._path)

    def validate(self) -> ValidationReport:
        report = self._report

        if not self._path.exists():
            report.fatal = f"Export path does not exist: {self._path}"
            return report
        if not self._path.is_dir():
            report.fatal = f"Export path is not a directory: {self._path}"
            return report

        try:
            manifest = load_manifest(self._path)
        except ManifestError as exc:
            report.fatal = str(exc)
            return report

        report.manifest = manifest

        ids: dict[str, set[str]] = {}
        for name in IMPORT_ORDER:
            spec = TABLES[name]
            validation = self._validate_table(spec, manifest, ids)
            report.tables[name] = validation
            for issue in validation.errors + validation.warnings:
                report.issues.append(issue)

        self._validate_relations(ids)
        self._validate_manifest(manifest)

        return report

    # -- tables ------------------------------------------------------------

    def _validate_table(
        self,
        spec: TableSpec,
        manifest: dict[str, Any],
        ids: dict[str, set[str]],
    ) -> TableValidation:
        validation = TableValidation(table=spec.name)
        entry = manifest.get("tables", {}).get(spec.name)

        if not isinstance(entry, dict):
            validation.status = "missing"
            validation.errors.append(
                Issue(
                    "error",
                    "manifest",
                    f"no manifest entry for table {spec.name!r}",
                    table=spec.name,
                )
            )
            return validation

        validation.file = str(entry.get("file") or "")
        declared = entry.get("count")
        validation.declared_count = declared if isinstance(declared, int) else None

        if entry.get("status") not in (None, "ok"):
            validation.status = str(entry.get("status"))
            validation.errors.append(
                Issue(
                    "error",
                    "export_status",
                    f"export reported status "
                    f"{entry.get('status')!r}: {entry.get('error', '')}".strip(),
                    table=spec.name,
                )
            )

        path = self._path / validation.file if validation.file else None
        if not validation.file or path is None or not path.is_file():
            validation.status = "missing_file"
            validation.errors.append(
                Issue(
                    "error",
                    "missing_file",
                    f"file {validation.file!r} is missing",
                    table=spec.name,
                )
            )
            return validation

        table_ids: set[str] = set()
        seen_columns: set[str] = set()
        duplicates = 0
        invalid = 0
        line_number = 0

        try:
            with open(path, encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError as exc:
                        invalid += 1
                        self._add_table_issue(
                            validation,
                            spec,
                            Issue(
                                "error",
                                "json_syntax",
                                f"line {line_number} is not valid JSON: {exc}",
                                table=spec.name,
                                location=f"line {line_number}",
                            ),
                        )
                        continue

                    validation.actual_count += 1

                    if not isinstance(row, dict):
                        invalid += 1
                        self._add_table_issue(
                            validation,
                            spec,
                            Issue(
                                "error",
                                "row_type",
                                f"line {line_number} is not a JSON object",
                                table=spec.name,
                                location=f"line {line_number}",
                            ),
                        )
                        continue

                    for key in row:
                        seen_columns.add(key)

                    raw_id = row.get("id")
                    if raw_id is not None:
                        key = str(raw_id)
                        if key in table_ids:
                            duplicates += 1
                            self._add_table_issue(
                                validation,
                                spec,
                                Issue(
                                    "error",
                                    "duplicate_id",
                                    f"duplicate id {key[:12]}…",
                                    table=spec.name,
                                    location=f"line {line_number}",
                                ),
                            )
                        else:
                            table_ids.add(key)

                    _values, errors = normalize_row(spec, row)
                    if errors:
                        invalid += 1
                        self._add_table_issue(
                            validation,
                            spec,
                            Issue(
                                "error",
                                "invalid_row",
                                "; ".join(errors[:3]),
                                table=spec.name,
                                location=f"line {line_number}",
                            ),
                        )

                    for finding in self._scanner.scan_record(
                        row, path=f"{spec.name}[line {line_number}]"
                    ):
                        severity = (
                            "error"
                            if finding.severity == "critical"
                            else "warning"
                        )
                        self._add_table_issue(
                            validation,
                            spec,
                            Issue(
                                severity,
                                "secret",
                                finding.describe(),
                                table=spec.name,
                                location=f"line {line_number}",
                            ),
                        )
                        if len(self._report.secret_scan.findings) < 50:
                            self._report.secret_scan.add(finding)
                    self._report.secret_scan.scanned_records += 1
        except OSError as exc:  # pragma: no cover - filesystem failure
            validation.errors.append(
                Issue(
                    "error",
                    "unreadable_file",
                    str(exc),
                    table=spec.name,
                )
            )

        ids[spec.name] = table_ids
        validation.duplicate_ids = duplicates
        validation.invalid_rows = invalid

        if (
            validation.declared_count is not None
            and validation.declared_count != validation.actual_count
        ):
            validation.errors.append(
                Issue(
                    "error",
                    "count_mismatch",
                    f"manifest declares {validation.declared_count} records "
                    f"but the file contains {validation.actual_count}",
                    table=spec.name,
                )
            )

        expected_sha = entry.get("sha256")
        if isinstance(expected_sha, str) and expected_sha:
            actual_sha = manifest_module.file_sha256(path)
            validation.checksum_ok = actual_sha == expected_sha
            if not validation.checksum_ok:
                validation.errors.append(
                    Issue(
                        "error",
                        "checksum_mismatch",
                        "file content does not match the manifest checksum "
                        "(the export was modified after it was written)",
                        table=spec.name,
                    )
                )

        self._validate_columns(spec, validation, seen_columns)
        self._validate_id_types(spec, validation, entry)

        if validation.errors:
            validation.status = "invalid"
        elif validation.warnings:
            validation.status = "warnings"
        return validation

    def _add_table_issue(
        self,
        validation: TableValidation,
        spec: TableSpec,
        issue: Issue,
    ) -> None:
        if issue.severity == "error":
            if len(validation.errors) < MAX_ISSUES_PER_TABLE:
                validation.errors.append(issue)
        elif len(validation.warnings) < MAX_ISSUES_PER_TABLE:
            validation.warnings.append(issue)

    def _validate_columns(
        self,
        spec: TableSpec,
        validation: TableValidation,
        seen_columns: set[str],
    ) -> None:
        known = set(spec.column_names)

        unknown = sorted(seen_columns - known)
        if unknown:
            self._add_table_issue(
                validation,
                spec,
                Issue(
                    "warning",
                    "unknown_columns",
                    "columns not present in the target schema are ignored: "
                    + ", ".join(unknown[:10]),
                    table=spec.name,
                ),
            )

        if seen_columns:
            missing_required = [
                column.name
                for column in spec.columns
                if not column.nullable
                and column.default is None
                and column.name != "id"
                and column.name not in seen_columns
            ]
        else:
            missing_required = []
        if missing_required:
            self._add_table_issue(
                validation,
                spec,
                Issue(
                    "error",
                    "missing_columns",
                    "required columns absent from the export: "
                    + ", ".join(missing_required),
                    table=spec.name,
                ),
            )

    def _validate_id_types(
        self,
        spec: TableSpec,
        validation: TableValidation,
        entry: dict[str, Any],
    ) -> None:
        """Warn when a UUID primary key cannot be preserved."""

        if spec.id_policy != "preserve":
            return
        id_types = {
            str(value) for value in (entry.get("id_types") or [])
        }
        if not id_types or id_types <= {"uuid"}:
            return
        self._add_table_issue(
            validation,
            spec,
            Issue(
                "warning",
                "id_type",
                "source ids are not UUIDs "
                f"({', '.join(sorted(id_types))}); the importer replaces them "
                "with deterministic uuid5 values and remaps references",
                table=spec.name,
            ),
        )

    # -- relations ---------------------------------------------------------

    def _validate_relations(self, ids: dict[str, set[str]]) -> None:
        for name in IMPORT_ORDER:
            spec = TABLES[name]
            for fk in spec.foreign_keys:
                parent_ids = ids.get(fk.ref_table)
                child_ids = ids.get(name)
                if parent_ids is None or child_ids is None:
                    continue
                self._check_reference(spec, fk, name, parent_ids)

    def _check_reference(
        self,
        spec: TableSpec,
        fk: Any,
        table: str,
        parent_ids: set[str],
    ) -> None:
        """Count rows referencing a parent id that is absent from the export."""

        entry = self._report.manifest.get("tables", {}).get(table) or {}
        path = entry.get("file")
        if not path or not (self._path / str(path)).is_file():
            return

        missing = 0
        total = 0
        examples: list[str] = []
        with open(self._path / str(path), encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                value = row.get(fk.column)
                if value is None:
                    continue
                total += 1
                if str(value) not in parent_ids:
                    missing += 1
                    if len(examples) < 3:
                        examples.append(str(value)[:12] + "…")

        if missing:
            severity = "warning" if fk.soft else "error"
            self._report.add(
                Issue(
                    severity,
                    "missing_dependency" if not fk.soft else "soft_reference",
                    f"{missing}/{total} rows reference a "
                    f"{fk.ref_table}.{fk.ref_column} that is not part of the "
                    f"export (examples: {', '.join(examples)})",
                    table=table,
                    location=fk.column,
                )
            )

    # -- manifest ----------------------------------------------------------

    def _validate_manifest(self, manifest: dict[str, Any]) -> None:
        tables = manifest.get("tables") or {}
        for name in IMPORT_ORDER:
            if name not in tables:
                self._report.add(
                    Issue(
                        "error",
                        "manifest",
                        f"table {name!r} is missing from the manifest",
                        table=name,
                    )
                )

        extra = sorted(set(tables) - set(IMPORT_ORDER))
        if extra:
            self._report.add(
                Issue(
                    "warning",
                    "manifest",
                    "manifest lists unknown tables: " + ", ".join(extra),
                )
            )

        scan = manifest.get("secret_scan") or {}
        if scan.get("status") == "failed":
            self._report.add(
                Issue(
                    "error",
                    "secret_scan",
                    "the manifest records a failed secret scan; this export "
                    "must not be imported",
                )
            )
        elif scan.get("status") == "warnings":
            self._report.add(
                Issue(
                    "warning",
                    "secret_scan",
                    "the manifest records suspicious values; review them "
                    "before importing",
                )
            )

        totals = manifest.get("totals") or {}
        total_records = sum(
            entry.actual_count for entry in self._report.tables.values()
        )
        declared_total = totals.get("records")
        if isinstance(declared_total, int) and declared_total != total_records:
            self._report.add(
                Issue(
                    "error",
                    "total_mismatch",
                    f"manifest totals.records is {declared_total} but the "
                    f"files contain {total_records} records",
                )
            )


def iter_rows(path: Path) -> Iterable[tuple[int, dict]]:
    """Yield ``(line_number, row)`` for a JSONL file, skipping bad lines."""

    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield number, row
