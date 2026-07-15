"""
builder/history.py

Stores Discord action history for rollback support.

Current:
- Memory storage
- Per guild history

Later:
- Replace with Supabase/PostgreSQL
"""

import time
import copy
import logging


logger = logging.getLogger(
    "ai_discord_builder.history"
)


# =========================
# MEMORY STORAGE
# =========================

_history = {}





def add_action(
    guild_id: int,
    action: dict
):
    """
    Save completed AI action.

    Uses deepcopy so future changes
    do not modify stored history.
    """

    if guild_id not in _history:

        _history[guild_id] = []



    _history[guild_id].append(
        {
            "action": copy.deepcopy(action),
            "timestamp": time.time()
        }
    )


    logger.info(
        "Saved history action for guild %s: %s",
        guild_id,
        action.get("type")
    )





def get_history(
    guild_id: int
) -> list:
    """
    Get complete history for guild.
    """

    return _history.get(
        guild_id,
        []
    )





def get_last_actions(
    guild_id: int,
    amount: int = 10
) -> list:
    """
    Get latest actions.
    """

    history = get_history(
        guild_id
    )


    if amount <= 0:

        return []


    return history[-amount:]





def remove_last_actions(
    guild_id: int,
    amount: int = 1
):
    """
    Remove latest actions after rollback.
    """

    if guild_id not in _history:

        return



    if amount <= 0:

        return



    _history[guild_id] = (
        _history[guild_id][:-amount]
    )



    logger.info(
        "Removed %s history actions for guild %s",
        amount,
        guild_id
    )





def clear_history(
    guild_id: int
):
    """
    Delete all history for guild.
    """

    if guild_id in _history:

        del _history[guild_id]


        logger.info(
            "Cleared history for guild %s",
            guild_id
        )





def get_history_count(
    guild_id: int
) -> int:
    """
    Returns amount of saved actions.
    """

    return len(
        _history.get(
            guild_id,
            []
        )
    )