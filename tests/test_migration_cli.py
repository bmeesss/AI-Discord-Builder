"""CLI tests: backend gating, credentials, error handling and masking."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import config
from database.__main__ import main as cli_main
from tests.migration_fakes import FakePg
from tests.migration_fixtures import (
    FakeSupabaseClient,
    base_rows,
    make_export,
)

DATABASE_URL = "postgresql://discord_builder:discord_builder@localhost:5432/db"
SUPABASE_URL = "https://example.supabase.co"


class CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="migration-cli-"))
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def run_cli(self, *argv: str) -> int:
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return cli_main(list(argv))

    @property
    def out(self) -> str:
        return self.stdout.getvalue()

    @property
    def err(self) -> str:
        return self.stderr.getvalue()


class BackendGatingTests(CliTestCase):
    def test_export_refuses_postgres_backend(self):
        with patch("database.migration.cli.resolve_backend",
                   return_value="postgres"):
            rc = self.run_cli("export-supabase", "--output",
                              str(self.tmp / "e"))
        self.assertEqual(rc, 1)
        self.assertIn("DATABASE_BACKEND=supabase", self.err)
        self.assertIn("Nothing was exported", self.err)

    def test_import_refuses_supabase_backend(self):
        directory, _client = make_export(self.tmp / "export", base_rows())
        with patch("database.migration.cli.resolve_backend",
                   return_value="supabase"):
            rc = self.run_cli("import-postgres", str(directory), "--yes")
        self.assertEqual(rc, 1)
        self.assertIn("DATABASE_BACKEND=postgres", self.err)
        self.assertIn("Nothing was imported", self.err)

    def test_export_reports_missing_supabase_credentials(self):
        with (
            patch("database.migration.cli.resolve_backend",
                  return_value="supabase"),
            patch.object(config, "SUPABASE_URL", None),
            patch.object(config, "SUPABASE_KEY", None),
        ):
            rc = self.run_cli("export-supabase", "--output",
                              str(self.tmp / "e"))
        self.assertEqual(rc, 1)
        self.assertIn("SUPABASE_URL", self.err)
        self.assertIn("SUPABASE_KEY", self.err)
        self.assertNotIn("Traceback", self.err)


class ExportCliTests(CliTestCase):
    def _run_export(self, *extra: str) -> int:
        rows = base_rows()
        client = FakeSupabaseClient(rows)
        with (
            patch("database.migration.cli.resolve_backend",
                  return_value="supabase"),
            patch.object(config, "SUPABASE_URL", SUPABASE_URL),
            patch.object(config, "SUPABASE_KEY", "service-role-key"),
            patch("database.migration.cli.create_supabase_client",
                  return_value=client),
        ):
            return self.run_cli(
                "export-supabase",
                "--output",
                str(self.tmp / "export"),
                *extra,
            )

    def test_export_writes_an_export_and_reports_success(self):
        rc = self._run_export()
        self.assertEqual(rc, 0, self.err)
        self.assertIn("Export directory", self.out)
        self.assertIn("Records exported: 14", self.out)
        self.assertIn("verify-export", self.out)
        self.assertTrue((self.tmp / "export" / "manifest.json").is_file())

    def test_export_refuses_a_non_empty_output_directory(self):
        directory = self.tmp / "export"
        directory.mkdir(parents=True)
        (directory / "existing.txt").write_text("keep me", encoding="utf-8")

        rc = self._run_export()
        self.assertEqual(rc, 1)
        self.assertIn("non-empty directory", self.err)

    def test_export_rejects_unknown_tables(self):
        rc = self._run_export("--tables", "actions,not_a_table")
        self.assertEqual(rc, 1)
        self.assertIn("Unknown table", self.err)

    def test_export_leak_is_not_declared_successful(self):
        rows = base_rows()
        rows["memories"][0]["memory_value"] = (
            "MTIzNDU2Nzg5MDEyMzQ1Njc4.Gh7xYz.abcdefghijklmnopqrstuvwxyz012345"
        )
        client = FakeSupabaseClient(rows)
        with (
            patch("database.migration.cli.resolve_backend",
                  return_value="supabase"),
            patch.object(config, "SUPABASE_URL", SUPABASE_URL),
            patch.object(config, "SUPABASE_KEY", "service-role-key"),
            patch("database.migration.cli.create_supabase_client",
                  return_value=client),
        ):
            rc = self.run_cli("export-supabase", "--output",
                              str(self.tmp / "leak"))
        self.assertEqual(rc, 1)
        self.assertIn("secret", self.out.lower() + self.err.lower())


class VerifyCliTests(CliTestCase):
    def test_verify_reports_success(self):
        directory, _client = make_export(self.tmp / "export", base_rows())
        rc = self.run_cli("verify-export", str(directory))
        self.assertEqual(rc, 0, self.err)
        self.assertIn("VERIFY OK", self.out)
        self.assertIn("Secret scan: clean", self.out)

    def test_verify_reports_missing_path(self):
        rc = self.run_cli("verify-export", str(self.tmp / "nope"))
        self.assertEqual(rc, 1)
        self.assertIn("does not exist", self.err)
        self.assertNotIn("Traceback", self.err)

    def test_verify_reports_corrupt_jsonl(self):
        directory, _client = make_export(self.tmp / "export", base_rows())
        path = directory / "actions.jsonl"
        path.write_text(path.read_text(encoding="utf-8") + "{oops\n",
                        encoding="utf-8")

        rc = self.run_cli("verify-export", str(directory))
        self.assertEqual(rc, 1)
        self.assertIn("VERIFY FAILED", self.err)
        self.assertIn("json_syntax", self.out)
        self.assertNotIn("Traceback", self.err)

    def test_verify_reports_missing_manifest(self):
        directory, _client = make_export(self.tmp / "export", base_rows())
        (directory / "manifest.json").unlink()

        rc = self.run_cli("verify-export", str(directory))
        self.assertEqual(rc, 1)
        self.assertIn("No manifest found", self.err)

    def test_verify_changes_nothing(self):
        directory, _client = make_export(self.tmp / "export", base_rows())
        before = {
            path.name: path.read_bytes() for path in sorted(directory.iterdir())
        }
        self.run_cli("verify-export", str(directory))
        after = {
            path.name: path.read_bytes() for path in sorted(directory.iterdir())
        }
        self.assertEqual(before, after)


class ImportCliTests(CliTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = FakePg()
        self.directory, _client = make_export(
            self.tmp / "export", base_rows()
        )

    def _run_import(self, *extra: str, db: FakePg | None = None) -> int:
        database = db or self.db
        pool = database.pool()
        with (
            patch("database.migration.cli.resolve_backend",
                  return_value="postgres"),
            patch.object(config, "DATABASE_URL", DATABASE_URL),
            patch("database.connection.PostgresPool", lambda *a, **kw: pool),
        ):
            return self.run_cli("import-postgres", str(self.directory), *extra)

    def test_dry_run_writes_nothing_and_reports(self):
        rc = self._run_import("--dry-run")
        self.assertEqual(rc, 0, self.err)
        self.assertIn("DRY RUN", self.out)
        self.assertIn("Dry run complete: nothing was written.", self.out)
        self.assertEqual(len(self.db.tables["actions"]), 0)
        self.assertEqual(self.db.connection.executemany_calls, [])

    def test_import_without_yes_is_cancelled_when_not_interactive(self):
        rc = self._run_import()
        self.assertEqual(rc, 1)
        self.assertIn("cancelled", self.out + self.err)
        self.assertEqual(len(self.db.tables["actions"]), 0)

    def test_import_with_yes_imports_everything(self):
        rc = self._run_import("--yes")
        self.assertEqual(rc, 0, self.err)
        self.assertIn("IMPORT OK", self.out)
        self.assertIn("inserted=14", self.out)
        self.assertEqual(len(self.db.tables["actions"]), 3)

    def test_import_reports_missing_export_path(self):
        with (
            patch("database.migration.cli.resolve_backend",
                  return_value="postgres"),
            patch.object(config, "DATABASE_URL", DATABASE_URL),
            patch("database.connection.PostgresPool",
                  lambda *a, **kw: self.db.pool()),
        ):
            rc = self.run_cli("import-postgres", str(self.tmp / "nope"),
                              "--yes")
        self.assertEqual(rc, 1)
        self.assertIn("does not exist", self.err)
        self.assertNotIn("Traceback", self.err)

    def test_import_reports_pending_migrations(self):
        db = FakePg(applied_migrations=False)
        rc = self._run_import("--yes", db=db)
        self.assertEqual(rc, 1)
        self.assertIn("pending migrations", self.err)
        self.assertEqual(len(db.tables["actions"]), 0)

    def test_import_reports_unreachable_postgres(self):
        class BrokenPool:
            async def ping(self):
                raise OSError("connection refused")

            async def pool(self):
                raise OSError("connection refused")

            async def close(self):
                return None

        with (
            patch("database.migration.cli.resolve_backend",
                  return_value="postgres"),
            patch.object(config, "DATABASE_URL", DATABASE_URL),
            patch("database.connection.PostgresPool",
                  lambda *a, **kw: BrokenPool()),
        ):
            rc = self.run_cli("import-postgres", str(self.directory), "--yes")
        self.assertEqual(rc, 1)
        self.assertIn("connection refused", self.err)
        self.assertNotIn("Traceback", self.err)

    def test_import_masks_dsn_credentials_in_errors(self):
        class LeakyPool:
            async def ping(self):
                raise RuntimeError(
                    "failed for postgresql://user:hunter2@db:5432/prod"
                )

            async def pool(self):
                raise RuntimeError(
                    "failed for postgresql://user:hunter2@db:5432/prod"
                )

            async def close(self):
                return None

        with (
            patch("database.migration.cli.resolve_backend",
                  return_value="postgres"),
            patch.object(config, "DATABASE_URL", DATABASE_URL),
            patch("database.connection.PostgresPool",
                  lambda *a, **kw: LeakyPool()),
        ):
            rc = self.run_cli("import-postgres", str(self.directory), "--yes")
        self.assertEqual(rc, 1)
        self.assertNotIn("hunter2", self.err)
        self.assertIn("***", self.err)

    def test_verification_runs_after_a_real_import(self):
        rc = self._run_import("--yes")
        self.assertEqual(rc, 0, self.err)
        self.assertIn("Verification:", self.out)

    def test_no_traceback_for_normal_errors(self):
        self._run_import("--yes", db=FakePg(applied_migrations=False))
        self.assertNotIn("Traceback", self.err)
        self.assertNotIn("File \"", self.err)


class ManifestSafetyTests(CliTestCase):
    def test_manifest_never_contains_environment_secrets(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "DISCORD_TOKEN": "discord-token-value",
                    "GROQ_API_KEY": "gsk_abcdefghijklmnopqrstuvwxyz",
                    "OPENAI_API_KEY": "sk-abcdefghijklmnop",
                    "SUPABASE_KEY": "service-role-secret",
                    "POSTGRES_PASSWORD": "db-password",
                },
            ),
            patch("database.migration.cli.resolve_backend",
                  return_value="supabase"),
            patch.object(config, "SUPABASE_URL", SUPABASE_URL),
            patch.object(config, "SUPABASE_KEY", "service-role-secret"),
            patch("database.migration.cli.create_supabase_client",
                  return_value=FakeSupabaseClient(base_rows())),
        ):
            rc = self.run_cli("export-supabase", "--output",
                              str(self.tmp / "safe"))
        self.assertEqual(rc, 0, self.err)
        text = (self.tmp / "safe" / "manifest.json").read_text(encoding="utf-8")
        for secret in (
            "discord-token-value",
            "gsk_abcdefghijklmnopqrstuvwxyz",
            "sk-abcdefghijklmnop",
            "service-role-secret",
            "db-password",
        ):
            self.assertNotIn(secret, text)
            self.assertNotIn(secret, self.out)

        manifest = json.loads(text)
        self.assertEqual(manifest["source"]["url_host"], "example.supabase.co")


if __name__ == "__main__":
    unittest.main()
