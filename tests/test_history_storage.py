"""builder/history + JSON storage integration.

Two layers are covered:
1. history delegates to the injected storage (fakes) and swallows failures;
2. the real JSON store round-trips rollback history with guild isolation.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from builder import history
from storage import set_storage
from storage.json_store import create_json_storage


def make_storage(**overrides) -> SimpleNamespace:
    storage = SimpleNamespace(
        actions=AsyncMock(),
        conversations=AsyncMock(),
        memories=AsyncMock(),
        analysis=AsyncMock(),
        templates=AsyncMock(),
    )
    for name, value in overrides.items():
        setattr(storage, name, value)
    return storage


class HistoryDelegationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.storage = make_storage()
        set_storage(self.storage)

    def tearDown(self):
        set_storage(None)

    async def test_add_action_delegates_with_stringified_ids(self):
        self.storage.actions.add_action.return_value = None

        await history.add_action(123, {"type": "create_channel"}, 456)

        self.storage.actions.add_action.assert_awaited_once_with(
            "123",
            {"type": "create_channel"},
            "456",
        )

    async def test_get_last_actions_returns_repo_result(self):
        entries = [{"action": {"type": "x"}, "timestamp": "t"}]
        self.storage.actions.get_last_actions.return_value = entries

        result = await history.get_last_actions(42, 3)

        self.storage.actions.get_last_actions.assert_awaited_once_with("42", 3)
        self.assertEqual(result, entries)

    async def test_storage_failure_returns_empty_history(self):
        self.storage.actions.get_last_actions.side_effect = RuntimeError("down")

        self.assertEqual(await history.get_last_actions(42, 3), [])

        self.storage.actions.get_history.side_effect = RuntimeError("down")
        self.assertEqual(await history.get_history(42), [])

    async def test_remove_and_clear_swallow_failures(self):
        self.storage.actions.remove_last_actions.side_effect = RuntimeError("down")
        await history.remove_last_actions(42, 1)  # must not raise

        self.storage.actions.clear_history.side_effect = RuntimeError("down")
        await history.clear_history(42)  # must not raise


class JsonHistoryRoundtripTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        self.storage = create_json_storage(self.data_dir)
        set_storage(self.storage)

    def tearDown(self):
        set_storage(None)
        self._tmp.cleanup()

    async def test_roundtrip_newest_first_and_guild_isolation(self):
        await history.add_action(1, {"type": "a"}, 9)
        await history.add_action(1, {"type": "b"}, 9)
        await history.add_action(2, {"type": "other"}, 9)

        last = await history.get_last_actions(1, 10)
        self.assertEqual([entry["action"]["type"] for entry in last], ["b", "a"])

        full = await history.get_history(1)
        self.assertEqual([entry["action"]["type"] for entry in full], ["a", "b"])

        # Guild 2 never sees guild 1 data.
        self.assertEqual(
            [entry["action"]["type"] for entry in await history.get_history(2)],
            ["other"],
        )

    async def test_remove_last_actions_and_clear(self):
        await history.add_action(1, {"type": "a"}, None)
        await history.add_action(1, {"type": "b"}, None)

        await history.remove_last_actions(1, 1)
        remaining = await history.get_history(1)
        self.assertEqual([entry["action"]["type"] for entry in remaining], ["a"])

        await history.clear_history(1)
        self.assertEqual(await history.get_history(1), [])

    async def test_history_survives_a_restart(self):
        await history.add_action(1, {"type": "create_channel"}, 9)

        # "Restart": a fresh storage object over the same directory.
        set_storage(create_json_storage(self.data_dir))
        last = await history.get_last_actions(1, 1)
        self.assertEqual(last[0]["action"]["type"], "create_channel")

    async def test_history_count(self):
        await history.add_action(1, {"type": "a"}, None)
        await history.add_action(1, {"type": "b"}, None)
        self.assertEqual(await history.get_history_count(1), 2)


if __name__ == "__main__":
    unittest.main()
