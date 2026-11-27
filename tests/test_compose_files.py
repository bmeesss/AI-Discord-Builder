"""Static validation of the Docker Compose files — database-free edition.

The bot must run as a single container without any database service,
database image or database volume.  These tests validate the structure and
wiring of the Compose files directly (no Docker daemon needed).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?)\}")


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

    def test_only_the_bot_service_exists(self):
        """No database container, ever."""

        self.assertEqual(list(self.services), ["bot"])

    def test_no_database_images_anywhere(self):
        for service in self.services.values():
            image = str(service.get("image", "")).lower()
            for banned in ("postgres", "mysql", "mariadb", "mongo", "supabase"):
                self.assertNotIn(banned, image)

    def test_bot_has_no_database_environment(self):
        environment = self.services["bot"].get("environment", {})
        for key in environment:
            self.assertFalse(
                any(
                    key.startswith(prefix)
                    for prefix in ("DATABASE_", "POSTGRES_", "SUPABASE_", "DB_")
                ),
                f"unexpected database variable {key}",
            )

    def test_bot_persists_json_data_on_named_volume(self):
        bot = self.services["bot"]
        self.assertIn("bot_data", self.compose.get("volumes", {}))
        self.assertTrue(
            any("bot_data" in str(volume) for volume in bot.get("volumes", [])),
            "JSON storage must survive container restarts via bot_data",
        )
        environment = bot.get("environment", {})
        self.assertIn("DATA_DIR", environment)

    def test_bot_health_port_is_published(self):
        bot = self.services["bot"]
        self.assertIn(".env", bot.get("env_file", []))
        self.assertTrue(
            any("8080" in str(port) for port in bot.get("ports", [])),
            "health endpoints must be reachable",
        )


class InterpolationTests(unittest.TestCase):
    """Emulate Compose-variable interpolation with .env.example as the env."""

    @staticmethod
    def env_from_example() -> dict[str, str]:
        content = (ROOT / ".env.example").read_text(encoding="utf-8")
        env: dict[str, str] = {}
        for line in content.splitlines():
            match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line.strip())
            if match:
                env[match.group(1)] = match.group(2)
        return env

    @classmethod
    def render(cls, value, env):
        if isinstance(value, str):
            sentinel = "\0LITERAL_DOLLAR\0"
            value = value.replace("$$", sentinel)

            def substitute(match):
                variable, _, default = match.group(1).partition(":-")
                return env.get(variable, default)

            value = _INTERPOLATION.sub(substitute, value)
            return value.replace(sentinel, "$")
        if isinstance(value, list):
            return [cls.render(item, env) for item in value]
        if isinstance(value, dict):
            return {key: cls.render(item, env) for key, item in value.items()}
        return value

    def test_base_compose_renders_data_dir(self):
        env = self.env_from_example()
        rendered = self.render(load_compose("compose.yaml"), env)
        bot_env = rendered["services"]["bot"]["environment"]
        self.assertIn("DATA_DIR", bot_env)


class LocalAiOverlayTests(unittest.TestCase):
    def setUp(self):
        self.base = load_compose("compose.yaml")
        self.overlay = load_compose("compose.local-ai.yaml")

    def test_overlay_adds_ollama_without_touching_storage(self):
        overlay_services = self.overlay["services"]
        self.assertIn("ollama", overlay_services)
        self.assertIn("ollama-model", overlay_services)
        self.assertNotIn("db", overlay_services)

    def test_overlay_bot_keeps_storage_and_adds_ollama(self):
        bot = merge_service(self.base, self.overlay, "bot")
        depends_on = bot.get("depends_on", {})
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

    def test_documented_defaults_are_database_free(self):
        self.assertIn("DATA_DIR=data", self.content)
        self.assertNotIn("DATABASE_URL=", self.content)
        self.assertNotIn("SUPABASE_KEY=", self.content)
        self.assertNotIn("POSTGRES_", self.content)

    def test_no_real_secrets_in_example(self):
        lowered = self.content.lower()
        self.assertNotIn("gsk_", lowered)  # Groq key prefix
        self.assertNotIn("sk-proj", lowered)  # OpenAI key prefix


if __name__ == "__main__":
    unittest.main()
