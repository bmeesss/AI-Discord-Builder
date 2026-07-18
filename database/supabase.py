import os
import logging

from supabase import create_client, Client

logger = logging.getLogger("ai_discord_builder.supabase")

SUPABASE_URL = os.getenv(
    "SUPABASE_URL"
)

SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY"
)


supabase: Client | None = None


if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_KEY
    )
else:
    logger.warning(
        "Supabase is not configured; database features are disabled."
    )


def get_supabase() -> Client | None:
    return supabase
