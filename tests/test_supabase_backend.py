"""Supabase adapter contract tests (mocked SDK, no network)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.errors import (
    StorageNotConfiguredError,
    StorageUnavailableError,
)
from database.supabase_backend import (
    SupabaseActionRepository,
    SupabaseBackend,
    _AsyncFacade,
    create_supabase_client,
)


def make_client(select_data: list | None = None) -> MagicMock:
    """Fluent Supabase client mock with a configurable select result."""

    client = MagicMock(name="supabase-client")
    table = client.table.return_value

    select_result = SimpleNamespace(data=select_data or [])
    (
        table.select.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute
    ).return_value = select_result
    (
        table.select.return_value
        .eq.return_value
        .order.return_value
        .execute
    ).return_value = select_result
    table.select.return_value.limit.return_value.execute.return_value = (
        select_result
    )
    table.insert.return_value.execute.return_value = SimpleNamespace(data=[])
    table.delete.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(data=[])
    )
    return client


class CreateClientTests(unittest.TestCase):
    def test_missing_credentials_fail_clearly(self):
        with self.assertRaises(StorageNotConfiguredError):
            create_supabase_client(None, "key")
        with self.assertRaises(StorageNotConfiguredError):
            create_supabase_client("https://example.supabase.co", "")


class ActionRepositoryContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_action_maps_to_actions_table(self):
        client = make_client()
        repo = SupabaseActionRepository(client)

        await repo.add_action("42", {"type": "create_role", "name": "mod"}, "7")

        client.table.assert_called_with("actions")
        client.table.return_value.insert.assert_called_once_with(
            {
                "guild_id": "42",
                "user_id": "7",
                "action_type": "create_role",
                "data": {"type": "create_role", "name": "mod"},
            }
        )

    async def test_get_last_actions_queries_own_guild_newest_first(self):
        client = make_client(
            select_data=[
                {"data": {"type": "create_channel"}, "created_at": "2026-09-01T00:00:00"},
            ]
        )
        repo = SupabaseActionRepository(client)

        result = await repo.get_last_actions("42", 5)

        chain = client.table.return_value
        chain.select.return_value.eq.assert_called_with("guild_id", "42")
        (
            chain.select.return_value
            .eq.return_value
            .order.assert_called_with("created_at", desc=True)
        )
        self.assertEqual(
            result,
            [
                {
                    "action": {"type": "create_channel"},
                    "timestamp": "2026-09-01T00:00:00",
                }
            ],
        )

    async def test_get_history_orders_oldest_first(self):
        client = make_client(
            select_data=[
                {"data": {"type": "a"}, "created_at": "t1"},
                {"data": {"type": "b"}, "created_at": "t2"},
            ]
        )
        repo = SupabaseActionRepository(client)

        result = await repo.get_history("42")

        chain = client.table.return_value
        (
            chain.select.return_value
            .eq.return_value
            .order.assert_called_with("created_at", desc=False)
        )
        self.assertEqual([entry["action"]["type"] for entry in result], ["a", "b"])

    async def test_clear_history_is_guild_scoped(self):
        client = make_client()
        repo = SupabaseActionRepository(client)

        await repo.clear_history("42")

        chain = client.table.return_value
        chain.delete.return_value.eq.assert_called_with("guild_id", "42")

    async def test_remove_last_actions_deletes_selected_ids(self):
        client = make_client(select_data=[{"id": 11}, {"id": 12}])
        repo = SupabaseActionRepository(client)

        await repo.remove_last_actions("42", 2)

        chain = client.table.return_value
        delete_eq = chain.delete.return_value.eq
        self.assertEqual(delete_eq.call_count, 2)
        delete_eq.assert_any_call("id", 11)
        delete_eq.assert_any_call("id", 12)


class BackendLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def make_backend(self, client) -> SupabaseBackend:
        with patch(
            "database.supabase_backend.create_supabase_client",
            return_value=client,
        ):
            return SupabaseBackend("https://example.supabase.co", "key")

    async def test_initialize_pings_actions_table(self):
        client = make_client()
        backend = self.make_backend(client)

        await backend.initialize()
        client.table.assert_any_call("actions")

    async def test_initialize_raises_when_unreachable(self):
        client = make_client()
        (
            client.table.return_value
            .select.return_value
            .limit.return_value
            .execute
        ).side_effect = RuntimeError("connection refused")
        backend = self.make_backend(client)

        with self.assertRaises(StorageUnavailableError):
            await backend.initialize()

    async def test_healthcheck_never_raises(self):
        client = make_client()
        (
            client.table.return_value
            .select.return_value
            .limit.return_value
            .execute
        ).side_effect = RuntimeError("down")
        backend = self.make_backend(client)

        ok, detail = await backend.healthcheck()
        self.assertFalse(ok)
        self.assertIn("down", detail)

        client.table.return_value.select.return_value.limit.return_value.execute.side_effect = None
        ok, detail = await backend.healthcheck()
        self.assertTrue(ok)

    async def test_storage_repositories_exposed(self):
        backend = self.make_backend(make_client())
        for attribute in (
            "actions",
            "conversations",
            "memories",
            "analysis",
            "templates",
        ):
            self.assertTrue(hasattr(backend, attribute), attribute)


class AsyncFacadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_wraps_sync_calls_as_coroutines(self):
        delegate = MagicMock()
        delegate.get_summaries.return_value = ["summary"]
        facade = _AsyncFacade(delegate)

        result = await facade.get_summaries(guild_id="42", limit=3)

        delegate.get_summaries.assert_called_once_with(guild_id="42", limit=3)
        self.assertEqual(result, ["summary"])


if __name__ == "__main__":
    unittest.main()
