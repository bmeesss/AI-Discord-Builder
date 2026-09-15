"""Exporter tests: pagination, manifest, checksums and secret filtering."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from database.migration.manifest import file_sha256, load_manifest
from database.migration.model import IMPORT_ORDER
from database.postgres.migrator import load_migrations
from tests.migration_fixtures import (
    GUILD_A,
    FakeSupabaseClient,
    base_rows,
    empty_rows,
    large_rows,
    make_export,
)

DISCORD_LOOKING_TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4.Gh7xYz.abcdefghijklmnopqrstuvwxyz012345"


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="migration-export-"))

    def test_export_writes_every_table_and_the_manifest(self):
        directory, _client = make_export(self.tmp / "export", base_rows())

        for name in IMPORT_ORDER:
            self.assertTrue((directory / f"{name}.jsonl").is_file(), name)
        self.assertTrue((directory / "manifest.json").is_file())

        manifest = load_manifest(directory)
        self.assertEqual(manifest["format_version"], "1.0")
        self.assertEqual(manifest["totals"]["failed_tables"], 0)

        rows = base_rows()
        for name in IMPORT_ORDER:
            entry = manifest["tables"][name]
            self.assertEqual(entry["file"], f"{name}.jsonl")
            self.assertEqual(entry["count"], len(rows[name]), name)
            self.assertEqual(entry["status"], "ok", name)
            written = [
                json.loads(line)
                for line in (directory / f"{name}.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            self.assertEqual(len(written), len(rows[name]), name)

    def test_manifest_checksums_match_the_files(self):
        directory, _client = make_export(self.tmp / "export", base_rows())
        manifest = load_manifest(directory)

        for name in IMPORT_ORDER:
            entry = manifest["tables"][name]
            self.assertEqual(
                file_sha256(directory / entry["file"]),
                entry["sha256"],
                name,
            )
            self.assertEqual(
                (directory / entry["file"]).stat().st_size,
                entry["bytes"],
                name,
            )

    def test_manifest_records_schema_and_source_information(self):
        directory, _client = make_export(self.tmp / "export", base_rows())
        manifest = load_manifest(directory)

        expected = {
            migration.version: migration.checksum
            for migration in load_migrations()
        }
        recorded = {
            entry["version"]: entry["checksum"]
            for entry in manifest["schema"]["migrations"]
        }
        self.assertEqual(recorded, expected)
        self.assertEqual(manifest["schema"]["target_backend"], "postgres")
        self.assertEqual(manifest["source"]["backend"], "supabase")
        self.assertEqual(
            manifest["source"]["url_host"], "example.supabase.co"
        )
        self.assertIn("generated_at", manifest)
        self.assertEqual(manifest["secret_scan"]["status"], "clean")

    def test_manifest_documents_import_order_and_conflict_policy(self):
        directory, _client = make_export(self.tmp / "export", base_rows())
        manifest = load_manifest(directory)

        self.assertEqual(manifest["import"]["order"], list(IMPORT_ORDER))
        policy = manifest["import"]["conflict_policy"]
        self.assertEqual(policy["prompt_versions"]["conflict_key"],
                         ["name", "version"])
        self.assertEqual(policy["actions"]["id_policy"], "regenerate")
        self.assertEqual(policy["conversations"]["conflict_key"], ["id"])

    def test_empty_tables_produce_empty_files(self):
        directory, _client = make_export(self.tmp / "empty", empty_rows())
        manifest = load_manifest(directory)

        for name in IMPORT_ORDER:
            entry = manifest["tables"][name]
            self.assertEqual(entry["count"], 0, name)
            self.assertEqual(entry["status"], "ok", name)
            self.assertEqual((directory / f"{name}.jsonl").read_text(), "")


class PaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="migration-pages-"))

    def test_export_reads_every_page_not_just_the_first(self):
        rows = large_rows(count=2500)
        directory, client = make_export(
            self.tmp / "big", rows, page_size=500
        )

        manifest = load_manifest(directory)
        self.assertEqual(manifest["tables"]["actions"]["count"], 2500)
        self.assertEqual(manifest["tables"]["actions"]["pages"], 5)
        self.assertEqual(manifest["tables"]["memories"]["count"], 2500)

        # One range() request per page.  A final empty request proves the
        # exporter does not stop at the first full page: 2500 rows with a page
        # size of 500 needs 5 data pages plus one probe that returns nothing.
        requests = client.page_requests("actions")
        self.assertEqual([request.start for request in requests],
                         [0, 500, 1000, 1500, 2000, 2500])
        self.assertEqual([request.end for request in requests],
                         [499, 999, 1499, 1999, 2499, 2999])

    def test_all_rows_are_exported_exactly_once(self):
        rows = large_rows(count=1234)
        directory, _client = make_export(self.tmp / "big", rows, page_size=250)

        written = [
            json.loads(line)["id"]
            for line in (directory / "actions.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertEqual(len(written), 1234)
        self.assertEqual(len(set(written)), 1234)
        self.assertEqual(set(written), {row["id"] for row in rows["actions"]})

    def test_pagination_uses_a_total_order(self):
        _directory, client = make_export(
            self.tmp / "ordered", base_rows(), page_size=1
        )
        request = client.page_requests("actions")[0]
        self.assertEqual(
            [column for column, _desc in request.orders],
            ["created_at", "id"],
        )

    def test_page_size_is_clamped_to_the_postgrest_limit(self):
        rows = large_rows(count=1600)
        directory, client = make_export(
            self.tmp / "clamped", rows, page_size=100_000
        )
        # Clamped to the hard PostgREST limit of 1000 rows per request.
        requests = client.page_requests("actions")
        self.assertEqual([request.end for request in requests], [999, 1999])
        self.assertEqual(
            load_manifest(directory)["tables"]["actions"]["count"], 1600
        )

    def test_missing_order_column_falls_back_to_unordered_paging(self):
        rows = large_rows(count=1200)
        client = FakeSupabaseClient(rows)
        client.tables["actions"].missing_columns.add("created_at")

        directory, client = make_export(
            self.tmp / "fallback",
            rows,
            page_size=500,
            client=client,
        )
        manifest = load_manifest(directory)
        self.assertEqual(manifest["tables"]["actions"]["count"], 1200)
        self.assertEqual(manifest["tables"]["actions"]["ordering"], [])


class SecretSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="migration-secrets-"))

    def test_configured_secret_value_is_detected(self):
        rows = base_rows()
        rows["memories"][0]["memory_value"] = "token is " + DISCORD_LOOKING_TOKEN
        directory, _client = make_export(self.tmp / "leak", rows)

        manifest = load_manifest(directory)
        self.assertEqual(manifest["secret_scan"]["status"], "failed")
        self.assertGreater(manifest["secret_scan"]["critical_count"], 0)

    def test_discord_token_pattern_is_critical(self):
        rows = base_rows()
        rows["feedback"][0]["comment"] = DISCORD_LOOKING_TOKEN
        _directory, _client = make_export(self.tmp / "leak2", rows)
        manifest = load_manifest(self.tmp / "leak2")
        self.assertEqual(manifest["secret_scan"]["status"], "failed")

    def test_sensitive_key_name_is_a_warning_not_a_failure(self):
        rows = base_rows()
        rows["feedback"][0]["metadata"] = {"api_key": "abcd1234efgh5678"}
        directory, _client = make_export(self.tmp / "suspicious", rows)

        manifest = load_manifest(directory)
        self.assertEqual(manifest["secret_scan"]["status"], "warnings")
        self.assertGreater(manifest["secret_scan"]["suspicious_count"], 0)

    def test_manifest_never_contains_the_supabase_key(self):
        rows = base_rows()
        directory, _client = make_export(self.tmp / "safe", rows)
        text = (directory / "manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(text)

        self.assertNotIn("SUPABASE_KEY", text)
        self.assertNotIn("service_role", text)
        self.assertEqual(manifest["source"]["url_host"], "example.supabase.co")

    def test_clean_export_has_no_findings(self):
        directory, _client = make_export(self.tmp / "clean", base_rows())
        manifest = load_manifest(directory)
        self.assertEqual(manifest["secret_scan"]["findings"], [])


class ExportFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="migration-fail-"))

    def test_missing_table_is_reported_without_hiding_other_tables(self):
        rows = base_rows()
        client = FakeSupabaseClient(rows)
        client.tables["memories"].error = RuntimeError(
            'relation "public.memories" does not exist'
        )

        directory, _client = make_export(
            self.tmp / "partial", rows, client=client
        )
        manifest = load_manifest(directory)

        self.assertEqual(manifest["tables"]["memories"]["status"], "error")
        self.assertIn("does not exist", manifest["tables"]["memories"]["error"])
        self.assertEqual(manifest["tables"]["actions"]["status"], "ok")
        self.assertEqual(manifest["totals"]["failed_tables"], 1)

    def test_progress_messages_are_emitted(self):
        messages: list[str] = []
        rows = base_rows()
        client = FakeSupabaseClient(rows)

        from database.migration.export import ExportOptions, SupabaseExporter

        options = ExportOptions(
            output_dir=self.tmp / "progress",
            page_size=1,
            progress=messages.append,
        )
        SupabaseExporter(client, options).export()

        self.assertTrue(any("actions" in message for message in messages))
        self.assertTrue(
            any("Manifest written" in message for message in messages)
        )


class GuildIsolationFixtureTests(unittest.TestCase):
    def test_fixtures_cover_multiple_guilds_and_nulls(self):
        rows = base_rows()
        guilds = {row["guild_id"] for row in rows["actions"]}
        self.assertEqual(guilds, {GUILD_A, "1000000000000000002"})
        self.assertIsNone(rows["conversations"][1]["user_id"])
        self.assertIsInstance(rows["conversations"][0]["ai_plan"], dict)
        self.assertGreater(len(rows["conversation_summaries"][0]["summary"]),
                           1000)


if __name__ == "__main__":
    unittest.main()
