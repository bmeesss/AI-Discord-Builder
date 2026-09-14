"""Unit tests for the PostgreSQL repository implementations.

These tests use fakes (no live database) and assert both behavior and
security properties: every query is parameterized, and every statement is
scoped to an explicit guild so records from other guilds can never leak.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from ai.models import ServerAnalysis, ServerIssue
from database.postgres.repositories.action_repository import (
    PostgresActionRepository,
)
from database.postgres.repositories.analysis_repository import (
    PostgresAnalysisRepository,
)
from database.postgres.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from database.postgres.repositories.memory_repository import (
    PostgresMemoryRepository,
)
from database.postgres.repositories.template_repository import (
    PostgresTemplateRepository,
)
from tests.fakes import FakePool


def assert_parameterized(test_case, sql: str, params: tuple) -> None:
    """User-controlled values must appear as parameters, never inline."""

    test_case.assertIn("$1", sql)
    for value in params:
        if isinstance(value, str) and value:
            test_case.assertNotIn(value, sql)


class ActionRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_action_inserts_parameterized_row(self):
        pool = FakePool()
        repo = PostgresActionRepository(pool)

        await repo.add_action(
            "123456789",
            {"type": "create_channel", "name": "general"},
            "987654321",
        )

        self.assertEqual(len(pool.conn.executed), 1)
        sql, params = pool.conn.executed[0]
        assert_parameterized(self, sql, params)
        self.assertIn("insert into actions", sql)
        self.assertEqual(params[0], "123456789")
        self.assertEqual(params[1], "987654321")
        self.assertEqual(params[2], "create_channel")
        self.assertEqual(json.loads(params[3])["name"], "general")

    async def test_get_last_actions_is_guild_scoped_and_newest_first(self):
        created = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        rows = [
            {"data": json.dumps({"type": "create_role"}), "created_at": created},
        ]
        pool = FakePool()
        pool.conn.rows = rows
        repo = PostgresActionRepository(pool)

        result = await repo.get_last_actions("42", 5)

        sql, params = pool.conn.fetched[0]
        self.assertIn("where guild_id = $1", sql)
        self.assertIn("order by created_at desc", sql)
        self.assertIn("limit $2", sql)
        self.assertEqual(params, ("42", 5))
        self.assertEqual(
            result,
            [{"action": {"type": "create_role"}, "timestamp": created.isoformat()}],
        )

    async def test_get_last_actions_rejects_non_positive_amount(self):
        pool = FakePool()
        repo = PostgresActionRepository(pool)
        self.assertEqual(await repo.get_last_actions("42", 0), [])
        self.assertEqual(pool.conn.fetched, [])

    async def test_get_history_orders_oldest_first(self):
        pool = FakePool()
        repo = PostgresActionRepository(pool)
        await repo.get_history("42")
        sql, params = pool.conn.fetched[0]
        self.assertIn("order by created_at asc", sql)
        self.assertEqual(params, ("42",))

    async def test_remove_last_actions_deletes_only_own_guild(self):
        pool = FakePool()
        repo = PostgresActionRepository(pool)
        await repo.remove_last_actions("42", 3)

        sql, params = pool.conn.executed[0]
        self.assertIn("delete from actions", sql)
        self.assertIn("where guild_id = $1", sql)
        self.assertIn("limit $2", sql)
        self.assertEqual(params, ("42", 3))

    async def test_clear_history_is_guild_scoped(self):
        pool = FakePool()
        repo = PostgresActionRepository(pool)
        await repo.clear_history("42")

        sql, params = pool.conn.executed[0]
        assert_parameterized(self, sql, params)
        self.assertIn("where guild_id = $1", sql)
        self.assertEqual(params, ("42",))


class ConversationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_conversation_persists_all_fields(self):
        pool = FakePool()
        repo = PostgresConversationRepository(pool)

        await repo.save_conversation(
            guild_id="42",
            user_id="7",
            username="mod",
            request="maak kanaal x",
            ai_plan={"summary": "plan", "actions": []},
            result={"ok": True},
        )

        sql, params = pool.conn.executed[0]
        self.assertIn("insert into conversations", sql)
        self.assertEqual(params[0], "42")
        self.assertEqual(params[1], "7")
        self.assertEqual(params[2], "mod")
        self.assertEqual(params[3], "maak kanaal x")
        self.assertIn('"summary"', params[4])
        self.assertEqual(json.loads(params[6]), {"ok": True})

    async def test_get_summaries_scoped_and_mapped(self):
        updated = datetime(2026, 9, 2, tzinfo=timezone.utc)
        pool = FakePool()
        pool.conn.rows = [
            {
                "guild_id": "42",
                "summary": "wil minecraft server",
                "preferences": json.dumps(["compact"]),
                "goals": json.dumps(["smp"]),
                "updated_at": updated,
            }
        ]
        repo = PostgresConversationRepository(pool)

        summaries = await repo.get_summaries("42", limit=3)

        sql, params = pool.conn.fetched[0]
        self.assertIn("from conversation_summaries", sql)
        self.assertIn("where guild_id = $1", sql)
        self.assertIn("deleted_at is null", sql)
        self.assertEqual(params, ("42", 3))
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].summary, "wil minecraft server")
        self.assertEqual(summaries[0].preferences, ["compact"])
        self.assertEqual(summaries[0].updated_at, updated.isoformat())


class MemoryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def _row(self, **overrides):
        row = {
            "id": uuid4(),
            "guild_id": "42",
            "user_id": None,
            "memory_key": "style",
            "memory_value": "compact",
            "memory_type": "preference",
            "confidence": 0.8,
            "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        }
        row.update(overrides)
        return row

    async def test_get_memories_with_user_includes_guild_level(self):
        pool = FakePool()
        pool.conn.rows = [self._row()]
        repo = PostgresMemoryRepository(pool)

        memories = await repo.get_memories("42", "7", limit=10)

        sql, params = pool.conn.fetched[0]
        self.assertIn("where guild_id = $1", sql)
        self.assertIn("(user_id is null or user_id = $2)", sql)
        self.assertEqual(params, ("42", "7", 10))
        self.assertEqual(memories[0].key, "style")
        self.assertAlmostEqual(memories[0].confidence, 0.8)

    async def test_get_memories_without_user_is_guild_only(self):
        pool = FakePool()
        repo = PostgresMemoryRepository(pool)

        await repo.get_memories("42", None, limit=5)

        sql, params = pool.conn.fetched[0]
        self.assertIn("and user_id is null", sql)
        self.assertEqual(params, ("42", 5))

    async def test_upsert_uses_conflict_target_and_parameters(self):
        pool = FakePool()
        repo = PostgresMemoryRepository(pool)

        await repo.upsert_memory(
            guild_id="42",
            user_id="7",
            key="style",
            value="compact",
            memory_type="preference",
            confidence=0.9,
        )

        sql, params = pool.conn.executed[0]
        self.assertIn("on conflict (guild_id, user_id, memory_type, memory_key)", sql)
        self.assertIn("do update set", sql)
        assert_parameterized(self, sql, params)
        self.assertEqual(params[:3], ("42", "7", "style"))


class AnalysisRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_analysis_serializes_issues(self):
        pool = FakePool()
        repo = PostgresAnalysisRepository(pool)
        analysis = ServerAnalysis(
            guild_id="42",
            health_score=80,
            issues=[
                ServerIssue(
                    severity="medium",
                    category="channels",
                    message="Duplicate channel name: general",
                    recommendation="Rename duplicates.",
                )
            ],
            recommendations=["Add rules channel."],
        )

        await repo.save_analysis(analysis)

        sql, params = pool.conn.executed[0]
        self.assertIn("insert into server_analysis", sql)
        self.assertEqual(params[0], "42")
        self.assertEqual(params[1], 80)
        self.assertEqual(
            json.loads(params[2])[0]["message"],
            "Duplicate channel name: general",
        )
        self.assertEqual(json.loads(params[3]), ["Add rules channel."])


class TemplateRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_tag_filter_uses_jsonb_containment(self):
        pool = FakePool()
        repo = PostgresTemplateRepository(pool)

        await repo.find_candidates(
            guild_id="42",
            user_request="Maak een minecraft smp server",
            member_count=50,
        )

        sql, params = pool.conn.fetched[0]
        self.assertIn("tags @> $1::jsonb", sql)
        self.assertEqual(json.loads(params[0]), ["minecraft"])
        self.assertEqual(params[1], 5)

    async def test_without_tags_uses_plain_enabled_filter(self):
        pool = FakePool()
        repo = PostgresTemplateRepository(pool)

        await repo.find_candidates(
            guild_id="42",
            user_request="iets algemeners",
            member_count=None,
            limit=3,
        )

        sql, params = pool.conn.fetched[0]
        self.assertNotIn("@>", sql)
        self.assertIn("where enabled", sql)
        self.assertEqual(params, (3,))


if __name__ == "__main__":
    unittest.main()
