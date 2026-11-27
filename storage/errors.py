"""Shared storage-layer exceptions.

Storage is a plain local JSON-file store (no database).  These errors never
decide whether a Discord action is allowed; the Discord permission/executor
layer remains responsible for authorization.  Storage only persists state
and history.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base error for the storage layer."""


class StorageNotConfiguredError(StorageError):
    """A required configuration value is missing or invalid."""


class StorageUnavailableError(StorageError):
    """Local storage cannot be used (e.g. the data directory is unusable)."""
