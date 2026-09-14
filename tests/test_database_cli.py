"""Unit tests for `python -m database` CLI behavior that needs no database."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from database.__main__ import main as cli_main


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


if __name__ == "__main__":
    unittest.main()
