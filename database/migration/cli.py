"""Command-line front-end for the migration tool.

The three commands are wired into ``python -m database``:

    export-supabase [--output DIR] [--page-size N]
    verify-export <export-path>
    import-postgres <export-path> [--dry-run] [--yes] [--batch-size N]

Everything printed here passes through :func:`~database.migration.secrets.redact`
so a credential can never end up in a terminal or CI log.  Stack traces are
only shown with ``--debug`` (or ``LOG_LEVEL=DEBUG``).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Callable

import config

from database.connection import mask_dsn
from database.errors import MigrationToolError, StorageError
from database.factory import resolve_backend
from database.migration.export import (
    ExportOptions,
    SupabaseExporter,
    source_section,
)
from database.migration.import_postgres import (
    ImportOptions,
    ImportReport,
    PostgresImporter,
)
from database.migration.manifest import new_export_dir
from database.migration.model import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_EXPORT_ROOT,
    DEFAULT_PAGE_SIZE,
    IMPORT_ORDER,
    MAX_PAGE_SIZE,
)
from database.migration.secrets import redact
from database.migration.validate import ExportValidator, ValidationReport
from database.supabase_backend import create_supabase_client

ProgressCallback = Callable[[str], None]


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def register_commands(subparsers: Any) -> None:
    """Add the migration commands to the ``python -m database`` parser."""

    export = subparsers.add_parser(
        "export-supabase",
        help="export the Supabase tables to a JSONL snapshot (read-only)",
    )
    export.add_argument(
        "--output",
        help=(
            "output directory (default: "
            f"{DEFAULT_EXPORT_ROOT}/supabase-export-YYYYMMDD-HHMMSS)"
        ),
    )
    export.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"rows per PostgREST request, 1-{MAX_PAGE_SIZE} "
        f"(default: {DEFAULT_PAGE_SIZE})",
    )
    export.add_argument(
        "--tables",
        help="comma-separated subset of tables to export (default: all)",
    )

    verify = subparsers.add_parser(
        "verify-export",
        help="validate an export directory (read-only, changes nothing)",
    )
    verify.add_argument("path", help="export directory")

    importer = subparsers.add_parser(
        "import-postgres",
        help="import an export into PostgreSQL (additive, idempotent)",
    )
    importer.add_argument("path", help="export directory")
    importer.add_argument(
        "--dry-run",
        action="store_true",
        help="only report what would happen; writes nothing",
    )
    importer.add_argument(
        "--yes",
        action="store_true",
        help="do not ask for confirmation (for automation)",
    )
    importer.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"rows per transaction (default: {DEFAULT_BATCH_SIZE})",
    )
    importer.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the automatic post-import verification pass",
    )


def selected_tables(value: str | None) -> tuple[str, ...]:
    if not value:
        return IMPORT_ORDER
    names = tuple(name.strip() for name in value.split(",") if name.strip())
    unknown = [name for name in names if name not in IMPORT_ORDER]
    if unknown:
        raise MigrationToolError(
            f"Unknown table(s): {', '.join(unknown)}. "
            f"Known tables: {', '.join(IMPORT_ORDER)}."
        )
    return names


# --------------------------------------------------------------------------
# export-supabase
# --------------------------------------------------------------------------


async def run_export(args: argparse.Namespace, progress: ProgressCallback) -> int:
    backend = resolve_backend()
    if backend != "supabase":
        print(
            f"'export-supabase' needs DATABASE_BACKEND=supabase (or only "
            f"SUPABASE_URL/SUPABASE_KEY configured); the active backend is "
            f"{backend!r}. Nothing was exported.",
            file=sys.stderr,
        )
        return 1

    client = create_supabase_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    directory = (
        Path(args.output)
        if getattr(args, "output", None)
        else new_export_dir(DEFAULT_EXPORT_ROOT)
    )
    if directory.exists() and any(directory.iterdir()):
        print(
            f"Refusing to write into non-empty directory: {directory}",
            file=sys.stderr,
        )
        return 1

    options = ExportOptions(
        output_dir=directory,
        page_size=getattr(args, "page_size", DEFAULT_PAGE_SIZE),
        tables=selected_tables(getattr(args, "tables", None)),
        progress=progress,
    )

    exporter = SupabaseExporter(client, options)
    result = await asyncio.to_thread(
        exporter.export,
        source_section(config.SUPABASE_URL, options.page_size),
    )

    print("")
    print(f"Export directory: {result.directory}")
    print("")
    _print_counts(
        {name: entry.count for name, entry in result.tables.items()},
        {name: entry.status for name, entry in result.tables.items()},
    )
    print("")
    print(f"Records exported: {result.total_records}")
    print(f"Secret scan: {result.secret_scan.status} "
          f"({result.secret_scan.scanned_records} records scanned)")

    for finding in result.secret_scan.findings[:10]:
        print(f"  {finding.describe()}")

    if result.errors:
        print("", file=sys.stderr)
        for error in result.errors:
            print(f"ERROR {redact(error)}", file=sys.stderr)

    if not result.ok:
        print(
            "\nExport NOT declared successful: resolve the errors above "
            "before using this export.",
            file=sys.stderr,
        )
        return 1

    print("")
    print(f"Next: python -m database verify-export {result.directory}")
    return 0


# --------------------------------------------------------------------------
# verify-export
# --------------------------------------------------------------------------


async def run_verify(args: argparse.Namespace, progress: ProgressCallback) -> int:
    path = Path(args.path)
    progress(f"Verifying export {path}")
    report = ExportValidator(path).validate()
    return _print_validation_report(report)


def _print_validation_report(report: ValidationReport) -> int:
    if report.fatal:
        print(f"ERROR {report.fatal}", file=sys.stderr)
        return 1

    print("")
    header = f"{'table':<24}{'declared':>10}{'actual':>10}{'sha256':>9}{'status':>12}"
    print(header)
    print("-" * len(header))
    for name in IMPORT_ORDER:
        entry = report.tables.get(name)
        if entry is None:
            continue
        checksum = {True: "ok", False: "MISMATCH", None: "-"}[entry.checksum_ok]
        print(
            f"{name:<24}{_fmt(entry.declared_count):>10}"
            f"{entry.actual_count:>10}{checksum:>9}{entry.status:>12}"
        )
    print("")

    for issue in report.issues[:25]:
        print(redact(issue.format()))
    if len(report.issues) > 25:
        print(f"... and {len(report.issues) - 25} more issue(s)")

    errors = len(report.errors)
    warnings = len(report.warnings)
    print("")
    print(
        f"Secret scan: {report.secret_scan.status} "
        f"(critical={len(report.secret_scan.critical)}, "
        f"suspicious={len(report.secret_scan.suspicious)})"
    )
    print(f"Result: {errors} error(s), {warnings} warning(s)")

    if errors:
        print("VERIFY FAILED: do not import this export.", file=sys.stderr)
        return 1
    if warnings:
        print("VERIFY OK (with warnings)")
        return 0
    print("VERIFY OK")
    return 0


# --------------------------------------------------------------------------
# import-postgres
# --------------------------------------------------------------------------


async def run_import(args: argparse.Namespace, progress: ProgressCallback) -> int:
    backend = resolve_backend()
    if backend != "postgres":
        print(
            f"'import-postgres' needs DATABASE_BACKEND=postgres; the active "
            f"backend is {backend!r}. Nothing was imported.",
            file=sys.stderr,
        )
        return 1

    from database.connection import PostgresPool

    pool = PostgresPool(config.DATABASE_URL or "", min_size=1, max_size=2)
    options = ImportOptions(
        batch_size=max(1, getattr(args, "batch_size", DEFAULT_BATCH_SIZE)),
        dry_run=bool(getattr(args, "dry_run", False)),
        assume_yes=bool(getattr(args, "yes", False)),
        verify=not bool(getattr(args, "no_verify", False)),
        progress=progress,
        confirm=_interactive_confirmation,
    )

    try:
        importer = PostgresImporter(pool, Path(args.path), options)
        report = await importer.run()
    finally:
        await pool.close()

    return _print_import_report(report)


def _interactive_confirmation(summary: str) -> bool:
    """Ask the operator to confirm; never imports silently."""

    print("")
    print(summary)
    print("")
    try:
        interactive = bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - exotic stdins
        interactive = False

    if not interactive:
        print(
            "Non-interactive session: refusing to import without "
            "confirmation. Re-run with --yes to import unattended.",
            file=sys.stderr,
        )
        return False

    try:
        answer = input("Type 'yes' to continue: ")
    except (EOFError, KeyboardInterrupt):
        print("")
        return False
    return answer.strip().lower() in {"yes", "y"}


def _print_import_report(report: ImportReport) -> int:
    label = "DRY RUN" if report.dry_run else "IMPORT"

    if report.aborted:
        print(f"{label} cancelled: nothing was written.")
        return 1

    print("")
    columns = (
        ("table", 24),
        ("source", 8),
        ("inserted", 9),
        ("skipped", 8),
        ("invalid", 8),
        ("deps", 6),
        ("errors", 7),
    )
    header = "".join(
        f"{name:>{width}}" if index else f"{name:<{width}}"
        for index, (name, width) in enumerate(columns)
    )
    print(header)
    print("-" * sum(width for _name, width in columns))

    for name in IMPORT_ORDER:
        stats = report.tables.get(name)
        if stats is None:
            continue
        print(
            f"{name:<24}{stats.source_rows:>8}"
            f"{stats.inserted:>9}{stats.skipped:>8}"
            f"{stats.invalid_rows:>8}{stats.dependency_problems:>6}"
            f"{stats.errors:>7}"
        )

    totals = report.totals
    print("")
    print(
        f"{label} totals: source={totals['source_rows']} "
        f"inserted={totals['inserted']} skipped={totals['skipped']} "
        f"invalid={totals['invalid_rows']} "
        f"dependency_problems={totals['dependency_problems']} "
        f"errors={totals['errors']}"
    )

    for warning in report.warnings:
        print(f"WARNING {redact(warning)}")

    for name in IMPORT_ORDER:
        stats = report.tables.get(name)
        if not stats:
            continue
        for example in stats.examples:
            print(f"  {name}: {redact(example)}")

    for error in report.errors:
        print(f"ERROR {redact(error)}", file=sys.stderr)

    verification = report.verification
    if verification is not None:
        print("")
        failed = [check for check in verification.checks if not check.ok]
        print(
            f"Verification: {len(verification.checks) - len(failed)}/"
            f"{len(verification.checks)} checks passed"
        )
        for check in failed[:10]:
            print(f"  FAILED {check.name}: {check.detail}")

    if report.dry_run:
        print("")
        print("Dry run complete: nothing was written.")
        print("Backup first, then run the same command without --dry-run.")
        return 0 if report.ok else 1

    if not report.ok:
        print("IMPORT FAILED (see errors above).", file=sys.stderr)
        return 1

    print("")
    print("IMPORT OK (additive: no existing data was deleted)")
    if verification is not None and not verification.ok:
        return 1
    return 0


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _print_counts(
    counts: dict[str, int], statuses: dict[str, str] | None = None
) -> None:
    statuses = statuses or {}
    header = f"{'table':<24}{'rows':>10}{'status':>10}"
    print(header)
    print("-" * len(header))
    for name in IMPORT_ORDER:
        if name not in counts:
            continue
        print(
            f"{name:<24}{counts[name]:>10}{statuses.get(name, 'ok'):>10}"
        )


def _fmt(value: int | None) -> str:
    return "-" if value is None else str(value)


def dsn_for_display() -> str:
    return mask_dsn(config.DATABASE_URL or "")


async def dispatch(args: argparse.Namespace, progress: ProgressCallback) -> int:
    """Run the requested migration command."""

    handlers = {
        "export-supabase": run_export,
        "verify-export": run_verify,
        "import-postgres": run_import,
    }
    handler = handlers.get(args.command)
    if handler is None:  # pragma: no cover - argparse prevents this
        raise MigrationToolError(f"Unknown command {args.command!r}")
    try:
        return await handler(args, progress)
    except StorageError:
        raise
    except MigrationToolError as exc:
        print(f"ERROR {redact(str(exc))}", file=sys.stderr)
        return 1
