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


# =========================
# MEMORY STORAGE
# =========================

_history = {}





def add_action(
    guild_id: int,
    action: dict
):
    """
    Saves completed action.

    Uses deepcopy so later changes do not modify history.
    """

    if guild_id not in _history:

        _history[guild_id] = []



    _history[guild_id].append(
        {
            "action": copy.deepcopy(action),
            "timestamp": time.time()
        }
    )





def get_history(
    guild_id: int
) -> list:

    return _history.get(
        guild_id,
        []
    )





def get_last_actions(
    guild_id: int,
    amount: int = 10
) -> list:

    history = get_history(
        guild_id
    )


    return history[-amount:]





def remove_last_actions(
    guild_id: int,
    amount: int = 1
):

    if guild_id not in _history:
        return



    _history[guild_id] = (
        _history[guild_id][:-amount]
    )





def clear_history(
    guild_id: int
):

    if guild_id in _history:

        del _history[guild_id]