"""Storage package — databasevrije JSON-bestandsopslag.

Applicatiecode gebruikt uitsluitend ``get_storage()`` en de protocols uit
``storage/interfaces.py``.  De backend is een lokale JSON-file store (zie
``storage/json_store.py``): geen PostgreSQL, geen Supabase, geen SQLite,
geen externe diensten, geen migraties.
"""

from __future__ import annotations

from storage.errors import (
    StorageError,
    StorageNotConfiguredError,
    StorageUnavailableError,
)
from storage.json_store import create_json_storage
from storage.storage import Storage

__all__ = [
    "Storage",
    "StorageError",
    "StorageNotConfiguredError",
    "StorageUnavailableError",
    "close_storage",
    "create_json_storage",
    "get_storage",
    "initialize_storage",
    "set_storage",
]

_storage: Storage | None = None


def get_storage() -> Storage:
    """Return the active storage, creating it lazily (no I/O until used)."""

    global _storage
    if _storage is None:
        _storage = create_json_storage()
    return _storage


async def initialize_storage() -> Storage:
    """Create the data directory and verify it is writable.  Fails loudly."""

    global _storage
    storage = _storage if _storage is not None else create_json_storage()
    await storage.initialize()
    _storage = storage
    return storage


async def close_storage() -> None:
    """Close the storage (idempotent; JSON files need no teardown)."""

    global _storage
    storage, _storage = _storage, None
    if storage is not None:
        await storage.close()


def set_storage(storage: Storage | None) -> None:
    """Test hook: inject a fake storage or reset the singleton."""

    global _storage
    _storage = storage
