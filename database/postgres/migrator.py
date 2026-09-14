"""Versioned, reproduceerbare PostgreSQL-migraties.

Elke ``.sql``-file in ``database/postgres/migrations`` heet
``<versie>_<naam>.sql`` (bijv. ``001_core_tables.sql``) en wordt hooguit één
keer uitgevoerd.  Toegepaste migraties worden met een SHA-256-checksum in
``schema_migrations`` bijgehouden; wijkt de checksum van een al toegepaste
migratie af, dan stopt alles met een duidelijke fout in plaats van stil
door te gaan.  Elke migratie draait in een eigen transactie — een mislukte
migratie laat geen half-schema achter.  Er zijn geen destructieve
automatische migraties.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database.errors import MigrationError

logger = logging.getLogger("ai_discord_builder.database.migrator")

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_FILENAME = re.compile(r"^(?P<version>\d+)_(?P<name>.+)\.sql$")

_CREATE_MIGRATIONS_TABLE = """
create table if not exists schema_migrations (
    version text primary key,
    name text not null,
    checksum text not null,
    applied_at timestamptz not null default now()
)
"""


@dataclass(frozen=True)
class MigrationFile:
    version: str
    name: str
    path: Path
    checksum: str


def checksum_sql(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def load_migrations(
    directory: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> list[MigrationFile]:
    """Discover migrations, sorted by numeric version."""

    directory = Path(directory)
    if not directory.is_dir():
        raise MigrationError(f"Migration directory not found: {directory}")

    migrations: list[MigrationFile] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        match = _FILENAME.match(path.name)
        if not match:
            if path.suffix == ".sql":
                raise MigrationError(
                    f"Migration file {path.name!r} does not follow the "
                    "'<version>_<name>.sql' naming scheme."
                )
            continue
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            MigrationFile(
                version=match.group("version"),
                name=match.group("name"),
                path=path,
                checksum=checksum_sql(sql),
            )
        )

    versions = [migration.version for migration in migrations]
    if len(set(versions)) != len(versions):
        raise MigrationError(
            f"Duplicate migration versions in {directory}: {versions}"
        )

    migrations.sort(key=lambda migration: int(migration.version))
    return migrations


class Migrator:
    """Applies pending migrations against a PostgresPool-like object.

    The pool object only needs an async ``pool()`` returning something with
    an async ``acquire()`` context manager (the real PostgresPool qualifies,
    which keeps the migrator unit-testable with fakes).
    """

    def __init__(
        self,
        pool: Any,
        directory: str | Path = DEFAULT_MIGRATIONS_DIR,
    ) -> None:
        self._pool = pool
        self._directory = Path(directory)

    async def _ensure_table(self, conn: Any) -> None:
        await conn.execute(_CREATE_MIGRATIONS_TABLE)

    async def applied_migrations(self) -> dict[str, str]:
        """Return {version: checksum} of applied migrations."""

        pool = await self._pool.pool()
        async with pool.acquire() as conn:
            await self._ensure_table(conn)
            rows = await conn.fetch(
                "select version, checksum from schema_migrations"
            )
        return {str(row["version"]): str(row["checksum"]) for row in rows}

    async def pending_migrations(self) -> list[MigrationFile]:
        applied = await self.applied_migrations()
        pending: list[MigrationFile] = []

        for migration in load_migrations(self._directory):
            existing = applied.get(migration.version)
            if existing is None:
                pending.append(migration)
            elif existing != migration.checksum:
                raise MigrationError(
                    f"Migration {migration.version}_{migration.name} was "
                    "already applied but its checksum changed. Do not edit "
                    "applied migrations; add a new migration instead."
                )

        return pending

    async def migrate(self) -> list[MigrationFile]:
        """Apply all pending migrations once, in order.

        Stops at the first failure; the error names the failing migration.
        Returns the migrations applied during this run.
        """

        pending = await self.pending_migrations()
        applied_now: list[MigrationFile] = []

        for migration in pending:
            label = f"{migration.version}_{migration.name}"
            logger.info("Applying database migration %s", label)
            sql = migration.path.read_text(encoding="utf-8")
            try:
                pool = await self._pool.pool()
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.execute(sql)
                        await conn.execute(
                            "insert into schema_migrations "
                            "(version, name, checksum) values ($1, $2, $3)",
                            migration.version,
                            migration.name,
                            migration.checksum,
                        )
            except Exception as exc:
                raise MigrationError(
                    f"Migration {label} failed: {exc}"
                ) from exc
            applied_now.append(migration)
            logger.info("Migration %s applied", label)

        return applied_now

    async def status(self) -> dict:
        """Return applied/pending info for humans and /readyz checks."""

        applied = await self.applied_migrations()
        # pending_migrations re-validates checksums and raises on mismatch.
        pending = await self.pending_migrations()
        return {
            "applied": [
                {"version": version, "checksum": checksum}
                for version, checksum in sorted(applied.items())
            ],
            "pending": [
                {"version": migration.version, "name": migration.name}
                for migration in pending
            ],
        }
