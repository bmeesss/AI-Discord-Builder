"""Asynchrone PostgreSQL-verbinding via asyncpg.

Één gedeelde connection pool per proces (nooit een verbinding per query).
De pool wordt lui aangemaakt binnen de actieve asyncio-loop en bij shutdown
netjes gesloten.  Alle queries in de repositories gebruiken asyncpg's
``$n``-parameters; er wordt nooit user input in SQL geïnterpoleerd.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse, urlunparse

import asyncpg

from database.errors import (
    StorageNotConfiguredError,
    StorageUnavailableError,
)

logger = logging.getLogger("ai_discord_builder.database.connection")

DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0


def validate_dsn(dsn: str | None) -> str:
    """Validate a PostgreSQL DSN and return it unchanged.

    Raises a clear startup error when the value is missing or malformed so
    the bot never half-starts with a broken database configuration.
    """

    if not dsn or not dsn.strip():
        raise StorageNotConfiguredError(
            "DATABASE_URL is not set. Point it at your PostgreSQL server, "
            "e.g. postgresql://user:password@db:5432/discord_builder."
        )

    candidate = dsn.strip()
    parsed = urlparse(candidate)

    if parsed.scheme not in {"postgresql", "postgres"}:
        raise StorageNotConfiguredError(
            "DATABASE_URL must start with postgresql:// (or postgres://)."
        )

    # A TCP host in the authority, or a unix-socket directory via ?host=.
    query = parse_qs(parsed.query)
    if not parsed.hostname and "host" not in query:
        raise StorageNotConfiguredError(
            "DATABASE_URL does not contain a host."
        )

    return candidate


def mask_dsn(dsn: str) -> str:
    """Return the DSN with any password removed, safe for logs/output."""

    parsed = urlparse(dsn)
    if parsed.password is None:
        return dsn

    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"

    netloc = f"{parsed.username}:***@{host}" if parsed.username else host
    return urlunparse(parsed._replace(netloc=netloc))


class PostgresPool:
    """Lazily created asyncpg pool with explicit lifecycle."""

    def __init__(
        self,
        dsn: str,
        min_size: int = 1,
        max_size: int = 10,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self._dsn = validate_dsn(dsn)
        self._min_size = min_size
        self._max_size = max_size
        self._connect_timeout = connect_timeout
        self._command_timeout = command_timeout
        self._pool: asyncpg.Pool | None = None

    @property
    def dsn(self) -> str:
        return self._dsn

    @property
    def is_open(self) -> bool:
        return self._pool is not None

    async def open(self) -> asyncpg.Pool:
        """Create the pool inside the current event loop.

        asyncpg tests the initial connections eagerly, so an unreachable
        server raises here with a clear error instead of surfacing later
        during Discord traffic.
        """

        if self._pool is not None:
            return self._pool

        logger.info(
            "Connecting to PostgreSQL at %s (pool %s-%s)",
            mask_dsn(self._dsn),
            self._min_size,
            self._max_size,
        )

        try:
            # asyncpg reconnects dropped pooled connections automatically.
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                timeout=self._connect_timeout,
                command_timeout=self._command_timeout,
            )
        except Exception as exc:  # asyncpg raises many concrete error types
            self._pool = None
            raise StorageUnavailableError(
                "Could not connect to PostgreSQL at "
                f"{mask_dsn(self._dsn)}: {exc}"
            ) from exc

        return self._pool

    async def pool(self) -> asyncpg.Pool:
        """Return the open pool, creating it on first use."""

        return await self.open()

    async def close(self) -> None:
        """Drain the pool during shutdown; safe to call more than once."""

        pool, self._pool = self._pool, None
        if pool is None:
            return

        try:
            await pool.close()
        except Exception:
            logger.exception("Error while closing the PostgreSQL pool")

    async def ping(self) -> None:
        """Raise StorageUnavailableError when the server is unreachable."""

        pool = await self.open()
        try:
            async with pool.acquire():
                pass
        except Exception as exc:
            raise StorageUnavailableError(
                f"PostgreSQL healthcheck failed: {exc}"
            ) from exc
