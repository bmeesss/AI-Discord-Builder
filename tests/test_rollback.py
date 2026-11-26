"""Rollback tests for builder/rollback.py.

History storage is mocked (builder.rollback.history); the Discord side is
mocked through the guild object.  Verified here: undo order, only successful
rollbacks are removed from history, message deletion, partial restore of
deleted channels/roles and safe failure handling.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from builder.rollback import (
    RollbackResult,
    rollback_actions,
    rollback_single_action,
)


def _entry(action: dict) -> dict:
    return {"action": action, "timestamp": "2026-01-01T00:00:00+00:00"}


class RollbackActionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = MagicMock()
        self.guild.id = 42
        # Finder helpers iterate these; keep them iterable and empty.
        self.guild.channels = []
        self.guild.categories = []
        self.guild.roles = []

    async def test_empty_history_reports_no_history(self):
        with patch(
            "builder.rollback.history.get_last_actions",
            new=AsyncMock(return_value=[]),
        ):
            results = await rollback_actions(self.guild, 3)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("No history found", results[0].detail)

    async def test_successful_rollback_removes_history_entries(self):
        channel = MagicMock()
        channel.name = "temp"
        channel.delete = AsyncMock()
        self.guild.get_channel = MagicMock(return_value=channel)

        remove = AsyncMock()
        with (
            patch(
                "builder.rollback.history.get_last_actions",
                new=AsyncMock(
                    return_value=[_entry({"type": "create_channel", "channel_id": 1})]
                ),
            ),
            patch("builder.rollback.history.remove_last_actions", new=remove),
        ):
            results = await rollback_actions(self.guild, 1)

        self.assertTrue(results[0].success)
        remove.assert_awaited_once_with(42, 1)

    async def test_only_successful_rollbacks_are_removed(self):
        channel = MagicMock()
        channel.delete = AsyncMock()
        # Entries arrive newest-first; rollback runs oldest-first (reversed):
        # entry B (channel 2) is processed first and must fail, then A succeeds.
        self.guild.get_channel = MagicMock(
            side_effect=[None, channel]
        )

        remove = AsyncMock()
        entries = [
            _entry({"type": "create_channel", "channel_id": 1, "name": "a"}),
            _entry({"type": "create_channel", "channel_id": 2, "name": "missing"}),
        ]
        with (
            patch(
                "builder.rollback.history.get_last_actions",
                new=AsyncMock(return_value=entries),
            ),
            patch("builder.rollback.history.remove_last_actions", new=remove),
        ):
            results = await rollback_actions(self.guild, 2)

        self.assertEqual(len(results), 2)
        self.assertFalse(results[0].success)  # oldest (channel 2) fails first
        self.assertTrue(results[1].success)   # newest (channel 1) succeeds
        remove.assert_awaited_once_with(42, 1)

    async def test_no_removal_when_nothing_rolled_back(self):
        self.guild.get_channel = MagicMock(return_value=None)

        remove = AsyncMock()
        with (
            patch(
                "builder.rollback.history.get_last_actions",
                new=AsyncMock(
                    return_value=[_entry({"type": "create_channel", "channel_id": 9})]
                ),
            ),
            patch("builder.rollback.history.remove_last_actions", new=remove),
        ):
            results = await rollback_actions(self.guild, 1)

        self.assertFalse(results[0].success)
        remove.assert_not_awaited()

    async def test_exception_becomes_failed_result(self):
        self.guild.get_channel = MagicMock(side_effect=RuntimeError("boom"))
        with patch(
            "builder.rollback.history.get_last_actions",
            new=AsyncMock(
                return_value=[_entry({"type": "create_channel", "channel_id": 1})]
            ),
        ):
            results = await rollback_actions(self.guild, 1)

        self.assertFalse(results[0].success)
        self.assertIn("Error", results[0].detail)


class RollbackSingleActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = MagicMock()
        self.guild.channels = []
        self.guild.categories = []
        self.guild.roles = []

    async def test_create_channel_rollback_deletes_channel(self):
        channel = MagicMock()
        channel.name = "temp"
        channel.delete = AsyncMock()
        self.guild.get_channel = MagicMock(return_value=channel)

        result = await rollback_single_action(
            self.guild, {"type": "create_channel", "channel_id": 7}
        )
        self.assertTrue(result.success)
        channel.delete.assert_awaited_once()

    async def test_rename_channel_rollback_restores_old_name(self):
        channel = MagicMock()
        channel.edit = AsyncMock()
        self.guild.get_channel = MagicMock(return_value=channel)

        result = await rollback_single_action(
            self.guild,
            {
                "type": "rename_channel",
                "channel_id": 7,
                "old_name": "before",
                "new_name": "after",
            },
        )
        self.assertTrue(result.success)
        channel.edit.assert_awaited_once()
        self.assertEqual(channel.edit.await_args.kwargs["name"], "before")

    async def test_rename_role_rollback_by_role_id(self):
        role = MagicMock()
        role.edit = AsyncMock()
        self.guild.get_role = MagicMock(return_value=role)

        result = await rollback_single_action(
            self.guild,
            {
                "type": "rename_role",
                "role_id": 5,
                "old_name": "member",
                "new_name": "vip",
            },
        )
        self.assertTrue(result.success)
        self.assertEqual(role.edit.await_args.kwargs["name"], "member")

    async def test_send_message_without_ids_fails(self):
        result = await rollback_single_action(
            self.guild, {"type": "send_message"}
        )
        self.assertFalse(result.success)
        self.assertIn("Missing message information", result.detail)

    async def test_send_message_rollback_deletes_message(self):
        message = MagicMock()
        message.delete = AsyncMock()
        channel = MagicMock()
        channel.name = "general"
        channel.fetch_message = AsyncMock(return_value=message)
        self.guild.get_channel = MagicMock(return_value=channel)

        result = await rollback_single_action(
            self.guild,
            {
                "type": "send_message",
                "channel_id": 3,
                "message_id": 4,
            },
        )
        self.assertTrue(result.success)
        message.delete.assert_awaited_once()

    async def test_send_message_already_deleted(self):
        channel = MagicMock()
        channel.name = "general"
        channel.fetch_message = AsyncMock(
            side_effect=discord.NotFound(
                MagicMock(status=404, reason="Not Found"), "gone"
            )
        )
        self.guild.get_channel = MagicMock(return_value=channel)

        result = await rollback_single_action(
            self.guild,
            {"type": "send_message", "channel_id": 3, "message_id": 4},
        )
        self.assertFalse(result.success)
        self.assertIn("already deleted", result.detail)

    async def test_delete_channel_rollback_recreates_text_channel(self):
        created = MagicMock()
        created.name = "rules"
        self.guild.create_text_channel = AsyncMock(return_value=created)
        self.guild.create_voice_channel = AsyncMock()

        result = await rollback_single_action(
            self.guild,
            {
                "type": "delete_channel",
                "channel_name": "rules",
                "channel_type": "text",
                "category_id": None,
            },
        )
        self.assertTrue(result.success)
        self.assertIn("Recreated", result.detail)
        self.guild.create_text_channel.assert_awaited_once()
        self.guild.create_voice_channel.assert_not_awaited()

    async def test_delete_channel_rollback_recreates_voice_channel(self):
        created = MagicMock()
        created.name = "Lounge"
        self.guild.create_voice_channel = AsyncMock(return_value=created)

        result = await rollback_single_action(
            self.guild,
            {
                "type": "delete_channel",
                "channel_name": "Lounge",
                "channel_type": "voice",
                "category_id": None,
            },
        )
        self.assertTrue(result.success)
        self.guild.create_voice_channel.assert_awaited_once()

    async def test_delete_channel_without_details_fails(self):
        result = await rollback_single_action(
            self.guild, {"type": "delete_channel"}
        )
        self.assertFalse(result.success)
        self.assertIn("Missing channel information", result.detail)

    async def test_delete_role_rollback_recreates_role(self):
        role = MagicMock()
        role.name = "Moderator"
        self.guild.create_role = AsyncMock(return_value=role)

        result = await rollback_single_action(
            self.guild,
            {
                "type": "delete_role",
                "role_name": "Moderator",
                "role_permissions": ["manage_messages"],
                "role_color": "#ff0000",
                "role_hoist": True,
                "role_mentionable": False,
            },
        )
        self.assertTrue(result.success)
        self.assertIn("Recreated role", result.detail)

        kwargs = self.guild.create_role.await_args.kwargs
        self.assertEqual(kwargs["name"], "Moderator")
        self.assertTrue(kwargs["hoist"])
        self.assertFalse(kwargs["mentionable"])

    async def test_unsupported_action_type_is_reported(self):
        result = await rollback_single_action(
            self.guild, {"type": "send_typing_indicator"}
        )
        self.assertFalse(result.success)
        self.assertIn("Unsupported", result.detail)

    def test_rollback_result_str_shows_status_icon(self):
        self.assertIn("✅", str(RollbackResult(True, "ok")))
        self.assertIn("❌", str(RollbackResult(False, "fail")))


if __name__ == "__main__":
    unittest.main()
