from database.supabase import supabase


response = supabase.table(
    "conversations"
).select("*").execute()


print(response)