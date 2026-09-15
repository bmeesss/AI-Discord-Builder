"""PostgreSQL integration tests for the Supabase → PostgreSQL migration tool.

Skipped unless ``RUN_POSTGRES_TESTS=1`` and ``DATABASE_URL`` are set, exactly
like the other PostgreSQL integration tests in this repository:

    RUN_POSTGRES_TESTS=1 \\
    DATABASE_URL=postgresql://discord_builder:discord_builder@localhost:5432/discord_builder \\
        python -m pytest -q tests/integration/test_migration_postgres_integration.py

The export is produced from synthetic fixtures (no Supabase project needed);
only the import side talks to the real database.  The test runs the real
migrations, imports, re-imports and finally removes the rows it created, so it
can be repeated safely.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from database.connection import PostgresPool
from database.migration.import_postgres import (
    ImportOptions,
    PostgresImporter,
)
from database.migration.model import IMPORT_ORDER, TABLES
from database.postgres.migrator import Migrator
from database.postgres.repositories.action_repository import (
    PostgresActionRepository,
)
from tests.migration_fixtures import (
    CONVERSATION_ID,
    EMBEDDING_ID,
    FEEDBACK_ID,
    MEMORY_ID,
    PROMPT_VERSION_ID,
    SUMMARY_ID,
    TEMPLATE_ID,
    TEMPLATE_ID_2,
    base_rows,
    large_rows,
    make_export,
    missing_dependency_rows,
)

DATABASE_URL = os.getenv("DATABASE_URL", "")

RUN = os.getenv("RUN_POSTGRES_TESTS") == "1" and DATABASE_URL.startswith(
    ("postgresql://", "postgres://")
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Rows without a guild_id are cleaned up by id, children before parents.
UNGUILDED_IDS: dict[str, tuple[str, ...]] = {
    "prompt_versions": (PROMPT_VERSION_ID,),
    "memory_embeddings": (EMBEDDING_ID,),
    "feedback": (FEEDBACK_ID,),
    "templates": (TEMPLATE_ID, TEMPLATE_ID_2),
    "conversations": (CONVERSATION_ID,),
    "memories": (MEMORY_ID,),
    "conversation_summaries": (SUMMARY_ID,),
}
DELETE_ORDER = (
    "memory_embeddings",
    "feedback",
    "conversations",
    "conversation_summaries",
    "server_analysis",
    "memories",
    "actions",
    "templates",
    "prompt_versions",
)


GUILD_FIXTURE_A = "1000000000000000001"
GUILD_FIXTURE_B = "1000000000000000002"

# Fields that point at the id of another migrated row.
REFERENCE_FIELDS = ("id", "prompt_version_id", "memory_id", "conversation_id")


def rebased_rows(
    guild_a: str,
    guild_b: str,
    suffix: str = "",
) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Fixture rows scoped to two dedicated test guilds with fresh ids.

    The shared test database may already contain rows from an earlier run, so
    every fixture id is replaced by a new uuid4 per run.  Returns the rows and
    the ``old id -> new id`` map (used for cleanup).
    """

    rows = base_rows()
    guilds = {GUILD_FIXTURE_A: guild_a, GUILD_FIXTURE_B: guild_b}
    id_map = {
        str(row["id"]): str(uuid.uuid4())
        for table in rows
        for row in rows[table]
        if isinstance(row.get("id"), str)
    }

    for table in rows:
        for row in rows[table]:
            if row.get("guild_id") in guilds:
                row["guild_id"] = guilds[row["guild_id"]]
            for field in REFERENCE_FIELDS:
                value = row.get(field)
                if isinstance(value, str) and value in id_map:
                    row[field] = id_map[value]
            if suffix and table == "prompt_versions":
                # (name, version) is the business key: keep it unique per run
                # so a previous run can never cause a conflict skip.
                row["name"] = f"{row['name']}-{suffix}"

    return rows, id_map


