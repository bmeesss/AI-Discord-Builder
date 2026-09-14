-- AI Discord Builder — core persistence tables (self-hosted PostgreSQL).
--
-- Mirrors the tables the application actually uses today via the Supabase
-- backend.  Note: the Supabase SQL in this repository never created the
-- `conversations` table (it only ALTERed it); this migration defines it
-- completely, including the intelligence columns the application writes.

create table if not exists actions (
    id bigint generated always as identity primary key,
    guild_id text not null,
    user_id text,
    action_type text,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists actions_guild_created_idx
    on actions (guild_id, created_at desc);

create table if not exists conversations (
    id uuid primary key default gen_random_uuid(),
    guild_id text not null,
    user_id text,
    username text,
    message text,
    response text,
    ai_plan jsonb,
    result jsonb,
    feedback jsonb,
    prompt_version_id uuid,
    risk text,
    selected_template text,
    error text,
    created_at timestamptz not null default now()
);

create index if not exists conversations_guild_created_idx
    on conversations (guild_id, created_at desc);
