"""Startup failure behavior tests (FASE 8).

The bot must fail clearly, never become half-ready, and never leak
credentials into errors or logs.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import database
from database.errors import (
    MigrationError,
    StorageNotConfiguredError,
    StorageUnavailableError,
)
from database.factory import create_storage
from database.postgres.backend import PostgresBackend


def make_postgres_backend(**overrides) -> PostgresBackend:
    kwargs = {
        "dsn": "postgresql://builder:s3cretpw@127.0.0.1:59999/builder",
        "min_size": 1,
        "max_size": 2,
        "migrate_on_startup": True,
    }
    kwargs.update(overrides)
    return PostgresBackend(**kwargs)


class UnreachableDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_unreachable_database_fails_clearly_before_discord(self):
        """Port 59999 is closed: initialize must fail fast with a clear error."""

        backend = make_postgres_backend()

        with self.assertRaises(StorageUnavailableError) as ctx:
            await backend.initialize()

        message = str(ctx.exception)
        self.assertIn("Could not connect to PostgreSQL", message)

    async def test_failure_message_never_contains_password(self):
        backend = make_postgres_backend()

        with self.assertRaises(StorageUnavailableError) as ctx:
            await backend.initialize()

        self.assertNotIn("s3cretpw", str(ctx.exception))
        self.assertIn("***", str(ctx.exception))

    async def test_healthcheck_masks_failures_instead_of_raising(self):
        backend = make_postgres_backend()
        ok, detail = await backend.healthcheck()
        self.assertFalse(ok)
        self.assertNotIn("s3cretpw", detail)


class MisconfigurationTests(unittest.TestCase):
    def test_wrong_dsn_scheme_fails_at_storage_creation(self):
        with self.assertRaises(StorageNotConfiguredError):
            PostgresBackend(dsn="mysql://builder:pw@127.0.0.1:3306/builder")

    def test_missing_dsn_fails_at_storage_creation(self):
        with self.assertRaises(StorageNotConfiguredError):
            create_storage(
                {"DATABASE_BACKEND": "postgres", "DATABASE_URL": ""}
            )

    def test_invalid_pool_size_fails(self):
        for bad in ("0", "-3", "not-a-number"):
            with self.assertRaises(StorageNotConfiguredError):
                create_storage(
                    {
                        "DATABASE_BACKEND": "postgres",
                        "DATABASE_URL": "postgresql://u:p@127.0.0.1/db",
                        "DB_POOL_MAX_SIZE": bad,
                    }
                )

    def test_invalid_backend_fails(self):
        with self.assertRaises(StorageNotConfiguredError):
            create_storage({"DATABASE_BACKEND": "sqlite"})


class MigrationFailureStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_migrations_block_startup_when_automigrate_off(self):
        """DB_MIGRATE_ON_STARTUP=false + pending migrations = clear startup error."""

        backend = make_postgres_backend(migrate_on_startup=False)

        class FakePool:
            async def open(self):
                return None

            async def pool(self):
                return self

            def acquire(self):
                return self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def ping(self):
                return None

            async def close(self):
                return None

            async def execute(self, sql, *params):
                return "OK"

            async def fetch(self, sql, *params):
                return []  # nothing applied yet

        backend._pool = FakePool()
        # The migrator keeps its own pool reference; swap both.
        backend._migrator._pool = backend._pool

        with self.assertRaises(MigrationError) as ctx:
            await backend.initialize()

        self.assertIn("pending", str(ctx.exception).lower())
        self.assertIn("database migrate", str(ctx.exception).lower())


class MainStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_storage_error_exits_startup_cleanly(self):
        """main() must convert StorageError into a clear SystemExit."""

        import main as main_module

        with (
            patch.object(main_module.config, "validate_config"),
            patch(
                "database.initialize_storage",
                new=AsyncMock(
                    side_effect=StorageUnavailableError("db down"),
                ),
            ),self.assertRaises(SystemExit) as ctx
        ):
            await main_module.main()

        self.assertIn("Database initialization failed", str(ctx.exception))

    async def test_full_startup_registers_database_component(self):
        """On success the database component + monitor are wired up."""

        import main as main_module
        import web.app as web_app

        storage = MagicMock()
        storage.healthcheck = AsyncMock(return_value=(True, "postgres ok"))
        storage.close = AsyncMock()
        storage.initialize = AsyncMock()

        web_app.set_ready(False)
        web_app.clear_components()

        try:
            database.set_storage(storage)
            with (
                patch.object(main_module.config, "validate_config"),
                patch(
                    "database.initialize_storage",
                    new=AsyncMock(return_value=storage),
                ),
                patch.object(main_module, "start_web_thread"),
                patch.object(
                    main_module,
                    "run_bot",
                    new=AsyncMock(side_effect=RuntimeError("discord unreachable")),
                ),
                self.assertRaises(RuntimeError),
            ):
                await main_module.main()
        finally:
            components = web_app.get_components()
            web_app.clear_components()
            database.set_storage(None)

        self.assertIn("database", components)
        self.assertTrue(components["database"]["ok"])
        storage.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
