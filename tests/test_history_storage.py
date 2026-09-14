"""builder/history integration with the storage layer (injected fakes)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from builder import history
from database import set_storage


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


class HistoryStorageTests(unittest.IsolatedAsyncioTestCase):
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
        self.assertEqual(await history.get_history_count(42), 0)

    async def test_remove_last_actions_delegates(self):
        await history.remove_last_actions(42, 2)
        self.storage.actions.remove_last_actions.assert_awaited_once_with(
            "42",
            2,
        )

    async def test_clear_history_delegates(self):
        await history.clear_history(42)
        self.storage.actions.clear_history.assert_awaited_once_with("42")


class ConversationWrapperTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.storage = make_storage()
        set_storage(self.storage)

    def tearDown(self):
        set_storage(None)

    async def test_save_conversation_delegates_to_storage(self):
        from database.conversations import save_conversation

        response = '{"summary": "plan", "actions": []}'
        await save_conversation(1, 2, "mod", "maak kanaal", response)

        repo = self.storage.conversations
        repo.save_conversation.assert_awaited_once()
        kwargs = repo.save_conversation.await_args.kwargs
        self.assertEqual(kwargs["guild_id"], "1")
        self.assertEqual(kwargs["user_id"], "2")
        self.assertEqual(kwargs["ai_plan"], {"summary": "plan", "actions": []})

    async def test_save_conversation_wraps_non_json_response(self):
        from database.conversations import save_conversation

        await save_conversation(1, 2, "mod", "maak kanaal", "not-json")

        kwargs = self.storage.conversations.save_conversation.await_args.kwargs
        self.assertEqual(kwargs["ai_plan"], {"raw": "not-json"})

    async def test_save_conversation_never_raises(self):
        from database.conversations import save_conversation

        self.storage.conversations.save_conversation.side_effect = RuntimeError(
            "down"
        )
        # Must not propagate: persistence failure never breaks the Discord flow.
        await save_conversation(1, 2, "mod", "maak kanaal", "{}")


if __name__ == "__main__":
    unittest.main()
