"""Backward-compatible lazy Supabase client accessor.

Kept for existing code and the opt-in Supabase smoke test.  The client is
created lazily so that importing the storage layer (or running with the
PostgreSQL backend) never instantiates — or warns about — Supabase.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("ai_discord_builder.supabase")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

_client = None


def get_supabase():
    global _client

    if _client is not None:
        return _client

    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    from supabase import create_client

    _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client
