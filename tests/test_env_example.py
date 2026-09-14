"""`.env.example` must document exactly the configuration the code uses.

Scans the project (excluding tests and this file) for every environment
variable that is read, and compares it with the keys present in
``.env.example`` (commented entries count as documented opt-ins).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS = (
    "ai",
    "builder",
    "commands",
    "database",
    "security",
    "services",
    "setup",
    "web",
)
SCAN_FILES = ("config.py", "main.py")

_PATTERNS = (
    re.compile(r"""os\.getenv\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
    re.compile(r"""os\.environ\.get\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
    re.compile(r"""(?:_env_bool|_env_int)\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
    re.compile(r"""configured\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
)

# Read by code but documented as commented-out optional lines in .env.example.
# (empty means: everything must be documented as an active line or via the
# commented-opt-in mechanism below)
_COMMENTED_OPT_INS = {"OPENAI_BASE_URL", "SUPABASE_URL", "SUPABASE_KEY"}

# Documented in .env.example but only consumed by Compose interpolation.
_COMPOSE_ONLY = {"OLLAMA_HOST_PORT"}

# Test-only flags; deliberately not part of .env.example.
_TEST_ONLY = {"RUN_OLLAMA_TESTS", "RUN_POSTGRES_TESTS", "RUN_SUPABASE_TESTS"}


def code_env_keys() -> set[str]:
    keys: set[str] = set()

    files: list[Path] = [ROOT / name for name in SCAN_FILES]
    for directory in SCAN_DIRS:
        files.extend((ROOT / directory).rglob("*.py"))

    for path in files:
        text = path.read_text(encoding="utf-8")
        for pattern in _PATTERNS:
            keys.update(pattern.findall(text))

    return keys - _TEST_ONLY


def documented_keys() -> set[str]:
    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    keys: set[str] = set()
    for line in content.splitlines():
        stripped = line.strip().lstrip("#").strip()
        match = re.match(r"^([A-Z][A-Z0-9_]*)\s*=", stripped)
        if match:
            keys.add(match.group(1))
    return keys


def active_keys() -> set[str]:
    """Uncommented KEY=value lines only."""

    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    return {
        match.group(1)
        for line in content.splitlines()
        if (match := re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip()))
    }


class EnvExampleTests(unittest.TestCase):
    def test_every_code_key_is_documented(self):
        undocumented = code_env_keys() - documented_keys()
        self.assertEqual(
            undocumented,
            set(),
            f"environment variables used in code but missing from .env.example: {undocumented}",
        )

    def test_no_stale_documented_keys(self):
        stale = documented_keys() - code_env_keys() - _COMPOSE_ONLY
        self.assertEqual(
            stale,
            set(),
            f"documented keys that no longer exist in code: {stale}",
        )

    def test_optional_keys_are_commented_opt_ins(self):
        commented = documented_keys() - active_keys()
        self.assertEqual(commented, _COMMENTED_OPT_INS)

    def test_no_duplicate_active_keys(self):
        content = (ROOT / ".env.example").read_text(encoding="utf-8")
        seen: list[str] = [
            match.group(1)
            for line in content.splitlines()
            if (match := re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip()))
        ]
        duplicates = {key for key in seen if seen.count(key) > 1}
        self.assertEqual(duplicates, set())

    def test_postgres_defaults_are_consistent_with_compose(self):
        """The documented DSN must match the Compose db service wiring."""

        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        example = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn(
            "postgresql://discord_builder:discord_builder@db:5432/discord_builder",
            compose,
        )
        self.assertIn(
            "DATABASE_URL=postgresql://discord_builder:discord_builder@db:5432/discord_builder",
            example,
        )
        for variable in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
            self.assertIn(f"{variable}=", example)
            self.assertIn(variable, compose)


if __name__ == "__main__":
    unittest.main()
