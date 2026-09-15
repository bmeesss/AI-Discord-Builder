"""In-memory PostgreSQL double for the importer unit tests.

The fake understands exactly the statements the importer (and the migration
runner) issue and emulates the parts of PostgreSQL that matter here:

* primary key / unique constraint conflicts (``on conflict do nothing``);
* the partial unique index on active memories;
* foreign keys (``memory_embeddings.memory_id``,
  ``conversations.prompt_version_id``);
* ``identity`` id generation for ``actions``;
* per-batch transactions with rollback.

Everything else is recorded so tests can assert on the SQL that was used —
for example that no destructive statement and no interpolated value ever
reaches the database.
"""

from __future__ import annotations

import re
from typing import Any

from database.migration.model import IMPORT_ORDER, TABLES, TableSpec
from database.postgres.migrator import load_migrations


class FakeUniqueViolation(Exception):
    sqlstate = "23505"


class FakeForeignKeyViolation(Exception):
    sqlstate = "23503"


class FakeNotNullViolation(Exception):
    sqlstate = "23502"


class FakeTransaction:
    def __init__(self, conn: "FakePgConnection") -> None:
        self._conn = conn
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> "FakeTransaction":
        self._conn.begin()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._conn.commit()
            self.commits += 1
        else:
            self._conn.rollback()
            self.rollbacks += 1
        return False


def _normalised_sql(sql: str) -> str:
    return " ".join(sql.split())


class FakePgConnection:
    """Executes the importer's statements against ``FakePg``."""

    def __init__(self, db: "FakePg") -> None:
        self.db = db
        self.executed: list[tuple[str, tuple]] = []
        self.fetched: list[tuple[str, tuple]] = []
        self.executemany_calls: list[tuple[str, list]] = []
        self.transactions: list[FakeTransaction] = []
        self.fail_on_executemany: Exception | None = None
        self.fail_call_index: int | None = None
        self._executemany_count = 0
        self._pending: list[tuple[str, dict]] = []
        self._depth = 0

    # -- transaction plumbing ---------------------------------------------

    def begin(self) -> None:
        self._depth += 1
        self._pending = []

    def commit(self) -> None:
        self._depth = max(0, self._depth - 1)
        self._pending = []

    def rollback(self) -> None:
        for table, row in self._pending:
            self.db.tables[table].remove(row)
        self._pending = []
        self._depth = max(0, self._depth - 1)

    def transaction(self) -> FakeTransaction:
        transaction = FakeTransaction(self)
        self.transactions.append(transaction)
        return transaction

    # -- statements --------------------------------------------------------

    async def execute(self, sql: str, *params: Any) -> str:
        self.executed.append((_normalised_sql(sql), params))
        return "OK"

    async def executemany(self, sql: str, params: Any) -> None:
        self._executemany_count += 1
        self.executemany_calls.append((_normalised_sql(sql), list(params)))
        if (
            self.fail_on_executemany is not None
            and (
                self.fail_call_index is None
                or self.fail_call_index == self._executemany_count
            )
        ):
            raise self.fail_on_executemany
        self.db.apply_insert(_normalised_sql(sql), list(params), self)

    async def fetch(self, sql: str, *params: Any) -> list[dict]:
        self.fetched.append((_normalised_sql(sql), params))
        return self.db.query(_normalised_sql(sql), params)

    async def fetchrow(self, sql: str, *params: Any) -> dict | None:
        rows = await self.fetch(sql, *params)
        return rows[0] if rows else None

    async def fetchval(self, sql: str, *params: Any) -> Any:
        row = await self.fetchrow(sql, *params)
        return list(row.values())[0] if row else None


class FakeAcquire:
    def __init__(self, conn: FakePgConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakePgConnection:
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeInnerPool:
    def __init__(self, conn: FakePgConnection) -> None:
        self.conn = conn

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)


class FakePgPool:
    """Drop-in for ``database.connection.PostgresPool`` in unit tests."""

    def __init__(self, db: "FakePg | None" = None) -> None:
        self.db = db or FakePg()
        self.inner = FakeInnerPool(self.db.connection)
        self.closed = False
        self.pings = 0

    async def pool(self) -> FakeInnerPool:
        return self.inner

    async def ping(self) -> None:
        self.pings += 1

    async def close(self) -> None:
        self.closed = True


