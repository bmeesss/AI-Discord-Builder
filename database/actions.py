"""Backwards-compatible async wrappers for action history.

The canonical implementations live behind the storage factory
(``database/interfaces.py``); these wrappers keep the historical import
paths working for existing code while delegating to the configured backend
(PostgreSQL or Supabase).
"""

from __future__ import annotations

from typing import Any

from database import get_storage


async def add_action(
    guild_id: int,
    action: dict,
    user_id: int | None = None,
) -> None:
    await get_storage().actions.add_action(
        str(guild_id),
        action,
        str(user_id) if user_id else None,
    )


async def get_last_actions(
    guild_id: int,
    amount: int = 10,
) -> list[dict[str, Any]]:
    return await get_storage().actions.get_last_actions(
        str(guild_id),
        amount,
    )


async def remove_last_actions(
    guild_id: int,
    amount: int = 1,
) -> None:
    await get_storage().actions.remove_last_actions(
        str(guild_id),
        amount,
    )
