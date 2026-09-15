"""Shared storage-layer exceptions.

These errors never decide whether a Discord action is allowed; the Discord
permission/executor layer remains responsible for authorization.  Storage
only persists state and history.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base error for the storage layer."""


class StorageNotConfiguredError(StorageError):
    """A required backend configuration value is missing."""


class StorageUnavailableError(StorageError):
    """The selected backend cannot be reached or initialized."""


class MigrationError(StorageError):
    """A migration failed or the schema version table is inconsistent."""


class MigrationToolError(StorageError):
    """The Supabase → PostgreSQL migration tool could not (safely) continue.

    Raised for configuration problems, unreadable/invalid exports, missing
    migrations and schema mismatches.  Messages are safe to print: they never
    contain credentials and never imply that data was modified.
    """
