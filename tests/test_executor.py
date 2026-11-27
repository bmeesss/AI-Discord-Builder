"""Executor tests for builder/executor.py.

The executor runs validated plans against a guild.  These tests mock the
Discord side (channels/roles/categories helpers and the guild) and verify:
success enrichment (rollback ids), failure handling (missing objects,
Forbidden/HTTP errors) and that unknown actions never crash the plan run.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from builder.executor import ActionResult, execute_plan


def _forbidden() -> discord.Forbidden:
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "denied")


def _http_error() -> discord.HTTPException:
    return discord.HTTPException(
        MagicMock(status=500, reason="Internal Server Error"), "boom"
    )


class ExecutePlanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = MagicMock()

    async def test_create_category_success_enriches_action(self):
        category = MagicMock()
        category.id = 111
        category.name = "general"

        with patch(
            "builder.executor.categories.create_category",
            new=AsyncMock(return_value=category),
        ):
            results = await execute_plan(
                self.guild,
                [{"type": "create_category", "name": "general"}],
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        self.assertEqual(results[0].action["category_id"], 111)

    async def test_create_channel_success_enriches_ids(self):
        channel = MagicMock()
        channel.id = 222
        channel.name = "chat"
        channel.category = MagicMock(id=333)

        with patch(
            "builder.executor.channels.create_channel",
            new=AsyncMock(return_value=channel),
        ):
            results = await execute_plan(
                self.guild,
                [{"type": "create_channel", "name": "chat"}],
            )

        self.assertTrue(results[0].success)
        self.assertEqual(results[0].action["channel_id"], 222)
        self.assertEqual(results[0].action["category_id"], 333)

    async def test_unknown_action_is_reported_not_raised(self):
        results = await execute_plan(
            self.guild,
            [{"type": "launch_missiles"}],
        )
        self.assertFalse(results[0].success)
        self.assertIn("Unknown action", results[0].detail)

    async def test_missing_channel_fails_that_action_only(self):
        with patch(
            "builder.executor.find_channel",
            new=MagicMock(return_value=None),
        ):
            results = await execute_plan(
                self.guild,
                [{"type": "delete_channel", "name": "gone"}],
            )

        self.assertFalse(results[0].success)
        self.assertIn("Channel not found", results[0].detail)

    async def test_forbidden_is_reported_without_leaking_exception(self):
        with patch(
            "builder.executor.categories.create_category",
            new=AsyncMock(side_effect=_forbidden()),
        ):
            results = await execute_plan(
                self.guild,
                [{"type": "create_category", "name": "x"}],
            )

        self.assertFalse(results[0].success)
        self.assertIn("No permission", results[0].detail)

    async def test_http_exception_is_reported(self):
        with patch(
            "builder.executor.categories.create_category",
            new=AsyncMock(side_effect=_http_error()),
        ):
            results = await execute_plan(
                self.guild,
                [{"type": "create_category", "name": "x"}],
            )

        self.assertFalse(results[0].success)
        self.assertIn("Discord error", results[0].detail)

    async def test_unexpected_exception_is_reported(self):
        with patch(
            "builder.executor.categories.create_category",
            new=AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            results = await execute_plan(
                self.guild,
                [{"type": "create_category", "name": "x"}],
            )

        self.assertFalse(results[0].success)
        self.assertIn("Error", results[0].detail)

    async def test_one_failing_action_does_not_stop_the_rest(self):
        category = MagicMock()
        category.id = 1
        category.name = "ok"

        with patch(
            "builder.executor.categories.create_category",
            new=AsyncMock(side_effect=[_forbidden(), category]),
        ):
            results = await execute_plan(
                self.guild,
                [
                    {"type": "create_category", "name": "a"},
                    {"type": "create_category", "name": "b"},
                ],
            )

        self.assertEqual(len(results), 2)
        self.assertFalse(results[0].success)
        self.assertTrue(results[1].success)

    async def test_send_message_requires_text_channel(self):
        channel = MagicMock(spec=discord.VoiceChannel)
        channel.name = "voice"

        with patch(
            "builder.executor.find_channel",
            new=MagicMock(return_value=channel),
        ):
            results = await execute_plan(
                self.guild,
                [
                    {
                        "type": "send_message",
                        "channel": "voice",
                        "content": "hi",
                    }
                ],
            )

        self.assertFalse(results[0].success)
        self.assertIn("not text", results[0].detail)

    async def test_send_message_success_records_ids(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "general"
        message = MagicMock()
        message.id = 4242
        channel.send = AsyncMock(return_value=message)

        with patch(
            "builder.executor.find_channel",
            new=MagicMock(return_value=channel),
        ):
            results = await execute_plan(
                self.guild,
                [
                    {
                        "type": "send_message",
                        "channel": "general",
                        "content": "hi",
                    }
                ],
            )

        self.assertTrue(results[0].success)
        self.assertEqual(results[0].action["message_id"], 4242)

    def test_action_result_str_shows_status_icon(self):
        self.assertIn("✅", str(ActionResult({}, True, "ok")))
        self.assertIn("❌", str(ActionResult({}, False, "fail")))


if __name__ == "__main__":
    unittest.main()
