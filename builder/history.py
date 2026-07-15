"""
builder/history.py

Persistent Discord action history.

This file acts as an interface between
the builder system and the Supabase database.

Storage:
- Supabase PostgreSQL
- actions table

Supports:
- Save actions
- Get history
- Get latest actions
- Remove actions after rollback
- Clear guild history
"""

import logging

from database.actions import (
    add_action as db_add_action,
    get_last_actions as db_get_last_actions,
    remove_last_actions as db_remove_last_actions
)

from database.supabase import supabase


logger = logging.getLogger(
    "ai_discord_builder.history"
)



# =====================================
# ADD ACTION
# =====================================

def add_action(
    guild_id: int,
    action: dict,
    user_id: int | None = None
):
    """
    Save completed builder action.
    """

    try:

        db_add_action(
            guild_id,
            action,
            user_id
        )


        logger.info(
            "Saved action %s for guild %s",
            action.get("type"),
            guild_id
        )


    except Exception:

        logger.exception(
            "Failed adding action"
        )



# =====================================
# GET ALL HISTORY
# =====================================

def get_history(
    guild_id: int
) -> list:
    """
    Get complete guild action history.
    """

    try:

        result = (
            supabase.table(
                "actions"
            )
            .select("*")
            .eq(
                "guild_id",
                str(guild_id)
            )
            .order(
                "created_at",
                desc=False
            )
            .execute()
        )


        return [
            {
                "action": row["data"],
                "timestamp": row["created_at"]
            }
            for row in result.data
        ]


    except Exception:

        logger.exception(
            "Failed loading history"
        )

        return []



# =====================================
# GET LAST ACTIONS
# =====================================

def get_last_actions(
    guild_id: int,
    amount: int = 10
) -> list:
    """
    Get latest actions for rollback.

    Returns oldest -> newest
    """

    if amount <= 0:

        return []


    try:

        actions = db_get_last_actions(
            guild_id,
            amount
        )


        # Database returns newest first
        # Rollback needs oldest first

        return list(
            reversed(actions)
        )


    except Exception:

        logger.exception(
            "Failed getting latest actions"
        )

        return []



# =====================================
# REMOVE ACTIONS
# =====================================

def remove_last_actions(
    guild_id: int,
    amount: int = 1
):
    """
    Remove actions after successful rollback.
    """

    try:

        db_remove_last_actions(
            guild_id,
            amount
        )


        logger.info(
            "Removed %s actions from guild %s",
            amount,
            guild_id
        )


    except Exception:

        logger.exception(
            "Failed removing actions"
        )



# =====================================
# CLEAR HISTORY
# =====================================

def clear_history(
    guild_id: int
):
    """
    Delete all stored actions from guild.
    """

    try:

        supabase.table(
            "actions"
        ).delete().eq(
            "guild_id",
            str(guild_id)
        ).execute()


        logger.info(
            "Cleared history for guild %s",
            guild_id
        )


    except Exception:

        logger.exception(
            "Failed clearing history"
        )



# =====================================
# COUNT
# =====================================

def get_history_count(
    guild_id: int
) -> int:
    """
    Return amount of stored actions.
    """

    return len(
        get_history(
            guild_id
        )
    )