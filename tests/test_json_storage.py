"""JSON-file storage backend tests (no database anywhere).

Covers the repository contracts (rollback history semantics, guild isolation,
capping), conversation summaries, memory upserts, optional templates, write
atomicity and corruption tolerance.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from storage.json_store import (
    MAX_ACTIONS_PER_GUILD,
    JsonStorage,
    create_json_storage,
)


class JsonActionRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        self.storage = create_json_storage(self.data_dir)
        self.actions = self.storage.actions

    def tearDown(self):
        self._tmp.cleanup()

    async def test_entry_shape_matches_contract(self):
        await self.actions.add_action("1", {"type": "x"}, "9")
        entries = await self.actions.get_history("1")

        self.assertEqual(len(entries), 1)
        self.assertEqual(set(entries[0]), {"action", "timestamp"})
        self.assertEqual(entries[0]["action"], {"type": "x"})
        self.assertIsNotNone(entries[0]["timestamp"])

    async def test_ordering_is_stable(self):
        for index in range(5):
            await self.actions.add_action("1", {"type": f"a{index}"})

        last = await self.actions.get_last_actions("1", 3)
        self.assertEqual(
            [entry["action"]["type"] for entry in last],
            ["a4", "a3", "a2"],
        )

        full = await self.actions.get_history("1")
        self.assertEqual(
            [entry["action"]["type"] for entry in full],
            ["a0", "a1", "a2", "a3", "a4"],
        )

    async def test_amount_edge_cases(self):
        await self.actions.add_action("1", {"type": "x"})
        self.assertEqual(await self.actions.get_last_actions("1", 0), [])
        self.assertEqual(len(await self.actions.get_last_actions("1", 99)), 1)

    async def test_guild_isolation(self):
        await self.actions.add_action("1", {"type": "mine"})
        await self.actions.add_action("2", {"type": "theirs"})

        self.assertEqual(
            [entry["action"]["type"] for entry in await self.actions.get_history("1")],
            ["mine"],
        )
        self.assertEqual(
            [entry["action"]["type"] for entry in await self.actions.get_history("2")],
            ["theirs"],
        )
        await self.actions.clear_history("1")
        self.assertEqual(await self.actions.get_history("1"), [])
        self.assertEqual(len(await self.actions.get_history("2")), 1)

    async def test_history_is_capped(self):
        for index in range(MAX_ACTIONS_PER_GUILD + 25):
            await self.actions.add_action("1", {"type": f"a{index}"})

        entries = await self.actions.get_history("1")
        self.assertEqual(len(entries), MAX_ACTIONS_PER_GUILD)
        # The newest entries survive the cap.
        self.assertEqual(entries[-1]["action"]["type"], f"a{MAX_ACTIONS_PER_GUILD + 24}")

    async def test_concurrent_adds_are_serialized(self):
        await asyncio.gather(
            *(self.actions.add_action("1", {"type": f"a{i}"}) for i in range(50))
        )
        self.assertEqual(len(await self.actions.get_history("1")), 50)

    async def test_file_is_valid_json_after_writes(self):
        await self.actions.add_action("1", {"type": "x", "detail": "with — unicode"})
        raw = (self.data_dir / "actions.json").read_text(encoding="utf-8")
        document = json.loads(raw)
        self.assertIn("1", document)


class JsonConversationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = create_json_storage(Path(self._tmp.name) / "data")

    def tearDown(self):
        self._tmp.cleanup()

    async def test_save_and_summarize_recent_conversations(self):
        await self.storage.conversations.save_conversation(
            guild_id="1",
            user_id="2",
            username="alice",
            request="maak een kanaal",
            ai_plan={"summary": "ok"},
        )

        summaries = await self.storage.conversations.get_summaries("1", limit=3)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].guild_id, "1")
        self.assertIn("alice", summaries[0].summary)
        self.assertIn("maak een kanaal", summaries[0].summary)

    async def test_summaries_respect_limit_and_guild(self):
        for index in range(5):
            await self.storage.conversations.save_conversation(
                guild_id="1",
                user_id="2",
                username="u",
                request=f"req {index}",
                ai_plan={},
            )
        await self.storage.conversations.save_conversation(
            guild_id="2", user_id="3", username="x", request="other", ai_plan={}
        )

        summaries = await self.storage.conversations.get_summaries("1", limit=2)
        self.assertEqual(len(summaries), 2)
        # Newest first.
        self.assertIn("req 4", summaries[0].summary)
        self.assertEqual(len(await self.storage.conversations.get_summaries("2", 5)), 1)

    async def test_limit_zero_returns_nothing(self):
        self.assertEqual(
            await self.storage.conversations.get_summaries("1", limit=0), []
        )


class JsonMemoryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = create_json_storage(Path(self._tmp.name) / "data")

    def tearDown(self):
        self._tmp.cleanup()

    async def test_upsert_updates_existing_memory(self):
        await self.storage.memories.upsert_memory(
            "1", "2", "lang", "nl", "preference", 0.7
        )
        await self.storage.memories.upsert_memory(
            "1", "2", "lang", "en", "preference", 0.9
        )

        memories = await self.storage.memories.get_memories("1", "2")
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].value, "en")
        self.assertAlmostEqual(memories[0].confidence, 0.9)

    async def test_guild_level_versus_user_memories(self):
        await self.storage.memories.upsert_memory("1", None, "theme", "dark", "preference", 0.5)
        await self.storage.memories.upsert_memory("1", "2", "lang", "nl", "preference", 0.8)

        guild_only = await self.storage.memories.get_memories("1", None)
        self.assertEqual([m.key for m in guild_only], ["theme"])

        for_user = await self.storage.memories.get_memories("1", "2")
        self.assertEqual(sorted(m.key for m in for_user), ["lang", "theme"])

        # Other users never see user 2's memory.
        other = await self.storage.memories.get_memories("1", "3")
        self.assertEqual([m.key for m in other], ["theme"])

    async def test_confidence_ordering(self):
        await self.storage.memories.upsert_memory("1", None, "a", "1", "preference", 0.2)
        await self.storage.memories.upsert_memory("1", None, "b", "2", "preference", 0.9)

        memories = await self.storage.memories.get_memories("1", None)
        self.assertEqual([m.key for m in memories], ["b", "a"])


class JsonAnalysisAndTemplateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        self.storage = create_json_storage(self.data_dir)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_analysis_is_written_without_errors(self):
        from ai.models import ServerAnalysis, ServerIssue

        analysis = ServerAnalysis(
            guild_id="1",
            health_score=80,
            issues=[ServerIssue("low", "cat", "msg", "fix")],
            recommendations=["do x"],
        )
        await self.storage.analysis.save_analysis(analysis)

        raw = json.loads((self.data_dir / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["1"][0]["health_score"], 80)

    async def test_templates_default_to_empty(self):
        found = await self.storage.templates.find_candidates("1", "minecraft smp", 10)
        self.assertEqual(found, [])

    async def test_user_provided_templates_are_matched_by_tag(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "templates.json").write_text(
            json.dumps(
                [
                    {
                        "name": "SMP Starter",
                        "description": "Minecraft survival server",
                        "category": "gaming",
                        "tags": ["minecraft"],
                    },
                    {
                        "name": "Support Desk",
                        "description": "Helpdesk layout",
                        "category": "business",
                        "tags": ["support"],
                    },
                    {"name": "Disabled", "enabled": False, "tags": ["minecraft"]},
                ]
            ),
            encoding="utf-8",
        )

        found = await self.storage.templates.find_candidates(
            "1", "maak een minecraft smp server", 10
        )
        names = [template.name for template in found]
        self.assertEqual(names[0], "SMP Starter")
        self.assertIn("Support Desk", names)
        self.assertNotIn("Disabled", names)


class CorruptionAndLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"

    def tearDown(self):
        self._tmp.cleanup()

    async def test_corrupt_file_is_quarantined_not_fatal(self):
        self.data_dir.mkdir(parents=True)
        (self.data_dir / "actions.json").write_text("{{{", encoding="utf-8")

        storage = create_json_storage(self.data_dir)
        await storage.initialize()

        self.assertEqual(await storage.actions.get_history("1"), [])
        self.assertTrue((self.data_dir / "actions.json.corrupt").exists())

    async def test_initialize_verifies_writability(self):
        storage = create_json_storage(self.data_dir)
        await storage.initialize()
        ok, detail = await storage.healthcheck()
        self.assertTrue(ok, detail)
        self.assertEqual(detail, "json storage ok")

    async def test_close_is_safe_without_initialize(self):
        storage = create_json_storage(self.data_dir)
        await storage.close()  # must not raise


class JsonStorageInstanceTests(unittest.TestCase):
    def test_json_storage_exposes_repositories_and_data_dir(self):
        backend = JsonStorage("some/dir")
        self.assertEqual(backend.name, "json")
        self.assertEqual(backend.data_dir, Path("some/dir"))
        self.assertTrue(hasattr(backend, "actions"))
        self.assertTrue(hasattr(backend, "conversations"))


if __name__ == "__main__":
    unittest.main()
