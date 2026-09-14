"""PostgreSQL DSN/config/pool tests (no live database)."""

from __future__ import annotations

import unittest

from database.connection import (
    PostgresPool,
    mask_dsn,
    validate_dsn,
)
from database.errors import StorageNotConfiguredError


class ValidateDsnTests(unittest.TestCase):
    def test_valid_postgresql_dsn(self):
        dsn = "postgresql://user:pass@db:5432/builder"
        self.assertEqual(validate_dsn(dsn), dsn)

    def test_valid_postgres_scheme_alias(self):
        dsn = "postgres://user:pass@localhost/builder"
        self.assertEqual(validate_dsn(dsn), dsn)

    def test_missing_dsn_fails_clearly(self):
        with self.assertRaises(StorageNotConfiguredError):
            validate_dsn(None)
        with self.assertRaises(StorageNotConfiguredError):
            validate_dsn("   ")

    def test_wrong_scheme_fails(self):
        with self.assertRaises(StorageNotConfiguredError):
            validate_dsn("mysql://user:pass@db/builder")

    def test_missing_host_fails(self):
        with self.assertRaises(StorageNotConfiguredError):
            validate_dsn("postgresql:///builder")


class MaskDsnTests(unittest.TestCase):
    def test_password_is_masked(self):
        masked = mask_dsn("postgresql://builder:s3cret@db:5432/app")
        self.assertNotIn("s3cret", masked)
        self.assertIn("builder:***@db:5432", masked)

    def test_dsn_without_password_stays_readable(self):
        masked = mask_dsn("postgresql://builder@db:5432/app")
        self.assertIn("db:5432", masked)


class PoolSettingsTests(unittest.TestCase):
    def test_pool_keeps_configured_sizes(self):
        pool = PostgresPool(
            "postgresql://u:p@db:5432/app",
            min_size=2,
            max_size=5,
        )
        self.assertFalse(pool.is_open)
        self.assertEqual(pool._min_size, 2)
        self.assertEqual(pool._max_size, 5)


if __name__ == "__main__":
    unittest.main()
