"""Static validation of the Docker Compose files.

The sandbox/CI cannot guarantee a Docker daemon, so these tests validate the
structure and wiring of the Compose files directly: services, healthchecks,
depends_on conditions, volumes and merge behavior of the local-AI overlay.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_compose(name: str) -> dict:
    path = ROOT / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{name} must be a YAML mapping"
    return data


def merge_service(base: dict, overlay: dict, service: str) -> dict:
    """Approximate Compose multi-file merge for the keys we rely on."""

    merged = dict(base["services"].get(service, {}))
    for key, value in overlay["services"].get(service, {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


class BaseComposeTests(unittest.TestCase):
    def setUp(self):
        self.compose = load_compose("compose.yaml")
        self.services = self.compose["services"]

    def test_db_and_bot_services_exist(self):
        self.assertIn("db", self.services)
        self.assertIn("bot", self.services)

    def test_db_is_postgres_with_healthcheck_and_volume(self):
        db = self.services["db"]
        self.assertIn("postgres", db["image"])

        healthcheck = db.get("healthcheck", {})
        self.assertIn("pg_isready", " ".join(map(str, healthcheck.get("test", []))))

        volumes = db.get("volumes", [])
        self.assertTrue(
            any("postgres_data" in str(volume) for volume in volumes),
            "db must persist data in the postgres_data volume",
        )
        self.assertIn("postgres_data", self.compose.get("volumes", {}))

        # The database is deliberately not published on the host.
        self.assertNotIn("ports", db)

    def test_bot_waits_for_healthy_db(self):
        bot = self.services["bot"]
        depends_on = bot.get("depends_on", {})
        self.assertEqual(
            depends_on.get("db", {}).get("condition"),
            "service_healthy",
        )

    def test_bot_defaults_to_postgres_backend(self):
        environment = self.services["bot"].get("environment", {})
        backend = environment.get("DATABASE_BACKEND", "")
        self.assertIn("postgres", backend)
        database_url = environment.get("DATABASE_URL", "")
        self.assertIn("postgresql://", database_url)
        self.assertIn("@db:5432", database_url)

    def test_bot_env_file_and_health_port(self):
        bot = self.services["bot"]
        self.assertIn(".env", bot.get("env_file", []))
        self.assertTrue(
            any("8080" in str(port) for port in bot.get("ports", [])),
            "health endpoints must be reachable",
        )


class LocalAiOverlayTests(unittest.TestCase):
    def setUp(self):
        self.base = load_compose("compose.yaml")
        self.overlay = load_compose("compose.local-ai.yaml")

    def test_overlay_adds_ollama_without_touching_db(self):
        overlay_services = self.overlay["services"]
        self.assertIn("ollama", overlay_services)
        self.assertIn("ollama-model", overlay_services)
        self.assertNotIn("db", overlay_services)

    def test_overlay_bot_keeps_db_dependency_and_adds_ollama(self):
        bot = merge_service(self.base, self.overlay, "bot")
        depends_on = bot.get("depends_on", {})
        self.assertEqual(
            depends_on.get("db", {}).get("condition"),
            "service_healthy",
        )
        self.assertEqual(
            depends_on.get("ollama", {}).get("condition"),
            "service_healthy",
        )

    def test_overlay_bot_uses_ollama_provider(self):
        environment = self.overlay["services"]["bot"].get("environment", {})
        self.assertEqual(environment.get("AI_PROVIDER"), "ollama")
        self.assertEqual(environment.get("OLLAMA_BASE_URL"), "http://ollama:11434")

    def test_ollama_has_healthcheck_and_named_volume(self):
        ollama = self.overlay["services"]["ollama"]
        self.assertIn("healthcheck", ollama)
        self.assertTrue(
            any("ollama_models" in str(volume) for volume in ollama.get("volumes", []))
        )
        self.assertIn("ollama_models", self.overlay.get("volumes", {}))


class EnvExampleTests(unittest.TestCase):
    def setUp(self):
        self.content = (ROOT / ".env.example").read_text(encoding="utf-8")

    def test_documented_defaults_match_compose(self):
        self.assertIn("DATABASE_BACKEND=postgres", self.content)
        self.assertIn(
            "DATABASE_URL=postgresql://discord_builder:discord_builder@db:5432/discord_builder",
            self.content,
        )
        self.assertIn("DB_MIGRATE_ON_STARTUP=true", self.content)
        self.assertIn("POSTGRES_USER=discord_builder", self.content)

    def test_no_real_secrets_in_example(self):
        lowered = self.content.lower()
        self.assertNotIn("gsk_", lowered)  # Groq key prefix
        self.assertNotIn("sk-proj", lowered)  # OpenAI key prefix


if __name__ == "__main__":
    unittest.main()
