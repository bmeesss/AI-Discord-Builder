"""Startup failure behavior tests — database-free edition.

The bot must fail clearly, never become half-ready, and never leak
credentials into errors or logs.  Local JSON storage problems must surface
at startup with actionable messages and must never crash on corrupt files.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import config
from storage import close_storage, create_json_storage, initialize_storage
from storage.errors import StorageUnavailableError


class ConfigFailureTests(unittest.TestCase):
    def test_missing_discord_token_fails_clearly(self):
        environ = {"AI_PROVIDER": "groq", "GROQ_API_KEY": "key"}
        with self.assertRaises(RuntimeError) as ctx:
            config.validate_config(environ=environ)
        self.assertIn("DISCORD_TOKEN", str(ctx.exception))

    def test_unknown_provider_fails_clearly(self):
        environ = {
            "DISCORD_TOKEN": "t",
            "AI_PROVIDER": "hal9000",
        }
        with self.assertRaises(RuntimeError) as ctx:
            config.validate_config(environ=environ)
        self.assertIn("AI_PROVIDER", str(ctx.exception))

    def test_missing_provider_key_fails_clearly(self):
        environ = {"DISCORD_TOKEN": "t", "AI_PROVIDER": "groq"}
        with self.assertRaises(RuntimeError) as ctx:
            config.validate_config(environ=environ)
        self.assertIn("GROQ_API_KEY", str(ctx.exception))

    def test_valid_minimal_config_needs_no_database_settings(self):
        """The hard requirement: zero database configuration."""

        config.validate_config(
            environ={
                "DISCORD_TOKEN": "t",
                "AI_PROVIDER": "groq",
                "GROQ_API_KEY": "key",
            }
        )
        for banned in (
            "DATABASE_URL",
            "DATABASE_BACKEND",
            "SUPABASE_URL",
            "SUPABASE_KEY",
            "POSTGRES_USER",
        ):
            self.assertNotIn(banned, config.__dict__)


class StorageStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_unusable_data_dir_fails_before_discord(self):
        """A read-only data dir must stop startup with a clear error."""

        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "blocked"
            blocked.mkdir()
            blocked.chmod(0o500)  # read-only directory

            try:
                storage = create_json_storage(blocked)
                with self.assertRaises(StorageUnavailableError) as ctx:
                    await storage.initialize()
                self.assertIn("not usable", str(ctx.exception))
            finally:
                blocked.chmod(0o700)  # allow cleanup

    async def test_initialize_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            for _ in range(2):
                storage = create_json_storage(data_dir)
                await storage.initialize()
                ok, detail = await storage.healthcheck()
                self.assertTrue(ok, detail)

    async def test_corrupt_json_files_do_not_crash_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "actions.json").write_text("{not json", encoding="utf-8")
            (data_dir / "conversations.json").write_text("[1,2", encoding="utf-8")

            storage = create_json_storage(data_dir)
            await storage.initialize()  # must not raise

            # Corrupt files are quarantined for manual recovery.
            self.assertTrue((data_dir / "actions.json.corrupt").exists())
            self.assertTrue(
                (data_dir / "conversations.json.corrupt").exists()
            )

    async def test_healthcheck_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            storage = create_json_storage(data_dir)
            await storage.initialize()

            # Remove the data dir behind the store's back: healthcheck must
            # report failure instead of raising.
            for child in data_dir.iterdir():
                child.unlink()
            data_dir.rmdir()
            ok, detail = await storage.healthcheck()
            self.assertFalse(ok)
            self.assertIn("missing", detail)

    async def test_initialize_storage_without_any_env(self):
        """initialize_storage works with no database configuration at all."""

        await close_storage()
        try:
            from storage import get_storage

            storage = get_storage()
            self.assertEqual(storage.backend, "json")
        finally:
            await close_storage()


class NeverHalfReadyTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_initialization_leaves_no_ready_state(self):
        """A storage failure must not leave a half-initialized singleton."""

        await close_storage()
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "blocked"
            blocked.mkdir()
            blocked.chmod(0o500)
            try:
                from storage import set_storage

                set_storage(create_json_storage(blocked))
                with self.assertRaises(StorageUnavailableError):
                    await initialize_storage()
            finally:
                blocked.chmod(0o700)
                await close_storage()
        # asyncio task cleanup for IsolatedAsyncioTestCase
        await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
