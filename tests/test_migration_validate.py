"""Export validator tests (``verify-export``) — all read-only."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from database.migration.manifest import file_sha256, load_manifest, write_json_atomic
from database.migration.model import IMPORT_ORDER
from database.migration.validate import ExportValidator
from tests.migration_fixtures import (
    CONVERSATION_ID,
    FEEDBACK_ID,
    GUILD_A,
    base_rows,
    empty_rows,
    make_export,
    missing_dependency_rows,
)

DISCORD_LOOKING_TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4.Gh7xYz.abcdefghijklmnopqrstuvwxyz012345"


class ValidatorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="migration-validate-"))

    def make_export(self, rows=None, name="export"):
        directory = self.tmp / name
        return make_export(directory, rows if rows is not None else base_rows())

    @staticmethod
    def rewrite_table(directory: Path, table: str, rows: list[dict]) -> None:
        """Replace one JSONL file and keep the manifest consistent."""

        path = directory / f"{table}.jsonl"
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        manifest = load_manifest(directory)
        manifest["tables"][table]["count"] = len(rows)
        manifest["tables"][table]["sha256"] = file_sha256(path)
        manifest["tables"][table]["bytes"] = path.stat().st_size
        manifest["totals"]["records"] = sum(
            entry["count"] for entry in manifest["tables"].values()
        )
        write_json_atomic(directory / "manifest.json", manifest)


class ValidExportTests(ValidatorTestCase):
    def test_clean_export_validates(self):
        directory, _client = self.make_export()
        report = ExportValidator(directory).validate()

        self.assertTrue(report.ok, [issue.format() for issue in report.issues])
        self.assertEqual(report.fatal, None)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.secret_scan.status, "clean")

    def test_empty_export_validates(self):
        directory, _client = self.make_export(rows=empty_rows())
        report = ExportValidator(directory).validate()
        self.assertTrue(report.ok)
        for name in IMPORT_ORDER:
            self.assertEqual(report.tables[name].actual_count, 0)

    def test_counts_match_the_manifest(self):
        directory, _client = self.make_export()
        report = ExportValidator(directory).validate()
        rows = base_rows()
        for name in IMPORT_ORDER:
            self.assertEqual(
                report.tables[name].actual_count, len(rows[name]), name
            )
            self.assertEqual(report.tables[name].checksum_ok, True, name)


class FileLevelTests(ValidatorTestCase):
    def test_invalid_json_is_reported(self):
        directory, _client = self.make_export()
        path = directory / "actions.jsonl"
        path.write_text(path.read_text(encoding="utf-8") + "{not json\n",
                        encoding="utf-8")

        report = ExportValidator(directory).validate()
        self.assertFalse(report.ok)
        self.assertIn(
            "json_syntax",
            [issue.kind for issue in report.errors],
        )

    def test_count_mismatch_is_reported(self):
        directory, _client = self.make_export()
        manifest = load_manifest(directory)
        manifest["tables"]["actions"]["count"] = 99
        manifest["totals"]["records"] += 96
        write_json_atomic(directory / "manifest.json", manifest)

        report = ExportValidator(directory).validate()
        self.assertIn(
            "count_mismatch", [issue.kind for issue in report.errors]
        )
        self.assertIn(
            "total_mismatch", [issue.kind for issue in report.errors]
        )

    def test_checksum_mismatch_is_reported(self):
        directory, _client = self.make_export()
        path = directory / "actions.jsonl"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

        report = ExportValidator(directory).validate()
        self.assertEqual(report.tables["actions"].checksum_ok, False)
        self.assertIn(
            "checksum_mismatch", [issue.kind for issue in report.errors]
        )

    def test_duplicate_primary_keys_are_reported(self):
        directory, _client = self.make_export()
        rows = base_rows()["conversations"]
        self.rewrite_table(directory, "conversations", rows + [rows[0]])

        report = ExportValidator(directory).validate()
        self.assertIn(
            "duplicate_id", [issue.kind for issue in report.errors]
        )
        self.assertEqual(report.tables["conversations"].duplicate_ids, 1)

    def test_missing_required_field_is_reported(self):
        directory, _client = self.make_export()
        rows = base_rows()["actions"]
        broken = [dict(row) for row in rows]
        broken[0].pop("guild_id")
        self.rewrite_table(directory, "actions", broken)

        report = ExportValidator(directory).validate()
        self.assertGreater(report.tables["actions"].invalid_rows, 0)
        self.assertIn("invalid_row", [issue.kind for issue in report.errors])

    def test_missing_column_is_reported(self):
        directory, _client = self.make_export()
        rows = [dict(row) for row in base_rows()["actions"]]
        for row in rows:
            row.pop("guild_id")
        self.rewrite_table(directory, "actions", rows)

        report = ExportValidator(directory).validate()
        kinds = [issue.kind for issue in report.errors]
        self.assertIn("missing_columns", kinds)

    def test_unknown_columns_are_a_warning(self):
        directory, _client = self.make_export()
        rows = [dict(row) for row in base_rows()["actions"]]
        for row in rows:
            row["legacy_flag"] = True
        self.rewrite_table(directory, "actions", rows)

        report = ExportValidator(directory).validate()
        self.assertTrue(report.ok)
        self.assertIn(
            "unknown_columns", [issue.kind for issue in report.warnings]
        )

    def test_manifest_missing_is_fatal(self):
        directory, _client = self.make_export()
        (directory / "manifest.json").unlink()

        report = ExportValidator(directory).validate()
        self.assertIsNotNone(report.fatal)
        self.assertIn("No manifest found", report.fatal)

    def test_unsupported_format_version_is_fatal(self):
        directory, _client = self.make_export()
        manifest = load_manifest(directory)
        manifest["format_version"] = "99.0"
        write_json_atomic(directory / "manifest.json", manifest)

        report = ExportValidator(directory).validate()
        self.assertIsNotNone(report.fatal)
        self.assertIn("unsupported format_version", report.fatal)

    def test_missing_path_is_fatal(self):
        report = ExportValidator(self.tmp / "does-not-exist").validate()
        self.assertIn("does not exist", report.fatal or "")

    def test_missing_table_file_is_reported(self):
        directory, _client = self.make_export()
        (directory / "memories.jsonl").unlink()

        report = ExportValidator(directory).validate()
        self.assertIn(
            "missing_file", [issue.kind for issue in report.errors]
        )


class RelationTests(ValidatorTestCase):
    def test_missing_foreign_key_parent_is_an_error(self):
        directory, _client = self.make_export(rows=missing_dependency_rows())
        report = ExportValidator(directory).validate()

        self.assertFalse(report.ok)
        kinds = [issue.kind for issue in report.errors]
        self.assertIn("missing_dependency", kinds)

    def test_missing_soft_reference_is_only_a_warning(self):
        directory, _client = self.make_export(rows=missing_dependency_rows())
        report = ExportValidator(directory).validate()

        warnings = [
            issue for issue in report.warnings if issue.kind == "soft_reference"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].table, "feedback")

    def test_valid_relations_produce_no_issues(self):
        directory, _client = self.make_export()
        report = ExportValidator(directory).validate()
        kinds = [issue.kind for issue in report.issues]
        self.assertNotIn("missing_dependency", kinds)
        self.assertNotIn("soft_reference", kinds)


class SecretScanTests(ValidatorTestCase):
    def test_critical_secret_is_an_error(self):
        directory, _client = self.make_export()
        rows = base_rows()["memories"]
        leaked = [dict(row) for row in rows]
        leaked[0]["memory_value"] = DISCORD_LOOKING_TOKEN
        self.rewrite_table(directory, "memories", leaked)

        report = ExportValidator(directory).validate()
        self.assertFalse(report.ok)
        self.assertIn("secret", [issue.kind for issue in report.errors])
        self.assertEqual(report.secret_scan.status, "failed")

    def test_suspicious_value_is_a_warning(self):
        directory, _client = self.make_export()
        rows = base_rows()["feedback"]
        suspicious = [dict(row) for row in rows]
        suspicious[0]["metadata"] = {"api_key": "abcd1234efgh5678"}
        self.rewrite_table(directory, "feedback", suspicious)

        report = ExportValidator(directory).validate()
        self.assertTrue(report.ok)
        self.assertIn("secret", [issue.kind for issue in report.warnings])
        self.assertEqual(report.secret_scan.status, "warnings")

    def test_failed_secret_scan_in_manifest_is_reported(self):
        directory, _client = self.make_export()
        manifest = load_manifest(directory)
        manifest["secret_scan"]["status"] = "failed"
        write_json_atomic(directory / "manifest.json", manifest)

        report = ExportValidator(directory).validate()
        self.assertFalse(report.ok)
        self.assertIn("secret_scan", [issue.kind for issue in report.errors])


class ReadOnlyTests(ValidatorTestCase):
    def test_validator_changes_nothing(self):
        directory, _client = self.make_export()
        before = {
            path.name: (path.stat().st_mtime_ns, path.read_bytes())
            for path in sorted(directory.iterdir())
        }

        ExportValidator(directory).validate()

        after = {
            path.name: (path.stat().st_mtime_ns, path.read_bytes())
            for path in sorted(directory.iterdir())
        }
        self.assertEqual(before, after)


class FailedExportStatusTests(ValidatorTestCase):
    def test_table_export_error_is_reported(self):
        directory, _client = self.make_export()
        manifest = load_manifest(directory)
        manifest["tables"]["memories"]["status"] = "error"
        manifest["tables"]["memories"]["error"] = "permission denied"
        write_json_atomic(directory / "manifest.json", manifest)

        report = ExportValidator(directory).validate()
        self.assertFalse(report.ok)
        self.assertIn("export_status", [issue.kind for issue in report.errors])


class FixtureCoverageTests(ValidatorTestCase):
    def test_fixtures_include_nulls_jsonb_and_long_strings(self):
        rows = base_rows()
        self.assertIsNone(rows["conversations"][1]["response"])
        self.assertIsInstance(rows["memories"][0]["confidence"], float)
        self.assertIsInstance(rows["memory_embeddings"][0]["embedding"], list)
        self.assertGreater(
            len(rows["conversation_summaries"][0]["summary"]), 1000
        )
        self.assertEqual(rows["feedback"][0]["conversation_id"], CONVERSATION_ID)
        self.assertEqual(rows["feedback"][0]["id"], FEEDBACK_ID)
        self.assertEqual(rows["actions"][0]["guild_id"], GUILD_A)


if __name__ == "__main__":
    unittest.main()
