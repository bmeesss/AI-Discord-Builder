"""Opt-in PostgreSQL integration test against a real database.

Skipped unless RUN_POSTGRES_TESTS=1 and DATABASE_URL are set.  Intended for
CI (GitHub Actions services) or a local Compose database:

    RUN_POSTGRES_TESTS=1 \\
    DATABASE_URL=postgresql://discord_builder:discord_builder@localhost:5432/discord_builder \\
        python -m unittest tests.integration.test_postgres_integration

The test runs the real migrations in the target database and cleans up the
rows it creates (unique random guild ids), so it is safe to repeat.
"""

from __future__ import annotations

import os
import unittest
import uuid

from database.connection import PostgresPool
from database.postgres.migrator import Migrator
from database.postgres.repositories.action_repository import (
    PostgresActionRepository,
)
from database.postgres.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from database.postgres.repositories.memory_repository import (
    PostgresMemoryRepository,
)

DATABASE_URL = os.getenv("DATABASE_URL", "")

RUN = os.getenv("RUN_POSTGRES_TESTS") == "1" and DATABASE_URL.startswith(
    ("postgresql://", "postgres://")
)


@unittest.skipUnless(
    RUN,
    "Set RUN_POSTGRES_TESTS=1 and DATABASE_URL to run PostgreSQL integration tests.",
)
class PostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pool = PostgresPool(DATABASE_URL, min_size=1, max_size=2)
        await self.pool.open()
        migrator = Migrator(self.pool)
        await migrator.migrate()  # idempotent; must succeed here
        self.guild = f"itest-{uuid.uuid4()}"
        self.other_guild = f"itest-{uuid.uuid4()}"

    async def asyncTearDown(self):
        pool = await self.pool.pool()
        async with pool.acquire() as conn:
            for table in ("actions", "conversations", "memories"):
                await conn.execute(
                    f"delete from {table} where guild_id like 'itest-%'"
                )
        await self.pool.close()

    async def test_action_roundtrip_and_guild_isolation(self):
        repo = PostgresActionRepository(self.pool)

        await repo.add_action(
            self.guild,
            {"type": "create_channel", "name": "integration"},
            "user-1",
        )
        await repo.add_action(
            self.guild,
            {"type": "create_role", "name": "integration-mod"},
            "user-1",
        )
        await repo.add_action(
            self.other_guild,
            {"type": "create_channel", "name": "other"},
            "user-9",
        )

        last = await repo.get_last_actions(self.guild, 1)
        self.assertEqual(len(last), 1)
        self.assertEqual(last[0]["action"]["name"], "integration-mod")
        self.assertIsNotNone(last[0]["timestamp"])

        history = await repo.get_history(self.guild)
        self.assertEqual(
            [entry["action"]["type"] for entry in history],
            ["create_channel", "create_role"],
        )

        await repo.remove_last_actions(self.guild, 1)
        history = await repo.get_history(self.guild)
        self.assertEqual(len(history), 1)

        # Other guild untouched by every mutation above.
        other_history = await repo.get_history(self.other_guild)
        self.assertEqual(len(other_history), 1)

        await repo.clear_history(self.guild)
        self.assertEqual(await repo.get_history(self.guild), [])
        self.assertEqual(len(await repo.get_history(self.other_guild)), 1)

    async def test_conversation_and_memory_roundtrip(self):
        conversations = PostgresConversationRepository(self.pool)
        await conversations.save_conversation(
            guild_id=self.guild,
            user_id="user-1",
            username="tester",
            request="maak kanaal x",
            ai_plan={"summary": "s", "actions": [{"type": "create_channel"}]},
        )

        memories = PostgresMemoryRepository(self.pool)
        await memories.upsert_memory(
            guild_id=self.guild,
            user_id=None,
            key="style",
            value="compact",
            memory_type="preference",
            confidence=0.9,
        )
        await memories.upsert_memory(
            guild_id=self.guild,
            user_id=None,
            key="style",
            value="verbose",
            memory_type="preference",
            confidence=0.95,
        )

        found = await memories.get_memories(self.guild, None)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].value, "verbose")


if __name__ == "__main__":
    unittest.main()
