"""Database package — provider-neutrale storage-laag.

Applicatiecode gebruikt alleen ``get_storage()`` en de protocols uit
``database/interfaces.py``.  De gekozen backend (PostgreSQL of Supabase) is
onsichtbaar voor services, commands en builder-code.
"""

from __future__ import annotations

from database.errors import (
    MigrationError,
    StorageError,
    StorageNotConfiguredError,
    StorageUnavailableError,
)
from database.factory import create_storage, resolve_backend
from database.storage import Storage

__all__ = [
    "MigrationError",
    "Storage",
    "StorageError",
    "StorageNotConfiguredError",
    "StorageUnavailableError",
    "close_storage",
    "create_storage",
    "get_storage",
    "initialize_storage",
    "resolve_backend",
    "set_storage",
]

_storage: Storage | None = None


def get_storage() -> Storage:
    """Return the active storage, creating it lazily without connecting."""

    global _storage
    if _storage is None:
        _storage = create_storage()
    return _storage


async def initialize_storage() -> Storage:
    """Connect, verify reachability and run migrations.  Fails loudly."""

    global _storage
    storage = _storage if _storage is not None else create_storage()
    await storage.initialize()
    _storage = storage
    return storage


async def close_storage() -> None:
    """Close connections gracefully (idempotent)."""

    global _storage
    storage, _storage = _storage, None
    if storage is not None:
        await storage.close()


def set_storage(storage: Storage | None) -> None:
    """Test hook: inject a fake storage or reset the singleton."""

    global _storage
    _storage = storage
