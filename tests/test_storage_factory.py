"""Backend selection and storage factory tests."""

from __future__ import annotations

import unittest

from database.errors import StorageNotConfiguredError
from database.factory import (
    DEFAULT_DATABASE_BACKEND,
    create_storage,
    resolve_backend,
)

POSTGRES_ENV = {
    "DATABASE_BACKEND": "postgres",
    "DATABASE_URL": "postgresql://user:pass@db:5432/builder",
    "DB_POOL_MIN_SIZE": "1",
    "DB_POOL_MAX_SIZE": "10",
    "DB_MIGRATE_ON_STARTUP": "true",
}

SUPABASE_ENV = {
    "DATABASE_BACKEND": "supabase",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_KEY": "anon-key",
}


class ResolveBackendTests(unittest.TestCase):
    def test_explicit_postgres(self):
        self.assertEqual(resolve_backend(POSTGRES_ENV), "postgres")

    def test_explicit_supabase(self):
        self.assertEqual(resolve_backend(SUPABASE_ENV), "supabase")

    def test_unknown_backend_raises(self):
        with self.assertRaises(StorageNotConfiguredError):
            resolve_backend({"DATABASE_BACKEND": "mysql"})

    def test_default_is_postgres(self):
        self.assertEqual(DEFAULT_DATABASE_BACKEND, "postgres")
        self.assertEqual(resolve_backend({}), "postgres")

    def test_legacy_supabase_only_auto_selects_supabase(self):
        environ = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "anon-key",
        }
        self.assertEqual(resolve_backend(environ), "supabase")

    def test_database_url_wins_over_legacy_supabase(self):
        environ = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "anon-key",
            "DATABASE_URL": "postgresql://u:p@localhost/builder",
        }
        self.assertEqual(resolve_backend(environ), "postgres")


class CreateStorageTests(unittest.TestCase):
    def test_postgres_storage_shape(self):
        storage = create_storage(POSTGRES_ENV)
        self.assertEqual(storage.backend, "postgres")
        for attribute in (
            "actions",
            "conversations",
            "memories",
            "analysis",
            "templates",
        ):
            self.assertTrue(hasattr(storage, attribute), attribute)

    def test_postgres_requires_valid_dsn_at_build_time(self):
        environ = dict(POSTGRES_ENV)
        del environ["DATABASE_URL"]
        with self.assertRaises(StorageNotConfiguredError):
            create_storage(environ)

    def test_pool_size_validation(self):
        environ = dict(POSTGRES_ENV, DB_POOL_MAX_SIZE="0")
        with self.assertRaises(StorageNotConfiguredError):
            create_storage(environ)

        environ = dict(POSTGRES_ENV, DB_POOL_MAX_SIZE="abc")
        with self.assertRaises(StorageNotConfiguredError):
            create_storage(environ)

    def test_supabase_requires_credentials(self):
        with self.assertRaises(StorageNotConfiguredError):
            create_storage({"DATABASE_BACKEND": "supabase"})

    def test_supabase_storage_shape(self):
        # Creating the client performs no network calls.
        storage = create_storage(SUPABASE_ENV)
        self.assertEqual(storage.backend, "supabase")
        for attribute in (
            "actions",
            "conversations",
            "memories",
            "analysis",
            "templates",
        ):
            self.assertTrue(hasattr(storage, attribute), attribute)


if __name__ == "__main__":
    unittest.main()
