"""Opt-in startup/restart/recovery integration tests against real PostgreSQL.

Skipped unless RUN_POSTGRES_TESTS=1 and DATABASE_URL are set (CI provides a
postgres service; a local Compose database works too):

    RUN_POSTGRES_TESTS=1 \\
    DATABASE_URL=postgresql://discord_builder:discord_builder@localhost:5432/discord_builder \\
        python -m unittest tests.integration.test_startup_flow

These tests create scratch databases and terminate their own connections;
they never touch other data.
"""

from __future__ import annotations

import asyncio
import io
import os
import unittest
import uuid
from contextlib import redirect_stdout
from urllib.parse import urlparse, urlunparse

from database import __main__ as database_cli
from database.connection import PostgresPool
from database.postgres.backend import PostgresBackend
from web import app as web_app

DATABASE_URL = os.getenv("DATABASE_URL", "")

RUN = os.getenv("RUN_POSTGRES_TESTS") == "1" and DATABASE_URL.startswith(
    ("postgresql://", "postgres://")
)


def dsn_for(path: str) -> str:
    parts = urlparse(DATABASE_URL)
    return urlunparse(parts._replace(path=f"/{path}"))


async def admin_execute(sql: str, *params) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn_for("postgres"))
    try:
        await conn.execute(sql, *params)
    finally:
        await conn.close()


@unittest.skipUnless(
    RUN,
    "Set RUN_POSTGRES_TESTS=1 and DATABASE_URL to run startup integration tests.",
)
class StartupFlowTests(unittest.IsolatedAsyncioTestCase):
    """The "fresh machine" flow: migrations, health/readiness, restarts."""

    async def asyncSetUp(self):
        self.dbname = f"aidb_itest_{uuid.uuid4().hex[:12]}"
        await admin_execute(f'CREATE DATABASE "{self.dbname}"')
        self.dsn = dsn_for(self.dbname)
        web_app.set_ready(False)
        web_app.clear_components()

    async def asyncTearDown(self):
        web_app.set_ready(False)
        web_app.clear_components()
        await admin_execute(f'DROP DATABASE IF EXISTS "{self.dbname}" WITH (FORCE)')

    def make_backend(self) -> PostgresBackend:
        return PostgresBackend(self.dsn, min_size=1, max_size=2)

    async def readyz_status(self) -> int:
        client = web_app.app.test_client()
        return (await asyncio.to_thread(client.get, "/readyz")).status_code

    async def test_fresh_install_startup_flow(self):
        """1-7: start -> migrate -> schema_migrations -> healthz/readyz."""

        backend = self.make_backend()

        # Storage initialization runs migrations before the Discord login.
        await backend.initialize()

        # schema_migrations exists and lists both shipped migrations.
        pool = await backend._pool.pool()
        async with pool.acquire() as conn:
            versions = await conn.fetch(
                "select version from schema_migrations order by version"
            )
        self.assertEqual([row["version"] for row in versions], ["001", "002"])

        # Core tables are usable immediately.
        await backend.actions.add_action(
            "fresh-guild", {"type": "create_channel", "name": "welkom"}, "u1"
        )
        self.assertEqual(len(await backend.actions.get_history("fresh-guild")), 1)

        # Readiness: before Discord is ready -> 503 even with healthy db.
        ok, detail = await backend.healthcheck()
        self.assertTrue(ok, detail)
        web_app.set_component("database", ok, detail)
        self.assertEqual(await self.readyz_status(), 503)

        client = web_app.app.test_client()
        self.assertEqual(
            (await asyncio.to_thread(client.get, "/healthz")).status_code, 200
        )

        # Discord runtime reports in (as on_ready does after command sync).
        web_app.set_ready(True)
        self.assertEqual(await self.readyz_status(), 200)

        await backend.close()

    async def test_bot_restart_is_idempotent(self):
        """A second process start applies no migrations and keeps data."""

        first = self.make_backend()
        await first.initialize()
        await first.actions.add_action(
            "restart-guild", {"type": "create_role", "name": "mod"}, "u1"
        )
        await first.close()

        # Fresh backend instance = fresh process/container start.
        second = self.make_backend()
        await second.initialize()

        pool = await second._pool.pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("select version from schema_migrations")
        self.assertEqual(len(rows), 2, "no duplicate migrations after restart")

        history = await second.actions.get_history("restart-guild")
        self.assertEqual(
            [entry["action"]["name"] for entry in history],
            ["mod"],
            "data written before the restart must still be there",
        )
        await second.close()

    async def test_concurrent_migration_runs_are_serialized(self):
        """Two processes racing migrations: both succeed, exactly one applies."""

        from database.postgres.migrator import Migrator

        pool_a = PostgresPool(self.dsn, min_size=1, max_size=2)
        pool_b = PostgresPool(self.dsn, min_size=1, max_size=2)
        try:
            await pool_a.open()
            await pool_b.open()

            applied_a, applied_b = await asyncio.gather(
                Migrator(pool_a).migrate(),
                Migrator(pool_b).migrate(),
            )

            total = len(applied_a) + len(applied_b)
            self.assertEqual(
                total,
                2,
                f"exactly one run applies both migrations (got {total})",
            )
            self.assertEqual(
                {len(applied_a), len(applied_b)},
                {0, 2},
                "one migrator applies all, the other finds nothing pending",
            )

            status = await Migrator(pool_a).status()
            self.assertEqual(status["pending"], [])
            self.assertEqual(len(status["applied"]), 2)
        finally:
            await pool_a.close()
            await pool_b.close()

    async def test_pool_recovers_after_database_connection_loss(self):
        """Simulates `restart db`: pool self-heals, readiness flips 503 -> 200."""

        backend = self.make_backend()
        await backend.initialize()
        await backend.actions.add_action(
            "recover-guild", {"type": "create_channel", "name": "x"}, "u1"
        )

        # Kill all of this database's connections (what a restart would do).
        await admin_execute(
            "SELECT pg_terminate_backend(pid) "
            "FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            self.dbname,
        )

        # Readiness may dip briefly while dead connections are detected.
        recovered = False
        for _attempt in range(10):
            ok, _detail = await backend.healthcheck()
            web_app.set_component("database", ok, _detail)
            if ok:
                recovered = True
                break
            await asyncio.sleep(0.2)

        self.assertTrue(recovered, "pool must recover after connection loss")

        web_app.set_ready(True)
        self.assertEqual(await self.readyz_status(), 200)

        # And the repository still serves the pre-restart data.
        history = await backend.actions.get_history("recover-guild")
        self.assertEqual(len(history), 1)

        await backend.close()


