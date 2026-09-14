"""Database CLI.

Usage:
    python -m database migrate   — apply pending PostgreSQL migrations
    python -m database status    — show backend, reachability and migrations

The CLI is intentionally independent of the Discord/AI configuration so it
also works for provisioning, Docker startup checks and CI.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import config
from database.connection import PostgresPool, mask_dsn
from database.errors import StorageError
from database.factory import resolve_backend
from database.postgres.migrator import Migrator


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
        for migration in applied:
            print(f"applied  {migration.version}_{migration.name}")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m database",
        description=__doc__,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply pending migrations")
    commands.add_parser("status", help="show backend and migration status")
    args = parser.parse_args(argv)

    try:
        backend = resolve_backend()
    except StorageError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
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

    try:
        return asyncio.run(runner(args))
    except StorageError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