# --------------------------------------------------------------------------
# The in-memory database
# --------------------------------------------------------------------------

INSERT_RE = re.compile(
    r"^insert into (?P<table>\w+) \((?P<columns>[^)]*)\) values "
    r"\((?P<values>.*?)\)(?P<tail>.*)$"
)
COUNT_RE = re.compile(r"^select count\(\*\) as total from (?P<table>\w+)$")
NULL_COUNT_RE = re.compile(
    r"^select count\(\*\) as total from (?P<table>\w+) "
    r"where (?P<column>\w+) is null$"
)
GUILD_SCOPE_RE = re.compile(
    r"^select count\(\*\) as total from (?P<table>\w+) "
    r"where guild_id is null or guild_id = ''$"
)
ORPHAN_RE = re.compile(
    r"^select count\(\*\) as total from (?P<table>\w+) child "
    r"where child\.(?P<column>\w+) is not null and not exists "
    r"\(select 1 from (?P<ref>\w+) parent "
    r"where parent\.(?P<ref_column>\w+) = child\.(?P<column2>\w+)\)$"
)
IDS_RE = re.compile(
    r"^select id from (?P<table>\w+) where id = any\(\$1::uuid\[\]\)$"
)


class FakePg:
    """Tables, constraints and query emulation for the migration importer."""

    def __init__(self, applied_migrations: bool = True) -> None:
        self.tables: dict[str, list[dict]] = {name: [] for name in IMPORT_ORDER}
        self._identity: dict[str, int] = {"actions": 0}
        self._connection = FakePgConnection(self)
        self.applied = (
            {
                migration.version: migration.checksum
                for migration in load_migrations()
            }
            if applied_migrations
            else {}
        )
        # Tables/columns reported by information_schema (schema-compat check).
        self.schema_columns: dict[str, dict[str, str]] = {
            name: {
                column.name: _data_type(column.kind)
                for column in TABLES[name].columns
            }
            for name in IMPORT_ORDER
        }

    @property
    def connection(self) -> FakePgConnection:
        return self._connection

    def pool(self) -> FakePgPool:
        return FakePgPool(self)

    # -- inserts -----------------------------------------------------------

    def apply_insert(
        self,
        sql: str,
        params: list[tuple],
        conn: FakePgConnection,
    ) -> None:
        match = INSERT_RE.match(sql)
        if not match:  # pragma: no cover - guards against unknown SQL
            raise AssertionError(f"fake database cannot run: {sql}")

        table = match.group("table")
        spec = TABLES[table]
        columns = [name.strip() for name in match.group("columns").split(",")]
        inserted: list[dict] = []

        for row_params in params:
            row = dict(zip(columns, row_params))
            self._assign_identity(spec, row)
            self._check_not_null(spec, row)
            if self._conflicts(spec, row):
                continue
            self._check_foreign_keys(spec, row)
            self.tables[table].append(row)
            inserted.append(row)
            conn._pending.append((table, row))

    def _assign_identity(self, spec: TableSpec, row: dict) -> None:
        if spec.id_policy == "regenerate":
            self._identity[spec.name] = self._identity.get(spec.name, 0) + 1
            row["id"] = self._identity[spec.name]

    def _check_not_null(self, spec: TableSpec, row: dict) -> None:
        for column in spec.columns:
            if not column.nullable and row.get(column.name) is None:
                raise FakeNotNullViolation(
                    f"null value in column {column.name!r} of {spec.name}"
                )

    def _conflicts(self, spec: TableSpec, row: dict) -> bool:
        existing = self.tables[spec.name]

        if any(
            other.get(spec.primary_key) == row.get(spec.primary_key)
            for other in existing
        ):
            return True

        if spec.name == "prompt_versions":
            return any(
                (other["name"], other["version"]) == (row["name"], row["version"])
                for other in existing
            )

        if spec.name == "memories" and row.get("deleted_at") is None:
            key = (
                row.get("guild_id"),
                row.get("user_id"),
                row.get("memory_type"),
                row.get("memory_key"),
            )
            if any(
                (
                    other.get("guild_id"),
                    other.get("user_id"),
                    other.get("memory_type"),
                    other.get("memory_key"),
                )
                == key
                and other.get("deleted_at") is None
                for other in existing
            ):
                raise FakeUniqueViolation(
                    "duplicate key value violates unique constraint "
                    "memories_unique_active_idx"
                )
        return False

    def _check_foreign_keys(self, spec: TableSpec, row: dict) -> None:
        for fk in spec.references:
            if fk.soft:
                continue
            value = row.get(fk.column)
            if value is None:
                continue
            parents = self.tables[fk.ref_table]
            if not any(parent.get("id") == value for parent in parents):
                raise FakeForeignKeyViolation(
                    f"insert or update on table {spec.name!r} violates "
                    f"foreign key constraint on {fk.column}"
                )

    # -- queries -----------------------------------------------------------

    def query(self, sql: str, params: tuple) -> list[dict]:
        if "schema_migrations" in sql:
            return [
                {"version": version, "checksum": checksum}
                for version, checksum in sorted(self.applied.items())
            ]

        if "information_schema.columns" in sql:
            wanted = set(params[0]) if params else set(IMPORT_ORDER)
            rows = []
            for table in sorted(wanted):
                for column, data_type in self.schema_columns.get(table, {}).items():
                    rows.append(
                        {
                            "table_name": table,
                            "column_name": column,
                            "data_type": data_type,
                            "is_nullable": "YES",
                        }
                    )
            return rows

        if sql.startswith("select name, version from prompt_versions"):
            names = set(params[0]) if params else set()
            return [
                {"name": row["name"], "version": row["version"]}
                for row in self.tables["prompt_versions"]
                if row["name"] in names
            ]

        if sql.startswith(
            "select guild_id, user_id, memory_type, memory_key from memories"
        ):
            guilds = set(params[0]) if params else set()
            return [
                {
                    "guild_id": row["guild_id"],
                    "user_id": row["user_id"],
                    "memory_type": row["memory_type"],
                    "memory_key": row["memory_key"],
                }
                for row in self.tables["memories"]
                if row.get("deleted_at") is None and row["guild_id"] in guilds
            ]

        if sql.startswith("select guild_id, user_id, action_type, data, created_at"):
            guilds = set(params[0]) if params else set()
            start, end = params[1], params[2]
            return [
                {
                    "guild_id": row["guild_id"],
                    "user_id": row["user_id"],
                    "action_type": row["action_type"],
                    "data": row["data"],
                    "created_at": row["created_at"],
                }
                for row in self.tables["actions"]
                if row["guild_id"] in guilds and start <= row["created_at"] <= end
            ]

        match = IDS_RE.match(sql)
        if match:
            wanted = set(params[0]) if params else set()
            return [
                {"id": row["id"]}
                for row in self.tables[match.group("table")]
                if row.get("id") in wanted
            ]

        match = COUNT_RE.match(sql)
        if match:
            return [{"total": len(self.tables[match.group("table")])}]

        match = NULL_COUNT_RE.match(sql)
        if match:
            table = match.group("table")
            column = match.group("column")
            return [
                {
                    "total": sum(
                        1 for row in self.tables[table]
                        if row.get(column) is None
                    )
                }
            ]

        match = GUILD_SCOPE_RE.match(sql)
        if match:
            table = match.group("table")
            return [
                {
                    "total": sum(
                        1
                        for row in self.tables[table]
                        if not row.get("guild_id")
                    )
                }
            ]

        match = ORPHAN_RE.match(sql)
        if match:
            table = match.group("table")
            column = match.group("column")
            ref = match.group("ref")
            parents = {row.get("id") for row in self.tables[ref]}
            return [
                {
                    "total": sum(
                        1
                        for row in self.tables[table]
                        if row.get(column) is not None
                        and row.get(column) not in parents
                    )
                }
            ]

        raise AssertionError(f"fake database does not understand SQL: {sql}")


def _data_type(kind: str) -> str:
    return {
        "uuid": "uuid",
        "text": "text",
        "jsonb": "jsonb",
        "timestamptz": "timestamp with time zone",
        "integer": "integer",
        "bigint": "bigint",
        "numeric": "numeric",
        "boolean": "boolean",
    }[kind]