@unittest.skipUnless(
    RUN,
    "Set RUN_POSTGRES_TESTS=1 and DATABASE_URL to run startup integration tests.",
)
class CliAgainstFreshDatabaseTests(unittest.IsolatedAsyncioTestCase):
    """python -m database status/migrate lifecycle on a fresh database."""

    async def asyncSetUp(self):
        self.dbname = f"aidb_itest_{uuid.uuid4().hex[:12]}"
        await admin_execute(f'CREATE DATABASE "{self.dbname}"')
        self.dsn = dsn_for(self.dbname)

    async def asyncTearDown(self):
        await admin_execute(f'DROP DATABASE IF EXISTS "{self.dbname}" WITH (FORCE)')

    def run_cli(self, *argv: str) -> tuple[int, str]:
        import config

        original = config.DATABASE_URL
        config.DATABASE_URL = self.dsn
        try:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                rc = database_cli.main(list(argv))
        finally:
            config.DATABASE_URL = original
        return rc, buffer.getvalue()

    async def test_status_migrate_status_lifecycle(self):
        rc, out = await asyncio.to_thread(self.run_cli, "status")
        self.assertEqual(rc, 1, "status must exit 1 while migrations are pending")
        self.assertIn("001_core_tables", out)
        self.assertIn("002_intelligence_tables", out)

        rc, out = await asyncio.to_thread(self.run_cli, "migrate")
        self.assertEqual(rc, 0)
        self.assertIn("001_core_tables", out)
        self.assertIn("002_intelligence_tables", out)

        rc, out = await asyncio.to_thread(self.run_cli, "migrate")
        self.assertEqual(rc, 0)
        self.assertIn("up to date", out.lower(), "second migrate must be idempotent")

        rc, out = await asyncio.to_thread(self.run_cli, "status")
        self.assertEqual(rc, 0)
        self.assertIn("none", out.lower(), "no pending migrations after migrate")

    async def test_cli_masks_dsn_password(self):
        parsed = urlparse(self.dsn)
        _rc, out = await asyncio.to_thread(self.run_cli, "status")

        dsn_line = next(
            line for line in out.splitlines() if line.strip().startswith("dsn:")
        )
        printed = urlparse(dsn_line.split(":", 1)[1].strip())

        # Everything except the password stays visible, so an operator can
        # still see which database the CLI is talking to.
        self.assertEqual(
            (
                printed.scheme,
                printed.username,
                printed.hostname,
                printed.port,
                printed.path,
            ),
            (
                parsed.scheme,
                parsed.username,
                parsed.hostname,
                parsed.port,
                parsed.path,
            ),
        )
        self.assertEqual(printed.password, "***" if parsed.password else None)

        if parsed.password:
            # The leak to guard against is a raw 'user:password@host'
            # authority.  Do not scan the output for the bare password:
            # CI (and .env.example) use the same value for user, password and
            # database, so the *masked* line legitimately repeats it as the
            # username and database name.
            self.assertNotIn(f":{parsed.password}@", out)


if __name__ == "__main__":
    unittest.main()
