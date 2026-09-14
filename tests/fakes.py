"""Shared fakes for database unit tests (no live PostgreSQL needed).

The fakes mimic the small slice of asyncpg the storage layer uses:
``pool()`` returning an object with ``acquire()`` as an async context
manager, and connections with ``fetch``/``execute``/``transaction``.
Every executed statement is captured so tests can assert on SQL and
parameters (e.g. guild isolation, no string interpolation).
"""

from __future__ import annotations

from typing import Any


class FakeTransaction:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.commits += 1
        return False


class FakeConnection:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.fetched: list[tuple[str, tuple]] = []
        self.executed: list[tuple[str, tuple]] = []
        self.transactions = 0
        self.fail_on_execute: Exception | None = None
        # Only fail statements containing this substring (targeted failures).
        self.fail_substring: str | None = None

    async def fetch(self, sql: str, *params: Any) -> list:
        self.fetched.append((sql, params))
        return self.rows

    async def execute(self, sql: str, *params: Any) -> str:
        failing = self.fail_on_execute is not None and (
            self.fail_substring is None or self.fail_substring in sql
        )
        if failing:
            raise self.fail_on_execute
        self.executed.append((sql, params))
        return "OK"

    def transaction(self) -> FakeTransaction:
        self.transactions += 1
        return FakeTransaction()


class FakeAcquire:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeInnerPool:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)


class FakePool:
    """Drop-in for database.connection.PostgresPool in unit tests."""

    def __init__(self, conn: FakeConnection | None = None) -> None:
        self.inner = FakeInnerPool(conn or FakeConnection())

    @property
    def conn(self) -> FakeConnection:
        return self.inner.conn

    async def pool(self) -> FakeInnerPool:
        return self.inner
