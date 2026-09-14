"""
Base repository helpers.
"""

from __future__ import annotations

from database.supabase import get_supabase


class RepositoryUnavailable(Exception):
    pass


class BaseRepository:
    """Supabase sync repository base.

    Optionally accepts an explicit client (used by the async Supabase
    backend facade).  Without one it falls back to the module-level client
    from ``database/supabase.py`` exactly as before.
    """

    def __init__(self, client=None) -> None:
        self._client_override = client

    @property
    def client(self):
        if self._client_override is not None:
            return self._client_override
        client = get_supabase()
        if client is None:
            raise RepositoryUnavailable("Supabase is not configured.")
        return client
