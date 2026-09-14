"""PostgreSQL implementation of the ActionRepository protocol.

Persists rollback history.  Every query is parameterized and always scoped
to one guild: records from other guilds can never be read or deleted.
"""

from __future__ import annotations

import json
from typing import Any

from database.postgres.repositories.base import (
    BasePostgresRepository,
    loads_json,
    to_iso,
)

_INSERT_ACTION = """
insert into actions (guild_id, user_id, action_type, data)
values ($1, $2, $3, $4::jsonb)
"""

_SELECT_LAST_ACTIONS = """
select data, created_at
from actions
where guild_id = $1
order by created_at desc, id desc
limit $2
"""

_SELECT_HISTORY = """
select data, created_at
from actions
where guild_id = $1
order by created_at asc, id asc
"""

_DELETE_LAST_ACTIONS = """
delete from actions
where id in (
    select id
    from actions
    where guild_id = $1
    order by created_at desc, id desc
    limit $2
)
"""

_DELETE_HISTORY = """
delete from actions
where guild_id = $1
"""


class PostgresActionRepository(BasePostgresRepository):
    async def add_action(
        self,
        guild_id: str,
        action: dict,
        user_id: str | None = None,
    ) -> None:
        async with await self._acquire() as conn:
            await conn.execute(
                _INSERT_ACTION,
                str(guild_id),
                str(user_id) if user_id else None,
                action.get("type"),
                json.dumps(action, default=str),
            )

    async def get_last_actions(
        self,
        guild_id: str,
        amount: int = 10,
    ) -> list[dict[str, Any]]:
        """Newest first (mirrors the behavior builder/history relies on)."""

        if amount <= 0:
            return []

        async with await self._acquire() as conn:
            rows = await conn.fetch(
                _SELECT_LAST_ACTIONS,
                str(guild_id),
                int(amount),
            )
        return [self._to_entry(row) for row in rows]

    async def get_history(self, guild_id: str) -> list[dict[str, Any]]:
        """Full history, oldest first."""

        async with await self._acquire() as conn:
            rows = await conn.fetch(_SELECT_HISTORY, str(guild_id))
        return [self._to_entry(row) for row in rows]

    async def remove_last_actions(
        self,
        guild_id: str,
        amount: int = 1,
    ) -> None:
        if amount <= 0:
            return

        async with await self._acquire() as conn:
            await conn.execute(
                _DELETE_LAST_ACTIONS,
                str(guild_id),
                int(amount),
            )

    async def clear_history(self, guild_id: str) -> None:
        async with await self._acquire() as conn:
            await conn.execute(_DELETE_HISTORY, str(guild_id))

    @staticmethod
    def _to_entry(row: Any) -> dict[str, Any]:
        return {
            "action": loads_json(row["data"], default={}),
            "timestamp": to_iso(row["created_at"]),
        }
