"""
Base repository helpers.
"""

from __future__ import annotations

from database.supabase import get_supabase


class RepositoryUnavailable(Exception):
    pass


class BaseRepository:
    @property
    def client(self):
        client = get_supabase()
        if client is None:
            raise RepositoryUnavailable("Supabase is not configured.")
        return client