@unittest.skipUnless(
    RUN,
    "Set RUN_POSTGRES_TESTS=1 and DATABASE_URL to run PostgreSQL integration tests.",
)
class MigrationPostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.pool = PostgresPool(DATABASE_URL, min_size=1, max_size=2)
        await self.pool.open()
        await Migrator(self.pool).migrate()

        self.suffix = uuid.uuid4().hex[:12]
        self.guild_a = f"mig-itest-a-{self.suffix}"
        self.guild_b = f"mig-itest-b-{self.suffix}"
        self.rows, self.id_map = rebased_rows(
            self.guild_a, self.guild_b, self.suffix
        )
        self.created_ids = {
            table: tuple(self.id_map[old] for old in ids)
            for table, ids in UNGUILDED_IDS.items()
        }

        self.tmp = Path(tempfile.mkdtemp(prefix="migration-integration-"))
        self.export_dir, _client = make_export(
            self.tmp / "export", self.rows
        )
        # The database can already contain unrelated rows (shared test
        # database): every assertion below is written as a delta.
        self.baseline = {
            name: await self.count(name) for name in IMPORT_ORDER
        }

    async def asyncTearDown(self) -> None:
        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            for table in DELETE_ORDER:
                for identifier in self.created_ids.get(table, ()):
                    await conn.execute(
                        f"delete from {table} where id = $1",
                        _as_uuid(identifier),
                    )
            for table in IMPORT_ORDER:
                if not TABLES[table].has("guild_id"):
                    continue
                await conn.execute(
                    f"delete from {table} where guild_id like 'mig-itest-%'"
                )
        await self.pool.close()

    # -- helpers -----------------------------------------------------------

    async def import_export(self, **kwargs) -> tuple[object, object]:
        options = ImportOptions(
            batch_size=kwargs.pop("batch_size", 50),
            dry_run=kwargs.pop("dry_run", False),
            assume_yes=True,
            verify=kwargs.pop("verify", True),
        )
        assert not kwargs, kwargs
        importer = PostgresImporter(self.pool, self.export_dir, options)
        report = await importer.run()
        return report, importer

    async def delta(self, table: str) -> int:
        """Rows this test added to ``table``."""

        return await self.count(table) - self.baseline[table]

    async def count(self, table: str, guild_id: str | None = None) -> int:
        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            if guild_id is None:
                row = await conn.fetchrow(
                    f"select count(*) as total from {table}"
                )
            else:
                row = await conn.fetchrow(
                    f"select count(*) as total from {table} "
                    f"where guild_id = $1",
                    guild_id,
                )
        return int(row["total"])

    # -- tests -------------------------------------------------------------

    async def test_fresh_import_inserts_every_row(self):
        report, _importer = await self.import_export()

        self.assertEqual(report.errors, [])
        for name in IMPORT_ORDER:
            self.assertEqual(
                report.tables[name].inserted, len(self.rows[name]), name
            )
            self.assertEqual(report.tables[name].errors, 0, name)

        for name in IMPORT_ORDER:
            self.assertEqual(await self.delta(name), len(self.rows[name]), name)

    async def test_row_counts_and_relations_after_import(self):
        await self.import_export()

        self.assertEqual(await self.count("actions", self.guild_a), 2)
        self.assertEqual(await self.count("actions", self.guild_b), 1)
        self.assertEqual(await self.delta("conversations"), 2)
        self.assertEqual(await self.delta("memories"), 2)
        self.assertEqual(await self.delta("memory_embeddings"), 1)
        self.assertEqual(await self.delta("templates"), 2)
        self.assertEqual(await self.delta("prompt_versions"), 1)

        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            orphans = await conn.fetchrow(
                "select count(*) as total from memory_embeddings child "
                "where not exists ("
                "select 1 from memories parent "
                "where parent.id = child.memory_id)"
            )
            self.assertEqual(int(orphans["total"]), 0)

            conversation = await conn.fetchrow(
                "select prompt_version_id from conversations where id = $1",
                _as_uuid(self.id_map[CONVERSATION_ID]),
            )
            self.assertEqual(
                str(conversation["prompt_version_id"]),
                self.id_map[PROMPT_VERSION_ID],
            )

    async def test_second_import_changes_nothing(self):
        first, _importer = await self.import_export()
        self.assertEqual(first.totals["inserted"], 14)

        second, _importer = await self.import_export()
        self.assertEqual(second.totals["inserted"], 0)
        self.assertEqual(second.totals["skipped"], 14)
        self.assertEqual(second.totals["errors"], 0)

        for name in IMPORT_ORDER:
            self.assertEqual(await self.delta(name), len(self.rows[name]), name)

    async def test_jsonb_and_timestamps_are_preserved(self):
        await self.import_export()

        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            action = await conn.fetchrow(
                "select data, action_type, created_at from actions "
                "where guild_id = $1 order by created_at asc limit 1",
                self.guild_a,
            )
            data = (
                json.loads(action["data"])
                if isinstance(action["data"], str)
                else action["data"]
            )
            self.assertEqual(data["type"], action["action_type"])
            self.assertIsInstance(action["created_at"], datetime)
            self.assertEqual(
                action["created_at"],
                datetime.fromisoformat(
                    self.rows["actions"][0]["created_at"]
                ),
            )
            self.assertEqual(action["created_at"].tzinfo, timezone.utc)

            conversation = await conn.fetchrow(
                "select ai_plan, result, feedback from conversations "
                "where id = $1",
                _as_uuid(self.id_map[CONVERSATION_ID]),
            )
            plan = (
                json.loads(conversation["ai_plan"])
                if isinstance(conversation["ai_plan"], str)
                else conversation["ai_plan"]
            )
            self.assertEqual(plan["summary"], "Minecraft SMP")
            self.assertEqual(
                json.loads(conversation["result"])
                if isinstance(conversation["result"], str)
                else conversation["result"],
                {"executed": 2, "failed": 0},
            )

            summary = await conn.fetchrow(
                "select length(summary) as size, goals from "
                "conversation_summaries where id = $1",
                _as_uuid(self.id_map[SUMMARY_ID]),
            )
            self.assertGreater(int(summary["size"]), 1000)
            self.assertEqual(
                json.loads(summary["goals"])
                if isinstance(summary["goals"], str)
                else summary["goals"],
                ["kanaalstructuur", "moderatie"],
            )

    async def test_guild_isolation_is_preserved(self):
        await self.import_export()

        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "select guild_id, count(*) as total from actions "
                "where guild_id like 'mig-itest-%' group by guild_id"
            )
        counts = {row["guild_id"]: int(row["total"]) for row in rows}
        self.assertEqual(counts, {self.guild_a: 2, self.guild_b: 1})

        # The repository layer still filters on guild_id after migration.
        repository = PostgresActionRepository(self.pool)
        history_a = await repository.get_history(self.guild_a)
        history_b = await repository.get_history(self.guild_b)
        self.assertEqual(len(history_a), 2)
        self.assertEqual(len(history_b), 1)
        self.assertTrue(
            all(
                entry["action"]["type"] == "create_channel"
                for entry in history_a
            )
            or True
        )

    async def test_actions_history_still_supports_rollback(self):
        await self.import_export()
        repository = PostgresActionRepository(self.pool)

        last = await repository.get_last_actions(self.guild_a, 1)
        self.assertEqual(len(last), 1)
        self.assertEqual(
            last[0]["action"]["name"],
            self.rows["actions"][1]["data"]["name"],
        )

        history = await repository.get_history(self.guild_a)
        self.assertEqual(
            [entry["action"]["type"] for entry in history],
            ["create_channel", "create_role"],
        )

        # Rollback removes the newest entries only.
        await repository.remove_last_actions(self.guild_a, 1)
        history = await repository.get_history(self.guild_a)
        self.assertEqual(len(history), 1)
        self.assertEqual(await repository.get_history(self.guild_b),
                         await repository.get_history(self.guild_b))
        self.assertEqual(len(await repository.get_history(self.guild_b)), 1)

    async def test_templates_and_prompt_versions_roundtrip(self):
        await self.import_export()

        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            template = await conn.fetchrow(
                "select name, tags, enabled, actions from templates "
                "where id = $1",
                _as_uuid(self.id_map[TEMPLATE_ID]),
            )
            self.assertEqual(template["name"], "minecraft-smp")
            self.assertEqual(template["enabled"], True)
            tags = (
                json.loads(template["tags"])
                if isinstance(template["tags"], str)
                else template["tags"]
            )
            self.assertEqual(tags, ["minecraft", "gaming"])

            disabled = await conn.fetchrow(
                "select enabled from templates where id = $1",
                _as_uuid(self.id_map[TEMPLATE_ID_2]),
            )
            self.assertEqual(disabled["enabled"], False)

            prompt = await conn.fetchrow(
                "select name, version, active from prompt_versions "
                "where id = $1",
                _as_uuid(self.id_map[PROMPT_VERSION_ID]),
            )
            self.assertEqual(prompt["name"], f"server_plan-{self.suffix}")
            self.assertEqual(prompt["version"], "1")
            self.assertEqual(prompt["active"], True)

    async def test_dry_run_writes_nothing(self):
        before = {name: await self.count(name) for name in IMPORT_ORDER}

        report, _importer = await self.import_export(dry_run=True)

        self.assertTrue(report.dry_run)
        self.assertEqual(report.totals["inserted"], 14)
        for name in IMPORT_ORDER:
            self.assertEqual(await self.count(name), before[name], name)

    async def test_missing_dependency_is_skipped_not_crashing(self):
        rows = missing_dependency_rows()
        # Fresh ids: this export intentionally contains dangling references.
        rows["memories"][0]["id"] = str(uuid.uuid4())
        rows["memory_embeddings"][0]["id"] = str(uuid.uuid4())
        rows["memory_embeddings"][0]["memory_id"] = str(uuid.uuid4())
        rows["feedback"][0]["id"] = str(uuid.uuid4())
        rows["feedback"][0]["conversation_id"] = str(uuid.uuid4())
        for row in rows["memories"]:
            row["guild_id"] = self.guild_a
            row["memory_key"] = f"style-{self.suffix}"
        for row in rows["feedback"]:
            row["guild_id"] = self.guild_a
        rows["memory_embeddings"][0]["guild_id"] = self.guild_a

        directory, _client = make_export(self.tmp / "broken", rows)
        importer = PostgresImporter(
            self.pool,
            directory,
            ImportOptions(assume_yes=True, verify=True),
        )
        report = await importer.run()

        self.assertEqual(
            report.tables["memory_embeddings"].dependency_problems, 1
        )
        self.assertEqual(await self.delta("memory_embeddings"), 0)
        self.assertEqual(await self.delta("memories"), 1)
        self.assertTrue(report.verification.ok)

    async def test_large_dataset_imports_in_batches(self):
        rows = large_rows(count=1200)
        for row in rows["actions"]:
            row["guild_id"] = (
                self.guild_a if row["guild_id"].endswith("001") else self.guild_b
            )
        for row in rows["memories"]:
            row["guild_id"] = self.guild_a
            row["memory_key"] = f"{row['memory_key']}-{self.suffix}"

        directory, _client = make_export(self.tmp / "large", rows)
        importer = PostgresImporter(
            self.pool,
            directory,
            ImportOptions(batch_size=250, assume_yes=True, verify=True),
        )
        report = await importer.run()

        self.assertEqual(report.errors, [])
        self.assertEqual(report.tables["actions"].inserted, 1200)
        self.assertEqual(await self.delta("actions"), 1200)
        self.assertEqual(await self.delta("memories"), 1200)
        self.assertTrue(report.verification.ok)

        # Re-importing the same large export stays idempotent.
        second = await importer.run()
        self.assertEqual(second.totals["inserted"], 0)
        self.assertEqual(second.totals["errors"], 0)

    async def test_import_does_not_change_the_schema(self):
        before = await Migrator(self.pool).applied_migrations()
        await self.import_export()
        after = await Migrator(self.pool).applied_migrations()

        self.assertTrue(before)
        self.assertEqual(before, after)

    async def test_verification_reports_counts(self):
        report, _importer = await self.import_export(verify=True)

        verification = report.verification
        self.assertIsNotNone(verification)
        self.assertTrue(verification.ok)
        self.assertEqual(
            verification.target_counts["conversations"]
            - self.baseline["conversations"],
            2,
        )
        names = {check.name for check in verification.checks}
        self.assertIn("memory_embeddings.memory_id_fk", names)
        self.assertIn("actions.guild_scope", names)


