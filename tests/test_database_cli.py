"""Unit tests for `python -m database` CLI behavior that needs no database."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from urllib.parse import urlparse

import config
from database.__main__ import main as cli_main
from database.postgres.migrator import load_migrations
from tests.fakes import FakeConnection, FakePool


class SupabaseCliTests(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            patch(
                "database.__main__.resolve_backend",
                return_value="supabase",
            ),
        ):
            rc = cli_main(list(argv))
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_status_with_supabase_backend_is_informational(self):
        rc, out, _err = self.run_cli("status")
        self.assertEqual(rc, 0)
        self.assertIn("supabase", out)
        self.assertIn("database/migrations", out)

    def test_migrate_is_postgres_only(self):
        rc, _out, err = self.run_cli("migrate")
        self.assertEqual(rc, 1)
        self.assertIn("PostgreSQL", err)

    def test_invalid_backend_config_is_a_clear_error(self):
        with patch(
            "database.__main__.resolve_backend",
            side_effect=__import__(
                "database.errors", fromlist=["StorageNotConfiguredError"]
            ).StorageNotConfiguredError("Unknown DATABASE_BACKEND='mysql'."),
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                rc = cli_main(["status"])
        self.assertEqual(rc, 1)
        self.assertIn("DATABASE_BACKEND", stderr.getvalue())


class _FakeCliPool(FakePool):
    """FakePool plus the lifecycle calls the `status` command makes."""

    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 2) -> None:
        # Pretend the shipped migrations are already applied: the CLI then sees
        # a clean schema (rc 0) without touching a real database.
        applied = [
            {"version": migration.version, "checksum": migration.checksum}
            for migration in load_migrations()
        ]
        super().__init__(FakeConnection(rows=applied))
        # Mirrors database.connection.PostgresPool's constructor.
        self.dsn = dsn

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class PostgresCliDsnMaskingTests(unittest.TestCase):
    """Regression: `status` must never print raw DSN credentials.

    CI (and .env.example) configure the same value for user, password and
    database — ``discord_builder``.  The masked DSN therefore still contains
    that value as the username and database name, which used to trip a naive
    "the password must not appear anywhere in the output" assertion.  That was
    a false failure, not a leak; the invariant that actually matters is that
    the ``user:password@host`` authority is redacted.
    """

    DSN = (
        "postgresql://discord_builder:discord_builder"
        "@localhost:5432/discord_builder"
    )

    def run_status(self) -> tuple[int, str]:
        stdout = io.StringIO()
        with (
            patch.object(config, "DATABASE_URL", self.DSN),
            patch("database.__main__.resolve_backend", return_value="postgres"),
            patch("database.__main__.PostgresPool", _FakeCliPool),
            redirect_stdout(stdout),
        ):
            rc = cli_main(["status"])
        return rc, stdout.getvalue()

    def test_status_masks_password_that_equals_user_and_database(self):
        rc, out = self.run_status()
        self.assertEqual(rc, 0, out)

        dsn_line = next(
            line for line in out.splitlines() if line.strip().startswith("dsn:")
        )
        printed = urlparse(dsn_line.split(":", 1)[1].strip())
        self.assertEqual(printed.password, "***")
        self.assertEqual(printed.username, "discord_builder")
        self.assertEqual(printed.path, "/discord_builder")
        self.assertEqual(printed.hostname, "localhost")

        # No raw 'user:password@host' authority may reach stdout.
        self.assertNotIn(":discord_builder@", out)


if __name__ == "__main__":
    unittest.main()
