"""Supabase → PostgreSQL migration tooling.

Commands (via ``python -m database``):

* ``export-supabase``  — paginated, read-only snapshot of the Supabase tables;
* ``verify-export``    — offline validation of such a snapshot;
* ``import-postgres``  — additive, idempotent import into PostgreSQL.

The tool only reads from Supabase and only inserts into PostgreSQL: it never
deletes, truncates or drops anything, never switches the active backend and
never touches Discord.
"""

from __future__ import annotations

from database.migration import (
    cli,
    export,
    import_postgres,
    manifest,
    model,
    secrets,
    validate,
)

__all__ = [
    "cli",
    "export",
    "import_postgres",
    "manifest",
    "model",
    "secrets",
    "validate",
]
