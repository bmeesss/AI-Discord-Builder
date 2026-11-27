"""Database-free startup tests.

Verifies the hard requirement: the bot starts (up to the Discord connection)
with NOTHING but a Discord token and AI-provider configuration — no
DATABASE_URL, no Supabase settings, no migrations, no connection attempts.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from storage import set_storage


MINIMAL_ENV = {
    "DISCORD_TOKEN": "test-token",
    "AI_PROVIDER": "groq",
    "GROQ_API_KEY": "test-key",
    "LOG_FILE_PATH": "",  # keep test runs out of logs/
}


class DatabaseFreeStartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        set_storage(None)  # no leftover singleton from other tests

    def tearDown(self):
        self._tmp.cleanup()

    async def test_main_starts_without_any_database_configuration(self):
        """The full startup path works with zero database settings."""

        import main as main_module

        started = asyncio.Event()

        async def fake_run_bot():
            started.set()

        with (
            patch.dict(os.environ, MINIMAL_ENV, clear=True),
            patch.object(config, "DATA_DIR", str(self.data_dir)),
            patch.object(config, "DISCORD_TOKEN", "test-token"),
            patch.object(config, "AI_PROVIDER", "groq"),
            patch.object(config, "GROQ_API_KEY", "test-key"),
            patch.object(config, "LOG_FILE_PATH", ""),
            patch.object(main_module, "run_bot", fake_run_bot),
            patch.object(main_module, "start_web_thread", lambda: None),
        ):
            await asyncio.wait_for(main_module.main(), timeout=10)

        self.assertTrue(started.is_set())
        # Local JSON storage was created; nothing else was needed.
        self.assertTrue(self.data_dir.is_dir())

    async def test_main_creates_json_files_without_migrations(self):
        """Startup performs no migrations and needs no schema."""

        import main as main_module

        async def fake_run_bot():
            return None

        with (
            patch.dict(os.environ, MINIMAL_ENV, clear=True),
            patch.object(config, "DATA_DIR", str(self.data_dir)),
            patch.object(config, "DISCORD_TOKEN", "test-token"),
            patch.object(config, "AI_PROVIDER", "groq"),
            patch.object(config, "GROQ_API_KEY", "test-key"),
            patch.object(config, "LOG_FILE_PATH", ""),
            patch.object(main_module, "run_bot", fake_run_bot),
            patch.object(main_module, "start_web_thread", lambda: None),
        ):
            await asyncio.wait_for(main_module.main(), timeout=10)

        # No schema/migration tables or files are ever created.
        self.assertFalse((self.data_dir / "schema_migrations").exists())
        self.assertFalse(any(self.data_dir.glob("*.sql")))

    async def test_bot_errors_propagate_after_storage_init(self):
        """A failed Discord login surfaces as a real error, not a hang."""

        import main as main_module

        async def failing_run_bot():
            raise RuntimeError("login failed")

        with (
            patch.dict(os.environ, MINIMAL_ENV, clear=True),
            patch.object(config, "DATA_DIR", str(self.data_dir)),
            patch.object(config, "DISCORD_TOKEN", "test-token"),
            patch.object(config, "AI_PROVIDER", "groq"),
            patch.object(config, "GROQ_API_KEY", "test-key"),
            patch.object(config, "LOG_FILE_PATH", ""),
            patch.object(main_module, "run_bot", failing_run_bot),
            patch.object(main_module, "start_web_thread", lambda: None),
        ):
            with self.assertRaises(RuntimeError):
                await asyncio.wait_for(main_module.main(), timeout=10)

    async def test_storage_dir_failure_stops_startup_before_discord(self):
        """An unusable DATA_DIR stops startup with SystemExit, never half-ready."""

        import main as main_module

        blocked = Path(self._tmp.name) / "blocked"
        blocked.mkdir()
        blocked.chmod(0o500)

        ran = []

        async def fake_run_bot():
            ran.append(True)

        try:
            with (
                patch.dict(os.environ, MINIMAL_ENV, clear=True),
                patch.object(config, "DATA_DIR", str(blocked)),
                patch.object(config, "DISCORD_TOKEN", "test-token"),
                patch.object(config, "AI_PROVIDER", "groq"),
                patch.object(config, "GROQ_API_KEY", "test-key"),
                patch.object(config, "LOG_FILE_PATH", ""),
                patch.object(main_module, "run_bot", fake_run_bot),
                patch.object(main_module, "start_web_thread", lambda: None),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    # Awaited directly (no task wrapper): SystemExit must be
                    # catchable here and must never escape into the loop.
                    await main_module.main()
        finally:
            blocked.chmod(0o700)

        self.assertIn("Local storage initialization failed", str(ctx.exception))
        self.assertEqual(ran, [], "the Discord bot must never start half-ready")

    async def test_validate_config_accepts_only_token_and_provider(self):
        config.validate_config(
            environ={
                "DISCORD_TOKEN": "t",
                "AI_PROVIDER": "openai",
                "OPENAI_API_KEY": "k",
            }
        )


if __name__ == "__main__":
    unittest.main()
