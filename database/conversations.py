import logging

from database.supabase import supabase


logger = logging.getLogger(
    "ai_discord_builder.conversations"
)



def save_conversation(
    guild_id: int,
    user_id: int,
    username: str,
    message: str,
    response: str
):

    try:

        supabase.table(
            "conversations"
        ).insert(
            {
                "guild_id": str(guild_id),
                "user_id": str(user_id),
                "username": username,
                "message": message,
                "response": response
            }
        ).execute()


        logger.info(
            "Saved conversation for %s",
            username
        )


    except Exception:

        logger.exception(
            "Failed saving conversation"
        )



def get_recent_conversations(
    guild_id: int,
    limit: int = 10
):

    try:

        result = (
            supabase.table(
                "conversations"
            )
            .select("*")
            .eq(
                "guild_id",
                str(guild_id)
            )
            .order(
                "created_at",
                desc=True
            )
            .limit(
                limit
            )
            .execute()
        )


        return result.data


    except Exception:

        logger.exception(
            "Failed loading conversations"
        )

        return []