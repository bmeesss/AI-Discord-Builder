"""
builder/history.py

Persistent Discord action history.

Uses Supabase database instead of memory.
"""

import logging

from database.supabase import supabase


logger = logging.getLogger(
    "ai_discord_builder.history"
)



# =========================
# SAVE ACTION
# =========================

def add_action(
    guild_id: int,
    action: dict,
    user_id: int | None = None
):
    """
    Save completed AI action.
    """

    try:

        supabase.table(
            "actions"
        ).insert(
            {
                "guild_id": str(guild_id),
                "user_id": str(user_id) if user_id else None,
                "action_type": action.get("type"),
                "data": action
            }
        ).execute()


        logger.info(
            "Saved action %s for guild %s",
            action.get("type"),
            guild_id
        )


    except Exception:

        logger.exception(
            "Failed saving action"
        )





# =========================
# GET HISTORY
# =========================

def get_history(
    guild_id: int
) -> list:
    """
    Get all actions from guild.
    """

    try:

        result = (
            supabase.table("actions")
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





def get_last_actions(
    guild_id: int,
    amount: int = 10
) -> list:
    """
    Get latest actions.
    """

    if amount <= 0:
        return []


    try:

        result = (
            supabase.table("actions")
            .select("*")
            .eq(
                "guild_id",
                str(guild_id)
            )
            .order(
                "created_at",
                desc=True
            )
            .limit(amount)
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
            "Failed getting latest actions"
        )

        return []





# =========================
# REMOVE AFTER ROLLBACK
# =========================

def remove_last_actions(
    guild_id: int,
    amount: int = 1
):
    """
    Remove rolled back actions.
    """

    if amount <= 0:
        return


    try:

        rows = (
            supabase.table("actions")
            .select("id")
            .eq(
                "guild_id",
                str(guild_id)
            )
            .order(
                "created_at",
                desc=True
            )
            .limit(amount)
            .execute()
        )


        for row in rows.data:

            supabase.table(
                "actions"
            ).delete().eq(
                "id",
                row["id"]
            ).execute()



        logger.info(
            "Removed %s actions from guild %s",
            amount,
            guild_id
        )


    except Exception:

        logger.exception(
            "Failed removing actions"
        )





def clear_history(
    guild_id: int
):
    """
    Delete all guild actions.
    """

    try:

        supabase.table(
            "actions"
        ).delete().eq(
            "guild_id",
            str(guild_id)
        ).execute()


    except Exception:

        logger.exception(
            "Failed clearing history"
        )





def get_history_count(
    guild_id: int
) -> int:

    return len(
        get_history(guild_id)
    )