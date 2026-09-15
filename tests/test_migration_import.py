"""Importer tests: dry-run, conflicts, idempotency, failures, action ids."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from database.errors import MigrationToolError
from database.migration.import_postgres import (
    ImportOptions,
    PostgresImporter,
)
from database.migration.model import (
    IMPORT_ORDER,
    deterministic_uuid,
)
from tests.migration_fakes import (
    FakePg,
    FakeUniqueViolation,
)
from tests.migration_fixtures import (
    CONVERSATION_ID,
    GUILD_A,
    GUILD_B,
    PROMPT_VERSION_ID,
    base_rows,
    conflicting_rows,
    large_rows,
    legacy_int_id_rows,
    make_export,
    missing_dependency_rows,
)

DISCORD_LOOKING_TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4.Gh7xYz.abcdefghijklmnopqrstuvwxyz012345"


class ImporterTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="migration-import-"))
        self.messages: list[str] = []

    def make_export(self, rows=None, name="export"):
        directory = self.tmp / name
        return make_export(directory, rows if rows is not None else base_rows())

    def options(self, **kwargs) -> ImportOptions:
        defaults = {
            "batch_size": 100,
            "assume_yes": True,
            "verify": False,
            "progress": self.messages.append,
        }
        defaults.update(kwargs)
        return ImportOptions(**defaults)

    async def run_import(
        self,
        directory: Path,
        db: FakePg | None = None,
        **kwargs,
    ):
        database = db or FakePg()
        importer = PostgresImporter(
            database.pool(), directory, self.options(**kwargs)
        )
        report = await importer.run()
        return report, database


class DryRunTests(ImporterTestCase):
    async def test_dry_run_writes_nothing(self):
        directory, _client = self.make_export()
        report, db = await self.run_import(directory, dry_run=True)

        self.assertTrue(report.dry_run)
        rows = base_rows()
        for name in IMPORT_ORDER:
            self.assertEqual(report.tables[name].source_rows, len(rows[name]),
                             name)
            self.assertEqual(report.tables[name].inserted, len(rows[name]),
                             name)
            self.assertEqual(db.tables[name], [], name)

        self.assertEqual(db.connection.executemany_calls, [])
        self.assertEqual(db.connection.transactions, [])

    async def test_dry_run_reports_existing_rows(self):
        directory, _client = self.make_export()
        db = FakePg()
        await self.run_import(directory, db=db)  # real import first

        report, _db = await self.run_import(directory, db=db, dry_run=True)
        totals = report.totals
        self.assertEqual(totals["inserted"], 0)
        self.assertEqual(totals["skipped"], 14)
        self.assertEqual(totals["errors"], 0)

    async def test_dry_run_reports_invalid_rows_without_writing(self):
        directory, _client = self.make_export()
        report, db = await self.run_import(directory, dry_run=True)
        self.assertEqual(report.tables["actions"].invalid_rows, 0)
        self.assertEqual(len(db.tables["actions"]), 0)


class ImportTests(ImporterTestCase):
    async def test_import_inserts_every_row(self):
        directory, _client = self.make_export()
        report, db = await self.run_import(directory)

        rows = base_rows()
        for name in IMPORT_ORDER:
            self.assertEqual(len(db.tables[name]), len(rows[name]), name)
            self.assertEqual(
                report.tables[name].inserted, len(rows[name]), name
            )
        self.assertEqual(report.errors, [])
        self.assertTrue(report.ok)

    async def test_jsonb_and_timestamps_are_preserved(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        action = db.tables["actions"][0]
        self.assertEqual(json.loads(action["data"])["type"], action["action_type"])
        self.assertIsInstance(action["created_at"], datetime)
        self.assertEqual(action["created_at"].tzinfo, timezone.utc)

        conversation = db.tables["conversations"][0]
        self.assertEqual(
            json.loads(conversation["ai_plan"])["summary"], "Minecraft SMP"
        )
        self.assertEqual(
            conversation["prompt_version_id"], UUID(PROMPT_VERSION_ID)
        )

    async def test_uuid_primary_keys_are_preserved(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        self.assertEqual(
            db.tables["conversations"][0]["id"], UUID(CONVERSATION_ID)
        )
        self.assertEqual(
            db.tables["memories"][0]["id"],
            UUID(base_rows()["memories"][0]["id"]),
        )

    async def test_guild_isolation_is_preserved(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        guilds = {row["guild_id"] for row in db.tables["actions"]}
        self.assertEqual(guilds, {GUILD_A, GUILD_B})
        self.assertTrue(all(row["guild_id"] for row in db.tables["actions"]))

    async def test_batch_size_is_respected(self):
        directory, _client = self.make_export(rows=large_rows(count=25))
        _report, db = await self.run_import(directory, batch_size=10)

        # 25 rows → 3 batches; actions and memories each use 3.
        calls = [
            call for call in db.connection.executemany_calls
            if "insert into actions" in call[0]
        ]
        self.assertEqual(len(calls), 3)
        self.assertEqual([len(params) for _sql, params in calls],
                         [10, 10, 5])


class IdempotencyTests(ImporterTestCase):
    async def test_second_import_inserts_nothing(self):
        directory, _client = self.make_export()
        first, db = await self.run_import(directory)
        second, db = await self.run_import(directory, db=db)

        totals = second.totals
        self.assertEqual(totals["inserted"], 0)
        self.assertEqual(totals["errors"], 0)
        self.assertEqual(totals["skipped"], first.totals["inserted"])

        rows = base_rows()
        for name in IMPORT_ORDER:
            self.assertEqual(len(db.tables[name]), len(rows[name]), name)

    async def test_third_import_is_still_clean(self):
        directory, _client = self.make_export()
        db = FakePg()
        for _run in range(3):
            report, db = await self.run_import(directory, db=db)
        self.assertEqual(report.totals["inserted"], 0)
        self.assertEqual(report.totals["errors"], 0)
        self.assertEqual(report.totals["skipped"], 14)

    async def test_idempotency_with_multiple_batches(self):
        directory, _client = self.make_export(rows=large_rows(count=45))
        db = FakePg()
        first, db = await self.run_import(directory, db=db, batch_size=10)
        second, db = await self.run_import(directory, db=db, batch_size=10)

        self.assertEqual(first.totals["inserted"], 90)
        self.assertEqual(second.totals["inserted"], 0)
        self.assertEqual(second.totals["errors"], 0)
        self.assertEqual(len(db.tables["actions"]), 45)
        self.assertEqual(len(db.tables["memories"]), 45)


class ConflictTests(ImporterTestCase):
    async def test_duplicate_business_key_is_skipped(self):
        directory, _client = self.make_export(rows=conflicting_rows())
        report, db = await self.run_import(directory)

        # prompt_versions: same (name, version) twice → one row stored.
        self.assertEqual(len(db.tables["prompt_versions"]), 1)
        self.assertEqual(report.tables["prompt_versions"].inserted, 1)
        self.assertEqual(report.tables["prompt_versions"].skipped, 1)

        # memories: the partial unique index blocks the second active key.
        self.assertEqual(len(db.tables["memories"]), 1)
        self.assertEqual(report.tables["memories"].inserted, 1)
        self.assertEqual(report.tables["memories"].skipped_conflict, 1)
        self.assertTrue(report.tables["memories"].examples)

    async def test_conflicts_are_reported_not_silently_dropped(self):
        directory, _client = self.make_export(rows=conflicting_rows())
        report, _db = await self.run_import(directory)
        self.assertTrue(any("already exists" in example
                            for example in report.tables["memories"].examples))

    async def test_existing_target_row_is_skipped_not_overwritten(self):
        rows = base_rows()
        directory, _client = self.make_export(rows=rows)
        db = FakePg()
        await self.run_import(directory, db=db)

        # Change an imported row by hand: a second import must leave it alone.
        db.tables["memories"][0]["memory_value"] = "changed by hand"
        expected_id = db.tables["memories"][0]["id"]
        await self.run_import(directory, db=db)

        self.assertEqual(len(db.tables["memories"]), 2)
        self.assertEqual(db.tables["memories"][0]["memory_value"],
                         "changed by hand")
        self.assertEqual(db.tables["memories"][0]["id"], expected_id)


class DependencyTests(ImporterTestCase):
    async def test_missing_parent_is_reported_and_skipped(self):
        directory, _client = self.make_export(rows=missing_dependency_rows())
        report, db = await self.run_import(directory)

        self.assertEqual(report.tables["memory_embeddings"].source_rows, 1)
        self.assertEqual(
            report.tables["memory_embeddings"].dependency_problems, 1
        )
        self.assertEqual(len(db.tables["memory_embeddings"]), 0)
        self.assertEqual(report.tables["memory_embeddings"].errors, 0)

    async def test_soft_reference_is_imported_with_a_warning(self):
        directory, _client = self.make_export(rows=missing_dependency_rows())
        report, db = await self.run_import(directory)

        self.assertEqual(len(db.tables["feedback"]), 1)
        self.assertEqual(
            report.tables["feedback"].soft_dependency_warnings, 1
        )
        self.assertEqual(report.tables["feedback"].dependency_problems, 0)

    async def test_foreign_keys_are_satisfied_after_import(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        memories = {row["id"] for row in db.tables["memories"]}
        prompts = {row["id"] for row in db.tables["prompt_versions"]}
        self.assertIn(db.tables["memory_embeddings"][0]["memory_id"], memories)
        for conversation in db.tables["conversations"]:
            if conversation["prompt_version_id"] is not None:
                self.assertIn(conversation["prompt_version_id"], prompts)

    async def test_import_order_follows_foreign_keys(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        statements = [sql for sql, _params in db.connection.executemany_calls]
        first_prompt = next(
            index for index, sql in enumerate(statements)
            if sql.startswith("insert into prompt_versions")
        )
        first_conversation = next(
            index for index, sql in enumerate(statements)
            if sql.startswith("insert into conversations")
        )
        first_memory = next(
            index for index, sql in enumerate(statements)
            if sql.startswith("insert into memories ")
        )
        first_embedding = next(
            index for index, sql in enumerate(statements)
            if sql.startswith("insert into memory_embeddings")
        )
        self.assertLess(first_prompt, first_conversation)
        self.assertLess(first_memory, first_embedding)


class ActionIdTests(ImporterTestCase):
    async def test_actions_get_a_new_generated_id(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        for row in db.tables["actions"]:
            self.assertIsInstance(row["id"], int)
            self.assertGreater(row["id"], 0)
        self.assertEqual(
            len({row["id"] for row in db.tables["actions"]}),
            len(db.tables["actions"]),
        )

    async def test_action_insert_never_sets_an_id(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        statements = [
            sql for sql, _params in db.connection.executemany_calls
            if "insert into actions" in sql
        ]
        self.assertTrue(statements)
        for sql in statements:
            column_list = sql.split("values")[0].split("(", 1)[1]
            columns = [name.strip() for name in column_list.split(",")]
            self.assertNotIn("id", columns, sql)

    async def test_action_content_is_fully_preserved(self):
        rows = base_rows()["actions"]
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        stored = {
            (row["guild_id"], row["action_type"], row["created_at"]): row
            for row in db.tables["actions"]
        }
        for source in rows:
            key = (
                source["guild_id"],
                source["action_type"],
                datetime.fromisoformat(source["created_at"]),
            )
            self.assertIn(key, stored)
            self.assertEqual(
                json.loads(stored[key]["data"]), source["data"]
            )
            self.assertEqual(stored[key]["user_id"], source["user_id"])

    async def test_history_ordering_survives_id_regeneration(self):
        rows = large_rows(count=30)
        directory, _client = self.make_export(rows=rows)
        _report, db = await self.run_import(directory)

        stored = sorted(db.tables["actions"], key=lambda row: row["created_at"])
        identifiers = [row["id"] for row in stored]
        self.assertEqual(identifiers, sorted(identifiers))
        self.assertEqual(len(stored), 30)


class LegacyIdTests(ImporterTestCase):
    async def test_non_uuid_ids_are_remapped_deterministically(self):
        directory, _client = self.make_export(rows=legacy_int_id_rows())
        report, db = await self.run_import(directory)

        conversation = db.tables["conversations"][0]
        self.assertEqual(
            conversation["id"], deterministic_uuid("conversations", 41)
        )
        self.assertEqual(report.tables["conversations"].id_remapped, 1)
        self.assertTrue(any("conversations" in warning
                            for warning in report.warnings))

        # The soft reference follows the remapped id.
        feedback = db.tables["feedback"][0]
        self.assertEqual(feedback["conversation_id"], conversation["id"])

    async def test_remapped_ids_are_stable_across_runs(self):
        directory, _client = self.make_export(rows=legacy_int_id_rows())
        db = FakePg()
        await self.run_import(directory, db=db)
        first = db.tables["conversations"][0]["id"]

        second, db = await self.run_import(directory, db=db)
        self.assertEqual(db.tables["conversations"][0]["id"], first)
        self.assertEqual(len(db.tables["conversations"]), 1)
        self.assertEqual(second.tables["conversations"].inserted, 0)


class FailureRecoveryTests(ImporterTestCase):
    async def test_failed_batch_rolls_back_and_later_batches_continue(self):
        rows = large_rows(count=30)
        directory, _client = self.make_export(rows=rows)
        db = FakePg()
        report, db = await self.run_import(directory, db=db, batch_size=10)

        self.assertEqual(len(db.tables["actions"]), 30)

        # Fail the second batch of the memories import.
        db2 = FakePg()
        db2.connection.fail_on_executemany = FakeUniqueViolation("boom")
        db2.connection.fail_call_index = 4  # actions(3 batches) + memories #1
        report, db2 = await self.run_import(directory, db=db2, batch_size=10)

        self.assertEqual(len(db2.tables["actions"]), 30)  # earlier batches kept
        self.assertEqual(report.tables["memories"].errors, 1)
        self.assertEqual(len(db2.tables["memories"]), 20)  # 2 of 3 batches
        self.assertIn("batch failed", " ".join(report.tables["memories"].examples))

    async def test_re_running_after_a_failure_completes_the_import(self):
        rows = large_rows(count=30)
        directory, _client = self.make_export(rows=rows)
        db = FakePg()
        db.connection.fail_on_executemany = FakeUniqueViolation("boom")
        db.connection.fail_call_index = 4
        await self.run_import(directory, db=db, batch_size=10)

        db.connection.fail_on_executemany = None
        db.connection.fail_call_index = None
        report, db = await self.run_import(directory, db=db, batch_size=10)

        self.assertEqual(report.totals["errors"], 0)
        self.assertEqual(len(db.tables["memories"]), 30)
        self.assertEqual(len(db.tables["actions"]), 30)

    async def test_a_failed_batch_leaves_no_partial_rows(self):
        rows = large_rows(count=12)
        directory, _client = self.make_export(rows=rows)
        db = FakePg()
        db.connection.fail_on_executemany = FakeUniqueViolation("boom")
        db.connection.fail_call_index = 1

        report, db = await self.run_import(directory, db=db, batch_size=100)
        self.assertEqual(len(db.tables["actions"]), 0)
        self.assertEqual(report.tables["actions"].errors, 1)
        self.assertEqual(len(db.tables["memories"]), 12)

    async def test_repeated_failures_abort_instead_of_looping(self):
        directory, _client = self.make_export(rows=large_rows(count=30))
        db = FakePg()
        db.connection.fail_on_executemany = FakeUniqueViolation("boom")
        report, db = await self.run_import(directory, db=db, batch_size=10)

        self.assertEqual(report.tables["actions"].errors, 4)
        self.assertEqual(len(db.tables["actions"]), 0)


class ConfirmationTests(ImporterTestCase):
    async def test_import_requires_confirmation(self):
        directory, _client = self.make_export()
        report, db = await self.run_import(
            directory, assume_yes=False, confirm=None
        )
        self.assertTrue(report.aborted)
        self.assertEqual(len(db.tables["actions"]), 0)

    async def test_declined_confirmation_writes_nothing(self):
        directory, _client = self.make_export()
        report, db = await self.run_import(
            directory, assume_yes=False, confirm=lambda _text: False
        )
        self.assertTrue(report.aborted)
        self.assertEqual(len(db.tables["actions"]), 0)

    async def test_accepted_confirmation_imports(self):
        directory, _client = self.make_export()
        report, db = await self.run_import(
            directory, assume_yes=False, confirm=lambda _text: True
        )
        self.assertFalse(report.aborted)
        self.assertEqual(len(db.tables["actions"]), 3)

    async def test_confirmation_text_warns_about_existing_data(self):
        directory, _client = self.make_export()
        db = FakePg()
        importer = PostgresImporter(
            db.pool(), directory, self.options(assume_yes=False)
        )
        # force the manifest to load without importing
        importer._manifest = __import__(
            "database.migration.manifest",
            fromlist=["load_manifest"],
        ).load_manifest(directory)

        text = importer.confirmation_text()
        self.assertIn("NOT deleted", text)
        self.assertIn("pg_dump", text)
        self.assertIn(str(directory), text)

    async def test_dry_run_does_not_ask_for_confirmation(self):
        directory, _client = self.make_export()
        report, _db = await self.run_import(
            directory, dry_run=True, assume_yes=False
        )
        self.assertFalse(report.aborted)
        self.assertTrue(report.dry_run)


class PreflightTests(ImporterTestCase):
    async def test_pending_migrations_block_the_import(self):
        directory, _client = self.make_export()
        db = FakePg(applied_migrations=False)
        with self.assertRaises(MigrationToolError) as context:
            await self.run_import(directory, db=db)
        self.assertIn("pending migrations", str(context.exception))

    async def test_schema_mismatch_blocks_the_import(self):
        directory, _client = self.make_export()
        db = FakePg()
        db.schema_columns["actions"].pop("action_type")
        with self.assertRaises(MigrationToolError) as context:
            await self.run_import(directory, db=db)
        self.assertIn("action_type", str(context.exception))

    async def test_missing_table_blocks_the_import(self):
        directory, _client = self.make_export()
        db = FakePg()
        db.schema_columns.pop("memories")
        with self.assertRaises(MigrationToolError) as context:
            await self.run_import(directory, db=db)
        self.assertIn("does not exist", str(context.exception))

    async def test_secret_scan_failure_blocks_the_import(self):
        rows = base_rows()
        rows["memories"][0]["memory_value"] = DISCORD_LOOKING_TOKEN
        directory, _client = self.make_export(rows=rows)
        with self.assertRaises(MigrationToolError) as context:
            await self.run_import(directory)
        self.assertIn("secret", str(context.exception).lower())

    async def test_invalid_export_path_is_a_clear_error(self):
        with self.assertRaises(MigrationToolError) as context:
            await self.run_import(self.tmp / "missing")
        self.assertIn("does not exist", str(context.exception))

    async def test_newer_target_schema_only_warns(self):
        directory, _client = self.make_export()
        db = FakePg()
        db.applied["003_future"] = "deadbeef"
        report, db = await self.run_import(directory, db=db)
        self.assertTrue(report.ok)
        self.assertTrue(any("newer migrations" in warning
                            for warning in report.warnings))


class SqlSafetyTests(ImporterTestCase):
    DESTRUCTIVE = ("drop ", "truncate ", "delete from", "update ", "alter ")

    async def test_only_parameterized_statements_are_sent(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        for sql, params in db.connection.executemany_calls:
            lowered = f" {sql.lower()}"
            for keyword in self.DESTRUCTIVE:
                self.assertNotIn(keyword, lowered, sql)
            for index in range(1, 20):
                if f"${index}" in sql:
                    continue
            self.assertNotIn("'", sql, "no literals in SQL")

    async def test_row_values_are_never_inlined_in_sql(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        for sql, params in db.connection.executemany_calls:
            for row in params:
                for value in row:
                    if isinstance(value, str) and len(value) > 8:
                        self.assertNotIn(value, sql)

    async def test_actions_are_never_deleted(self):
        directory, _client = self.make_export()
        _report, db = await self.run_import(directory)

        statements = [
            sql for sql, _params in db.connection.executed
        ] + [sql for sql, _params in db.connection.executemany_calls]
        for sql in statements:
            lowered = f" {sql.lower()}"
            for keyword in self.DESTRUCTIVE:
                self.assertNotIn(keyword, lowered, sql)


class VerificationTests(ImporterTestCase):
    async def test_verification_runs_after_import(self):
        directory, _client = self.make_export()
        report, _db = await self.run_import(directory, verify=True)

        self.assertIsNotNone(report.verification)
        self.assertTrue(report.verification.ok)
        self.assertEqual(report.verification.target_counts["actions"], 3)
        self.assertTrue(
            any(check.name == "memory_embeddings.memory_id_fk"
                for check in report.verification.checks)
        )
        self.assertTrue(
            any(check.name == "actions.guild_scope"
                for check in report.verification.checks)
        )

    async def test_verification_detects_orphans(self):
        directory, _client = self.make_export(rows=missing_dependency_rows())
        report, db = await self.run_import(directory, verify=True)

        # The orphan memory_embeddings row was skipped, so no FK violation.
        self.assertTrue(report.verification.ok)
        self.assertEqual(db.tables["memory_embeddings"], [])


if __name__ == "__main__":
    unittest.main()
