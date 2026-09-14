-- AI Discord Builder — intelligence tables (self-hosted PostgreSQL).
--
-- Port of database/migrations/001_intelligence_tables.sql (the Supabase
-- variant) so both backends expose the same schema.  The trailing
-- `alter table conversations` from the Supabase file is not needed here:
-- migration 001 already creates those columns.

create table if not exists memories (
    id uuid primary key default gen_random_uuid(),
    guild_id text not null,
    user_id text,
    memory_key text not null,
    memory_value text not null,
    memory_type text not null default 'preference',
    confidence numeric(4, 3) not null default 0.500,
    source text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint memories_confidence_range check (
        confidence >= 0
        and confidence <= 1
    )
);

create index if not exists memories_guild_user_idx
    on memories (guild_id, user_id)
    where deleted_at is null;

create index if not exists memories_key_idx
    on memories (guild_id, memory_key)
    where deleted_at is null;

create unique index if not exists memories_unique_active_idx
    on memories (
        guild_id,
        user_id,
        memory_type,
        memory_key
    )
    nulls not distinct
    where deleted_at is null;

create table if not exists memory_embeddings (
    id uuid primary key default gen_random_uuid(),
    memory_id uuid not null references memories(id) on delete cascade,
    provider text,
    model text,
    embedding jsonb,
    created_at timestamptz not null default now()
);

create table if not exists conversation_summaries (
    id uuid primary key default gen_random_uuid(),
    guild_id text not null,
    user_id text,
    summary text not null,
    goals jsonb not null default '[]'::jsonb,
    preferences jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

create index if not exists conversation_summaries_guild_idx
    on conversation_summaries (guild_id, updated_at desc)
    where deleted_at is null;

create table if not exists server_analysis (
    id uuid primary key default gen_random_uuid(),
    guild_id text not null,
    health_score integer not null,
    issues jsonb not null default '[]'::jsonb,
    recommendations jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint server_analysis_score_range check (
        health_score >= 0
        and health_score <= 100
    )
);

create index if not exists server_analysis_guild_idx
    on server_analysis (guild_id, created_at desc)
    where deleted_at is null;

create table if not exists feedback (
    id uuid primary key default gen_random_uuid(),
    guild_id text not null,
    user_id text,
    conversation_id uuid,
    execution_id uuid,
    rating integer,
    comment text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint feedback_rating_range check (
        rating is null
        or (
            rating >= 1
            and rating <= 5
        )
    )
);

create index if not exists feedback_guild_idx
    on feedback (guild_id, created_at desc)
    where deleted_at is null;

create table if not exists templates (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    description text not null default '',
    category text not null default 'general',
    version text not null default '1',
    tags jsonb not null default '[]'::jsonb,
    recommended_for jsonb not null default '[]'::jsonb,
    member_min integer,
    member_max integer,
    actions jsonb not null default '[]'::jsonb,
    enabled boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

create index if not exists templates_enabled_idx
    on templates (enabled, category)
    where deleted_at is null;

create table if not exists prompt_versions (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    version text not null,
    provider text,
    model text,
    system_prompt text not null,
    schema jsonb not null default '{}'::jsonb,
    active boolean not null default false,
    notes text,
    created_at timestamptz not null default now(),
    deleted_at timestamptz,
    unique (name, version)
);

create index if not exists prompt_versions_active_idx
    on prompt_versions (name, active)
    where deleted_at is null;

alter table conversations
    add constraint conversations_prompt_version_fk
    foreign key (prompt_version_id) references prompt_versions(id);
