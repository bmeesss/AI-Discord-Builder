import json

from database.supabase import supabase



def add_action(
    guild_id: int,
    action: dict,
    user_id: int | None = None
):

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





def get_last_actions(
    guild_id: int,
    amount: int = 10
):

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


    actions = []


    for row in result.data:

        actions.append(
            {
                "action": row["data"],
                "timestamp": row["created_at"]
            }
        )


    return actions





def remove_last_actions(
    guild_id: int,
    amount: int = 1
):

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