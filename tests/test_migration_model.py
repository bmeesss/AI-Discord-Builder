"""Datamodel tests: FK ordering, generated SQL, normalisation, schema parity."""

from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from database.migration.model import (
    IMPORT_ORDER,
    TABLES,
    deterministic_uuid,
    insert_sql,
    normalize_row,
    parse_timestamp,
    topological_order,
)
from database.postgres.migrator import DEFAULT_MIGRATIONS_DIR

_CREATE_TABLE = re.compile(r"create table if not exists (\w+) \(")
_NON_COLUMN = (
    "constraint",
    "primary key",
    "unique",
    "foreign key",
    "check",
)


def _table_body(text: str, start: int) -> str:
    """Return the body of a create-table block (parenthesis-balanced)."""

    depth = 1  # the opening parenthesis of the create-table block
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start:index]
    raise AssertionError("unbalanced parentheses in migration SQL")


def _split_top_level(body: str) -> list[str]:
    """Split a create-table body on commas that are not inside parentheses."""

    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for character in body:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(character)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def parse_migration_columns() -> dict[str, list[str]]:
    """Column names per table as declared in the shipped SQL migrations."""

    tables: dict[str, list[str]] = {}
    for path in sorted(Path(DEFAULT_MIGRATIONS_DIR).glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for match in _CREATE_TABLE.finditer(text):
            name = match.group(1)
            body = _table_body(text, match.end())
            columns: list[str] = []
            for part in _split_top_level(body):
                first = part.split()[0].lower()
                if first in _NON_COLUMN:
                    continue
                columns.append(first)
            tables.setdefault(name, []).extend(columns)
    return tables


class SchemaParityTests(unittest.TestCase):
    """The model must describe exactly what the migrations create."""

    def test_model_tables_match_migration_tables(self):
        self.assertEqual(
            set(TABLES),
            set(parse_migration_columns()),
        )

    def test_model_columns_match_migration_columns(self):
        migration_columns = parse_migration_columns()
        for name, spec in TABLES.items():
            self.assertEqual(
                list(spec.column_names),
                migration_columns[name],
                msg=f"column mismatch for {name}",
            )

    def test_foreign_keys_follow_the_real_schema(self):
        spec = TABLES["conversations"]
        fk = spec.foreign_key_for("prompt_version_id")
        self.assertIsNotNone(fk)
        self.assertEqual(fk.ref_table, "prompt_versions")
        self.assertFalse(fk.soft)

        spec = TABLES["memory_embeddings"]
        fk = spec.foreign_key_for("memory_id")
        self.assertIsNotNone(fk)
        self.assertEqual(fk.ref_table, "memories")
        self.assertEqual(fk.on_delete, "cascade")

    def test_feedback_reference_is_soft(self):
        fk = TABLES["feedback"].foreign_key_for("conversation_id")
        self.assertIsNotNone(fk)
        self.assertTrue(fk.soft, "feedback.conversation_id has no FK constraint")


class ImportOrderTests(unittest.TestCase):
    def test_topological_order_satisfies_dependencies(self):
        order = topological_order()
        self.assertEqual(sorted(order), sorted(TABLES))
        for name in order:
            for dependency in TABLES[name].dependencies:
                self.assertLess(
                    order.index(dependency),
                    order.index(name),
                )

    def test_documented_order_satisfies_every_foreign_key(self):
        """Even soft references must be imported after their parent."""

        for name in IMPORT_ORDER:
            for fk in TABLES[name].references:
                self.assertLess(
                    IMPORT_ORDER.index(fk.ref_table),
                    IMPORT_ORDER.index(name),
                    f"{fk.ref_table} must precede {name} ({fk.describe()})",
                )

    def test_parents_come_before_children(self):
        for name in IMPORT_ORDER:
            for dependency in TABLES[name].dependencies:
                self.assertLess(
                    IMPORT_ORDER.index(dependency),
                    IMPORT_ORDER.index(name),
                    f"{dependency} must be imported before {name}",
                )

    def test_prompt_versions_before_conversations(self):
        self.assertLess(
            IMPORT_ORDER.index("prompt_versions"),
            IMPORT_ORDER.index("conversations"),
        )

    def test_memories_before_memory_embeddings(self):
        self.assertLess(
            IMPORT_ORDER.index("memories"),
            IMPORT_ORDER.index("memory_embeddings"),
        )


class InsertSqlTests(unittest.TestCase):
    DESTRUCTIVE = ("drop ", "truncate ", "delete from", "update ", "alter ")

    def test_statements_are_parameterized(self):
        for name, spec in TABLES.items():
            sql = insert_sql(spec)
            self.assertIn(f"insert into {name} (", sql)
            for index in range(1, len(spec.insert_columns) + 1):
                self.assertIn(f"${index}", sql)
            self.assertNotIn("'%s'", sql)

    def test_no_destructive_sql(self):
        for spec in TABLES.values():
            sql = insert_sql(spec).lower()
            for keyword in self.DESTRUCTIVE:
                self.assertNotIn(keyword, sql)

    def test_actions_primary_key_is_not_inserted(self):
        sql = insert_sql(TABLES["actions"])
        self.assertNotIn("(id", sql)
        self.assertNotIn("on conflict", sql)

    def test_on_conflict_only_where_a_conflict_key_exists(self):
        for name, spec in TABLES.items():
            sql = insert_sql(spec)
            if spec.conflict_key:
                self.assertIn("on conflict (", sql)
                self.assertIn("do nothing", sql)
            else:
                self.assertNotIn("on conflict", sql, msg=name)

    def test_prompt_versions_conflict_key_is_the_business_key(self):
        sql = insert_sql(TABLES["prompt_versions"])
        self.assertIn("on conflict (name, version)", sql)

    def test_jsonb_columns_are_cast(self):
        sql = insert_sql(TABLES["actions"])
        self.assertIn("::jsonb", sql)


class NormalisationTests(unittest.TestCase):
    def test_valid_action_row(self):
        values, errors = normalize_row(
            TABLES["actions"],
            {
                "id": 7,
                "guild_id": "42",
                "user_id": None,
                "action_type": "create_channel",
                "data": {"type": "create_channel"},
                "created_at": "2026-01-01T10:00:00+00:00",
            },
        )
        self.assertEqual(errors, [])
        self.assertEqual(values["guild_id"], "42")
        self.assertEqual(values["created_at"].year, 2026)
        self.assertNotIn("id", values)

    def test_missing_required_field_is_reported(self):
        _values, errors = normalize_row(TABLES["actions"], {"guild_id": "42"})
        self.assertTrue(any("data" in error for error in errors))
        self.assertTrue(any("created_at" in error for error in errors))

    def test_invalid_uuid_is_reported(self):
        _values, errors = normalize_row(
            TABLES["feedback"],
            {
                "id": "not-a-uuid",
                "guild_id": "42",
                "execution_id": 12,
                "created_at": "2026-01-01T10:00:00+00:00",
            },
        )
        self.assertTrue(any("execution_id" in error for error in errors))

    def test_foreign_keys_are_resolved_by_the_importer_not_here(self):
        """FK columns accept legacy values; the importer remaps them."""

        values, errors = normalize_row(
            TABLES["conversations"],
            {
                "id": "not-a-uuid",
                "guild_id": "42",
                "prompt_version_id": 12,
                "created_at": "2026-01-01T10:00:00+00:00",
            },
        )
        self.assertEqual(errors, [])
        self.assertEqual(values["prompt_version_id"], 12)

    def test_check_constraints_are_enforced(self):
        _values, errors = normalize_row(
            TABLES["server_analysis"],
            {
                "id": str(deterministic_uuid("x", "y")),
                "guild_id": "42",
                "health_score": 500,
                "created_at": "2026-01-01T10:00:00+00:00",
            },
        )
        self.assertTrue(any("health_score" in error for error in errors))

        _values, errors = normalize_row(
            TABLES["memories"],
            {
                "guild_id": "42",
                "memory_key": "k",
                "memory_value": "v",
                "memory_type": "preference",
                "confidence": 4.2,
                "created_at": "2026-01-01T10:00:00+00:00",
            },
        )
        self.assertTrue(any("confidence" in error for error in errors))

    def test_confidence_becomes_decimal(self):
        values, errors = normalize_row(
            TABLES["memories"],
            {
                "guild_id": "42",
                "memory_key": "k",
                "memory_value": "v",
                "memory_type": "preference",
                "confidence": 0.9,
                "created_at": "2026-01-01T10:00:00+00:00",
            },
        )
        self.assertEqual(errors, [])
        self.assertEqual(values["confidence"], Decimal("0.900"))

    def test_naive_timestamps_are_utc(self):
        value, error = parse_timestamp("2026-01-01T10:00:00")
        self.assertIsNone(error)
        self.assertEqual(value.tzinfo, timezone.utc)

    def test_z_suffix_is_supported(self):
        value, error = parse_timestamp("2026-01-01T10:00:00Z")
        self.assertIsNone(error)
        self.assertEqual(value, datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc))

    def test_non_dict_row_is_invalid(self):
        _values, errors = normalize_row(TABLES["actions"], ["nope"])
        self.assertTrue(errors)


class DeterministicIdTests(unittest.TestCase):
    def test_same_input_gives_same_uuid(self):
        first = deterministic_uuid("conversations", 41)
        second = deterministic_uuid("conversations", 41)
        self.assertEqual(first, second)
        self.assertIsInstance(first, UUID)

    def test_different_tables_give_different_uuids(self):
        self.assertNotEqual(
            deterministic_uuid("conversations", 41),
            deterministic_uuid("memories", 41),
        )


if __name__ == "__main__":
    unittest.main()
