"""PostgreSQL storage backend — de standaard voor self-hosting.

Bundelt de connection pool, de repositories en de migration runner achter
één lifecycle (initialize/close/healthcheck).  Applicatiecode gebruikt dit
nooit rechtstreeks; de storage factory levert repositories conform de
protocols uit ``database/interfaces.py``.
"""

from __future__ import annotations

import logging

from database.connection import PostgresPool, mask_dsn, validate_dsn
from database.errors import MigrationError, StorageUnavailableError
from database.postgres.migrator import DEFAULT_MIGRATIONS_DIR, Migrator
from database.postgres.repositories.action_repository import (
    PostgresActionRepository,
)
from database.postgres.repositories.analysis_repository import (
    PostgresAnalysisRepository,
)
from database.postgres.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from database.postgres.repositories.memory_repository import (
    PostgresMemoryRepository,
)
from database.postgres.repositories.template_repository import (
    PostgresTemplateRepository,
)

logger = logging.getLogger("ai_discord_builder.database.postgres")


class PostgresBackend:
    name = "postgres"

    def __init__(
        self,
        dsn: str,
        min_size: int = 1,
        max_size: int = 10,
        migrate_on_startup: bool = True,
        migrations_dir: str | None = None,
    ) -> None:
        self._dsn = validate_dsn(dsn)  # fail vroeg, niet na Discord-login
        self._migrate_on_startup = migrate_on_startup
        self._pool = PostgresPool(
            self._dsn,
            min_size=min_size,
            max_size=max_size,
        )
        self._migrator = Migrator(
            self._pool,
            directory=migrations_dir or DEFAULT_MIGRATIONS_DIR,
        )

        self.actions = PostgresActionRepository(self._pool)
        self.conversations = PostgresConversationRepository(self._pool)
        self.memories = PostgresMemoryRepository(self._pool)
        self.analysis = PostgresAnalysisRepository(self._pool)
        self.templates = PostgresTemplateRepository(self._pool)

    async def initialize(self) -> None:
        """Bereikbaarheid, migraties en schema controleren vóór bot-start."""

        logger.info("Initializing PostgreSQL backend (%s)", mask_dsn(self._dsn))

        # 1. Verbinden faalt hier direct en duidelijk.
        await self._pool.open()

        # 2. Migraties: automatisch of strict verifiëren dat niets ontbreekt.
        if self._migrate_on_startup:
            applied = await self._migrator.migrate()
            if applied:
                names = ", ".join(
                    f"{migration.version}_{migration.name}"
                    for migration in applied
                )
                logger.info("Applied database migrations: %s", names)
        else:
            pending = await self._migrator.pending_migrations()
            if pending:
                names = ", ".join(
                    f"{migration.version}_{migration.name}"
                    for migration in pending
                )
                raise MigrationError(
                    "Database schema is not up to date "
                    f"(pending: {names}). Run 'python -m database migrate' "
                    "or set DB_MIGRATE_ON_STARTUP=true."
                )

        # 3. Definitieve ping zodat de bot nooit half-start.
        await self._pool.ping()
        logger.info("PostgreSQL backend ready")

    async def close(self) -> None:
        await self._pool.close()

    async def healthcheck(self) -> tuple[bool, str]:
        try:
            await self._pool.ping()
        except StorageUnavailableError as exc:
            return False, str(exc)
        except Exception as exc:  # healthchecks nooit laten crashen
            return False, f"PostgreSQL healthcheck failed: {exc}"
        return True, "postgres ok"
