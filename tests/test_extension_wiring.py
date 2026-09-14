"""Smoke tests: Discord extension wiring stays intact after refactors.

These tests don't need a Discord gateway; they verify the load functions
register their cogs and that the /ask flow modules import cleanly.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock


class ExtensionWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_ask_setup_registers_cog(self):
        from commands.ask import AskCog, setup

        bot = MagicMock()
        bot.add_cog = AsyncMock()

        await setup(bot)

        bot.add_cog.assert_awaited_once()
        cog = bot.add_cog.await_args.args[0]
        self.assertIsInstance(cog, AskCog)
        # The /ask application command must be present on the cog.
        self.assertTrue(hasattr(cog, "ask"))

    async def test_rollback_setup_registers_cog(self):
        from commands.rollback import RollbackCog, setup

        bot = MagicMock()
        bot.add_cog = AsyncMock()

        await setup(bot)

        cog = bot.add_cog.await_args.args[0]
        self.assertIsInstance(cog, RollbackCog)
        self.assertTrue(hasattr(cog, "rollback"))

    async def test_load_extensions_uses_same_list_as_runtime(self):
        """main.load_extensions must load ask, rollback and mention."""

        import main as main_module

        loaded: list[str] = []

        async def fake_load_extension(name: str) -> None:
            loaded.append(name)

        with unittest.mock.patch.object(
            main_module.bot,
            "load_extension",
            side_effect=fake_load_extension,
        ):
            await main_module.load_extensions()

        self.assertEqual(
            loaded,
            ["commands.ask", "commands.rollback", "commands.mention"],
        )


if __name__ == "__main__":
    unittest.main()