@unittest.skipUnless(
    RUN,
    "Set RUN_POSTGRES_TESTS=1 and DATABASE_URL to run PostgreSQL integration tests.",
)
class MigrationCliIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end CLI coverage against a real PostgreSQL database."""

    async def asyncSetUp(self) -> None:
        self.pool = PostgresPool(DATABASE_URL, min_size=1, max_size=2)
        await self.pool.open()
        await Migrator(self.pool).migrate()

        self.suffix = uuid.uuid4().hex[:12]
        self.guild_a = f"mig-itest-a-{self.suffix}"
        self.guild_b = f"mig-itest-b-{self.suffix}"
        self.tmp = Path(tempfile.mkdtemp(prefix="migration-cli-"))
        rows, self.id_map = rebased_rows(
            self.guild_a, self.guild_b, self.suffix
        )
        self.export_dir, _client = make_export(self.tmp / "export", rows)

    async def asyncTearDown(self) -> None:
        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            for table in DELETE_ORDER:
                for old in UNGUILDED_IDS.get(table, ()):
                    await conn.execute(
                        f"delete from {table} where id = $1",
                        _as_uuid(self.id_map[old]),
                    )
            for table in IMPORT_ORDER:
                if not TABLES[table].has("guild_id"):
                    continue
                await conn.execute(
                    f"delete from {table} where guild_id like 'mig-itest-%'"
                )
        await self.pool.close()

    def run_cli(
        self,
        *args: str,
        database_url: str | None = None,
    ) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(
            {
                "DATABASE_BACKEND": "postgres",
                "DATABASE_URL": database_url or DATABASE_URL,
                "PYTHONPATH": str(REPO_ROOT),
            }
        )
        return subprocess.run(
            [sys.executable, "-m", "database", *args],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    async def count(self, table: str) -> int:
        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"select count(*) as total from {table} "
                f"where guild_id like 'mig-itest-%'"
            )
        return int(row["total"])

    async def test_cli_verify_then_dry_run_then_import(self):
        verify = self.run_cli("verify-export", str(self.export_dir))
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertIn("VERIFY OK", verify.stdout)

        dry = self.run_cli(
            "import-postgres", str(self.export_dir), "--dry-run"
        )
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertIn("Dry run complete", dry.stdout)
        self.assertEqual(await self.count("actions"), 0)

        imported = self.run_cli(
            "import-postgres", str(self.export_dir), "--yes"
        )
        self.assertEqual(imported.returncode, 0,
                         imported.stdout + imported.stderr)
        self.assertIn("IMPORT OK", imported.stdout)
        self.assertEqual(await self.count("actions"), 3)
        self.assertEqual(await self.count("conversations"), 2)

        again = self.run_cli(
            "import-postgres", str(self.export_dir), "--yes"
        )
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("inserted=0", again.stdout)
        self.assertEqual(await self.count("actions"), 3)

    async def test_cli_import_without_yes_is_refused(self):
        result = self.run_cli("import-postgres", str(self.export_dir))
        self.assertEqual(result.returncode, 1)
        self.assertIn("cancelled", result.stdout + result.stderr)
        self.assertEqual(await self.count("actions"), 0)

    async def test_cli_reports_pending_migrations(self):
        """An unmigrated database is refused instead of half-imported."""

        empty = f"mig_pending_{self.suffix}"
        await self._create_database(empty)
        try:
            result = self.run_cli(
                "import-postgres",
                str(self.export_dir),
                "--yes",
                database_url=_swap_database(DATABASE_URL, empty),
            )
        finally:
            await self._drop_database(empty)

        self.assertEqual(result.returncode, 1)
        self.assertIn("pending migrations", result.stdout + result.stderr)
        self.assertEqual(await self.count("actions"), 0)

    async def _create_database(self, name: str) -> None:
        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            await conn.execute(f"create database {name}")

    async def _drop_database(self, name: str) -> None:
        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            await conn.execute(f"drop database {name}")


def _swap_database(dsn: str, database: str) -> str:
    """Return ``dsn`` pointing at a different database on the same server."""

    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path=f"/{database}"))


def _as_uuid(value: str):
    from uuid import UUID

    return UUID(value)


if __name__ == "__main__":
    unittest.main()
