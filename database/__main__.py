"""Database CLI.

Usage:
    python -m database migrate             — apply pending PostgreSQL migrations
    python -m database status              — show backend, reachability and migrations
    python -m database export-supabase     — snapshot Supabase data to disk (read-only)
    python -m database verify-export PATH  — validate an export (read-only)
    python -m database import-postgres PATH
                                           — import an export into PostgreSQL

The CLI is intentionally independent of the Discord/AI configuration so it
also works for provisioning, Docker startup checks and CI.  Credentials are
never printed: DSNs are masked and every error message is redacted.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import traceback

import config
from database import migration
from database.connection import PostgresPool, mask_dsn
from database.errors import (
    MigrationToolError,
    StorageError,
)
from database.factory import resolve_backend
from database.migration.secrets import redact
from database.postgres.migrator import Migrator

MIGRATION_COMMANDS = frozenset(
    {"export-supabase", "verify-export", "import-postgres"}
)


def _build_migrator() -> tuple[Migrator, PostgresPool]:
    pool = PostgresPool(
        config.DATABASE_URL or "",
        min_size=1,
        max_size=2,
    )
    return Migrator(pool), pool


async def _run_migrate(args: argparse.Namespace) -> int:
    migrator, pool = _build_migrator()
    try:
        applied = await migrator.migrate()
    finally:
        await pool.close()

    if applied:
        for migration_file in applied:
            print(f"applied  {migration_file.version}_{migration_file.name}")
        print(f"OK: {len(applied)} migration(s) applied.")
    else:
        print("OK: schema is up to date; no pending migrations.")
    return 0


async def _run_status(args: argparse.Namespace) -> int:
    backend = resolve_backend()
    print(f"backend: {backend}")

    if backend != "postgres":
        print(
            "Migrations are managed by your Supabase project "
            "(see database/migrations/ for the SQL to run there)."
        )
        return 0

    print(f"dsn:     {mask_dsn(config.DATABASE_URL or '')}")

    migrator, pool = _build_migrator()
    try:
        await pool.ping()
        print("connection: ok")

        status = await migrator.status()
    finally:
        await pool.close()

    print("applied migrations:")
    for entry in status["applied"]:
        print(f"  {entry['version']} (sha256 {entry['checksum'][:12]}…)")
    print("pending migrations:")
    for entry in status["pending"]:
        print(f"  {entry['version']}_{entry['name']}")
    if not status["pending"]:
        print("  none")

    return 1 if status["pending"] else 0


async def _run_migration_command(args: argparse.Namespace) -> int:
    """Dispatch export/verify/import (each checks its own backend)."""

    def progress(message: str) -> None:
        print(message, flush=True)

    return await migration.cli.dispatch(args, progress)


def _debug_enabled(args: argparse.Namespace) -> bool:
    if getattr(args, "debug", False):
        return True
    return (config.LOG_LEVEL or "").strip().upper() == "DEBUG"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m database",
        description=__doc__,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="show full tracebacks (or set LOG_LEVEL=DEBUG)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply pending migrations")
    commands.add_parser("status", help="show backend and migration status")
    migration.cli.register_commands(commands)
    args = parser.parse_args(argv)

    if args.command in MIGRATION_COMMANDS:
        return _run(args, _run_migration_command)

    try:
        backend = resolve_backend()
    except StorageError as exc:
        print(f"Configuration error: {redact(str(exc))}", file=sys.stderr)
        return 1

    if args.command == "migrate" and backend != "postgres":
        print(
            f"'migrate' only applies to the PostgreSQL backend; the active "
            f"backend is {backend!r}. Manage schema via your Supabase "
            f"project instead.",
            file=sys.stderr,
        )
        return 1

    runner = {
        "migrate": _run_migrate,
        "status": _run_status,
    }[args.command]

    return _run(args, runner)


def _run(args: argparse.Namespace, runner) -> int:
    try:
        return asyncio.run(runner(args))
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("Interrupted.", file=sys.stderr)
        return 130
    except (StorageError, MigrationToolError) as exc:
        print(f"{_label(exc)} {redact(str(exc))}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - users get a message, not a trace
        if _debug_enabled(args):
            traceback.print_exc()
        print(f"Unexpected error: {redact(str(exc))}", file=sys.stderr)
        return 1


def _label(exc: Exception) -> str:
    if isinstance(exc, MigrationToolError):
        return "Migration error:"
    if isinstance(exc, StorageError):
        return "Database error:"
    return "Error:"


if __name__ == "__main__":
    raise SystemExit(main())
