"""Shared helpers for the PostgreSQL repositories."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any


class BasePostgresRepository:
    """Repositories share one process-wide connection pool."""

    def __init__(self, pool: Any) -> None:
        # ``pool`` is a database.connection.PostgresPool (duck-typed so unit
        # tests can inject fakes without a live database).
        self._pool = pool

    async def _acquire(self):
        real_pool = await self._pool.pool()
        return real_pool.acquire()


def to_iso(value: Any) -> str | None:
    """Normalize timestamp values to ISO strings (Supabase parity)."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def loads_json(value: Any, default: Any = None) -> Any:
    """asyncpg returns jsonb as str by default; decode defensively."""

    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
