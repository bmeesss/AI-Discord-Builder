"""Migration runner tests: versioning, checksums, idempotency, failures."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database.errors import MigrationError
from database.postgres.migrator import (
    Migrator,
    checksum_sql,
    load_migrations,
)
from tests.fakes import FakeConnection, FakePool


def make_migrations_dir(contents: dict[str, str]) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="migrations-"))
    for filename, sql in contents.items():
        (directory / filename).write_text(sql, encoding="utf-8")
    return directory


class LoadMigrationsTests(unittest.TestCase):
    def test_discovers_and_sorts_by_numeric_version(self):
        directory = make_migrations_dir(
            {
                "010_later.sql": "select 1;",
                "002_second.sql": "select 2;",
                "001_first.sql": "select 3;",
            }
        )
        migrations = load_migrations(directory)
        self.assertEqual(
            [m.version for m in migrations],
            ["001", "002", "010"],
        )
        self.assertEqual(migrations[0].name, "first")

    def test_invalid_filename_raises(self):
        directory = make_migrations_dir({"oops.sql": "select 1;"})
        with self.assertRaises(MigrationError):
            load_migrations(directory)

    def test_duplicate_versions_raise(self):
        directory = make_migrations_dir(
            {
                "001_a.sql": "select 1;",
                "001_b.sql": "select 2;",
            }
        )
        with self.assertRaises(MigrationError):
            load_migrations(directory)

    def test_checksum_is_stable_sha256(self):
        self.assertEqual(
            checksum_sql("select 1;"),
            checksum_sql("select 1;"),
        )
        self.assertNotEqual(
            checksum_sql("select 1;"),
            checksum_sql("select 2;"),
        )

    def test_missing_directory_raises(self):
        with self.assertRaises(MigrationError):
            load_migrations("/nonexistent/migrations")


class _AppliedTracker:
    """Connection fake that behaves like schema_migrations exists."""

    def __init__(self) -> None:
        self.table_rows: list[dict] = []
        self.conn = _TrackingConnection(self)
        self.pool = FakePool(self.conn)


class _TrackingConnection(FakeConnection):
    def __init__(self, tracker: _AppliedTracker) -> None:
        super().__init__()
        self.tracker = tracker

    async def fetch(self, sql, *params):
        self.fetched.append((sql, params))
        if "from schema_migrations" in sql:
            return list(self.tracker.table_rows)
        return []

    async def execute(self, sql, *params):
        if self.fail_on_execute is not None and (
            self.fail_substring is None or self.fail_substring in sql
        ):
            raise self.fail_on_execute
        if "insert into schema_migrations" in sql:
            self.tracker.table_rows.append(
                {"version": params[0], "checksum": params[2]}
            )
        else:
            self.executed.append((sql, params))
        return "OK"


class MigratorTests(unittest.IsolatedAsyncioTestCase):
    def _setup(self, contents):
        directory = make_migrations_dir(contents)
        tracker = _AppliedTracker()
        migrator = Migrator(tracker.pool, directory=directory)
        return migrator, tracker

    async def test_migrate_applies_pending_once_in_transaction(self):
        migrator, tracker = self._setup(
            {
                "001_first.sql": "create table one (id int);",
                "002_second.sql": "create table two (id int);",
            }
        )

        applied = await migrator.migrate()
        self.assertEqual([m.version for m in applied], ["001", "002"])

        # Both migrations ran inside transactions.
        self.assertEqual(tracker.conn.transactions, 2)

        # Applied migrations are recorded with their checksum.
        rows = tracker.table_rows
        self.assertEqual([row["version"] for row in rows], ["001", "002"])

        # Idempotency: a second run applies nothing.
        applied_again = await migrator.migrate()
        self.assertEqual(applied_again, [])

    async def test_pending_skips_already_applied(self):
        migrator, tracker = self._setup(
            {
                "001_first.sql": "create table one (id int);",
                "002_second.sql": "create table two (id int);",
            }
        )
        tracker.table_rows.append(
            {"version": "001", "checksum": checksum_sql("create table one (id int);")}
        )

        pending = await migrator.pending_migrations()
        self.assertEqual([m.version for m in pending], ["002"])

    async def test_checksum_mismatch_fails_loudly(self):
        migrator, tracker = self._setup(
            {"001_first.sql": "create table changed (id int);"}
        )
        # The recorded checksum belongs to a different file content.
        tracker.table_rows.append({"version": "001", "checksum": "0" * 64})

        with self.assertRaises(MigrationError) as ctx:
            await migrator.migrate()
        self.assertIn("checksum", str(ctx.exception).lower())

    async def test_failed_migration_stops_and_reports(self):
        tracker = _AppliedTracker()
        # Only the migration file itself fails, not the bookkeeping table.
        tracker.conn.fail_on_execute = RuntimeError("boom")
        tracker.conn.fail_substring = "select 1;"

        directory = make_migrations_dir({"001_first.sql": "select 1;"})
        migrator = Migrator(tracker.pool, directory=directory)

        with self.assertRaises(MigrationError) as ctx:
            await migrator.migrate()
        self.assertIn("001_first", str(ctx.exception))

        # Nothing was recorded as applied.
        self.assertEqual(tracker.table_rows, [])

    async def test_status_reports_applied_and_pending(self):
        migrator, tracker = self._setup(
            {
                "001_first.sql": "create table one (id int);",
                "002_second.sql": "create table two (id int);",
            }
        )
        await migrator.migrate()

        status = await migrator.status()
        self.assertEqual(len(status["applied"]), 2)
        self.assertEqual(status["pending"], [])

        tracker.table_rows.pop()
        status = await migrator.status()
        self.assertEqual(len(status["applied"]), 1)
        self.assertEqual(
            [m["version"] for m in status["pending"]],
            ["002"],
        )


class MigrationLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_migration_run_holds_advisory_lock(self):
        tracker = _AppliedTracker()
        directory = make_migrations_dir({"001_first.sql": "select 1;"})
        migrator = Migrator(tracker.pool, directory=directory)

        await migrator.migrate()

        sql_statements = [sql for sql, _ in tracker.conn.executed]
        self.assertTrue(
            any("pg_advisory_lock" in sql for sql in sql_statements),
            "migrate() must take a PostgreSQL advisory lock",
        )
        self.assertTrue(
            any("pg_advisory_unlock" in sql for sql in sql_statements),
            "migrate() must release the advisory lock",
        )

    async def test_lock_released_after_failed_migration(self):
        tracker = _AppliedTracker()
        tracker.conn.fail_on_execute = RuntimeError("boom")
        tracker.conn.fail_substring = "select failing"

        directory = make_migrations_dir({"001_first.sql": "select failing;"})
        migrator = Migrator(tracker.pool, directory=directory)

        with self.assertRaises(MigrationError):
            await migrator.migrate()

        sql_statements = [sql for sql, _ in tracker.conn.executed]
        self.assertTrue(
            any("pg_advisory_unlock" in sql for sql in sql_statements),
            "the advisory lock must be released even after a failure",
        )


class RealMigrationsFileTests(unittest.TestCase):
    def test_repository_migrations_are_discoverable(self):
        """The shipped migration files are valid and ordered."""

        migrations = load_migrations()
        versions = [m.version for m in migrations]
        self.assertEqual(versions, ["001", "002"])
        self.assertIn("core_tables", migrations[0].name)


if __name__ == "__main__":
    unittest.main()
