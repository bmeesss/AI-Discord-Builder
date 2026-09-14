"""Storage factory: kiest de backend via configuratie.

Regels:

1. Expliciete ``DATABASE_BACKEND`` (``postgres`` of ``supabase``) wint altijd.
2. Zonder expliciete keuze: bestaande deployments die alleen Supabase-keys
   hebben (en geen ``DATABASE_URL``) blijven automatisch Supabase gebruiken —
   niets breekt bij een upgrade.
3. Anders is ``postgres`` de standaard (aanbevolen self-hosting backend).
"""

from __future__ import annotations

import logging

import config
from database.errors import StorageNotConfiguredError
from database.postgres.backend import PostgresBackend
from database.storage import Storage
from database.supabase_backend import SupabaseBackend

logger = logging.getLogger("ai_discord_builder.database.factory")

# Single source of truth for backend names lives in config.py.
VALID_DATABASE_BACKENDS = config.VALID_DATABASE_BACKENDS
DEFAULT_DATABASE_BACKEND = "postgres"


def _setting(environ: dict[str, str] | None, name: str) -> str | None:
    if environ is not None:
        return environ.get(name)
    return getattr(config, name)


def resolve_backend(environ: dict[str, str] | None = None) -> str:
    explicit = (_setting(environ, "DATABASE_BACKEND") or "").strip().lower()

    if explicit:
        if explicit not in VALID_DATABASE_BACKENDS:
            supported = ", ".join(sorted(VALID_DATABASE_BACKENDS))
            raise StorageNotConfiguredError(
                f"Unknown DATABASE_BACKEND={explicit!r}. "
                f"Supported backends: {supported}."
            )
        return explicit

    supabase_configured = bool(
        _setting(environ, "SUPABASE_URL") and _setting(environ, "SUPABASE_KEY")
    )
    postgres_configured = bool(_setting(environ, "DATABASE_URL"))

    if supabase_configured and not postgres_configured:
        logger.info(
            "DATABASE_BACKEND is not set; using Supabase because only "
            "SUPABASE_URL/SUPABASE_KEY are configured. Set "
            "DATABASE_BACKEND explicitly to silence this message."
        )
        return "supabase"

    return DEFAULT_DATABASE_BACKEND


def create_storage(environ: dict[str, str] | None = None) -> Storage:
    """Build the configured storage backend without connecting.

    Connections and migrations happen in ``Storage.initialize()``; building
    is cheap and safe to do lazily (e.g. in tests with injected fakes).
    """

    backend = resolve_backend(environ)

    if backend == "postgres":
        postgres_backend = PostgresBackend(
            dsn=_setting(environ, "DATABASE_URL") or "",
            min_size=_pool_size(environ, "DB_POOL_MIN_SIZE", default=1),
            max_size=_pool_size(environ, "DB_POOL_MAX_SIZE", default=10),
            migrate_on_startup=_migrate_on_startup(environ),
        )
        return Storage(
            backend="postgres",
            actions=postgres_backend.actions,
            conversations=postgres_backend.conversations,
            memories=postgres_backend.memories,
            analysis=postgres_backend.analysis,
            templates=postgres_backend.templates,
            _lifecycle=postgres_backend,
        )

    supabase_backend = SupabaseBackend(
        url=_setting(environ, "SUPABASE_URL"),
        key=_setting(environ, "SUPABASE_KEY"),
    )
    return Storage(
        backend="supabase",
        actions=supabase_backend.actions,
        conversations=supabase_backend.conversations,
        memories=supabase_backend.memories,
        analysis=supabase_backend.analysis,
        templates=supabase_backend.templates,
        _lifecycle=supabase_backend,
    )


def _pool_size(
    environ: dict[str, str] | None,
    name: str,
    default: int,
) -> int:
    value = _setting(environ, name)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise StorageNotConfiguredError(
            f"Environment variable {name} must be an integer."
        )
    if parsed < 1:
        raise StorageNotConfiguredError(
            f"Environment variable {name} must be >= 1."
        )
    return parsed


def _migrate_on_startup(environ: dict[str, str] | None) -> bool:
    if environ is not None:
        value = environ.get("DB_MIGRATE_ON_STARTUP")
        if value is None:
            return True
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(config.DB_MIGRATE_ON_STARTUP)
