"""
builder/history.py

Persistent Discord action history.

This module is a thin async interface between the builder system and the
configured storage backend (PostgreSQL by default, Supabase optional).
Storage never decides whether an action is allowed; it only keeps rollback
history.

Supports:
- Save actions
- Get history
- Get latest actions
- Remove actions after rollback
- Clear guild history

Note (documented behavior): rollback iterates the returned entries reversed,
which means the oldest of the latest N actions is rolled back first.  This
pre-existing quirk is preserved intentionally; see docs/self-hosting.md.
"""

import logging

from database import get_storage


logger = logging.getLogger(
    "ai_discord_builder.history"
)


# =====================================
# ADD ACTION
# =====================================

async def add_action(
    guild_id: int,
    action: dict,
    user_id: int | None = None
):
    """
    Save completed builder action.
    """

    try:

        await get_storage().actions.add_action(
            str(guild_id),
            action,
            str(user_id) if user_id else None,
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

async def get_history(
    guild_id: int
) -> list:
    """
    Get complete guild action history.
    """

    try:

        return await get_storage().actions.get_history(
            str(guild_id)
        )


    except Exception:

        logger.exception(
            "Failed loading history"
        )

        return []



# =====================================
# GET LAST ACTIONS
# =====================================

async def get_last_actions(
    guild_id: int,
    amount: int = 10
) -> list:
    """
    Get latest actions for rollback.

    Returns newest first; rollback_actions reverses again before iterating,
    which preserves the exact pre-refactor behavior.
    """

    if amount <= 0:

        return []


    try:

        return await get_storage().actions.get_last_actions(
            str(guild_id),
            amount,
        )


    except Exception:

        logger.exception(
            "Failed getting latest actions"
        )

        return []



# =====================================
# REMOVE ACTIONS
# =====================================

async def remove_last_actions(
    guild_id: int,
    amount: int = 1
):
    """
    Remove actions after successful rollback.
    """

    try:

        await get_storage().actions.remove_last_actions(
            str(guild_id),
            amount,
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

async def clear_history(
    guild_id: int
):
    """
    Delete all stored actions from guild.
    """

    try:

        await get_storage().actions.clear_history(
            str(guild_id)
        )


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

async def get_history_count(
    guild_id: int
) -> int:
    """
    Return amount of stored actions.
    """

    history = await get_history(
        guild_id
    )

    return len(
        history
    )
