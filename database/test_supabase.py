"""Opt-in Supabase integration smoke test.

This is intentionally skipped unless both Supabase settings and an explicit
flag are present. It must never perform a network call during normal test
collection.
"""

from __future__ import annotations

import os
import unittest

from database.supabase import get_supabase


@unittest.skipUnless(
    os.getenv("RUN_SUPABASE_TESTS") == "1"
    and bool(os.getenv("SUPABASE_URL"))
    and bool(os.getenv("SUPABASE_KEY")),
    "Set RUN_SUPABASE_TESTS=1 and Supabase credentials to enable this test.",
)
class SupabaseIntegrationTests(unittest.TestCase):
    def test_conversations_table_is_reachable(self):
        client = get_supabase()
        self.assertIsNotNone(client)
        response = client.table("conversations").select("*").limit(1).execute()
        self.assertIsNotNone(response)


if __name__ == "__main__":
    unittest.main()
