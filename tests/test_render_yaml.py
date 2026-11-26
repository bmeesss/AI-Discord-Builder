"""Static validation of render.yaml (Render Blueprint).

These tests pin down the deployment contract for hosted installs:
one always-on Docker web service with a public healthcheck, secrets only via
``sync: false`` prompts (never literal values), and a managed Postgres
database wired through ``fromDatabase``.  They run offline.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

SECRET_KEYS = {"DISCORD_TOKEN", "GROQ_API_KEY", "OPENAI_API_KEY", "SUPABASE_KEY"}


class RenderBlueprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        cls.blueprint = data
        cls.services = data.get("services") or []
        cls.databases = data.get("databases") or []
        cls.web = next(
            (service for service in cls.services if service.get("type") == "web"),
            None,
        )

    def test_exactly_one_web_service(self):
        self.assertEqual(len(self.services), 1)
        self.assertIsNotNone(self.web)

    def test_web_service_builds_from_dockerfile(self):
        self.assertEqual(self.web["runtime"], "docker")

    def test_web_service_is_always_on_paid_plan(self):
        """A Discord gateway bot needs an always-on instance.

        Free web services spin down after 15 minutes without inbound traffic
        (and are not intended for production), so the plan must be paid.
        """

        self.assertNotEqual(self.web.get("plan"), "free")
        self.assertTrue(self.web.get("plan"))

    def test_single_instance_only(self):
        """Running more than one instance would duplicate the gateway bot."""

        self.assertEqual(self.web.get("numInstances"), 1)

    def test_healthcheck_path_is_liveness_endpoint(self):
        self.assertEqual(self.web.get("healthCheckPath"), "/healthz")

    def test_auto_deploy_gated_on_ci_checks(self):
        self.assertEqual(self.web.get("autoDeployTrigger"), "checksPass")

    def _env_vars(self) -> dict[str, dict]:
        return {
            entry["key"]: entry
            for entry in self.web.get("envVars", [])
            if isinstance(entry, dict) and "key" in entry
        }

    def test_secrets_are_prompted_never_stored(self):
        env = self._env_vars()
        for key in SECRET_KEYS & set(env):
            entry = env[key]
            self.assertTrue(
                entry.get("sync") is False,
                f"{key} must use sync: false (prompted, never in git)",
            )
            self.assertNotIn("value", entry)

    def test_discord_token_is_a_prompted_secret(self):
        env = self._env_vars()
        self.assertIn("DISCORD_TOKEN", env)
        self.assertIs(env["DISCORD_TOKEN"].get("sync"), False)

    def test_ai_provider_is_user_controlled(self):
        env = self._env_vars()
        self.assertIn("AI_PROVIDER", env)
        self.assertIs(env["AI_PROVIDER"].get("sync"), False)

    def test_database_url_comes_from_managed_database(self):
        env = self._env_vars()
        self.assertIn("DATABASE_URL", env)
        reference = env["DATABASE_URL"].get("fromDatabase", {})
        self.assertEqual(reference.get("property"), "connectionString")
        self.assertIn(reference.get("name"), {db["name"] for db in self.databases})

    def test_database_backend_is_postgres(self):
        env = self._env_vars()
        self.assertEqual(env["DATABASE_BACKEND"].get("value"), "postgres")

    def test_no_literal_secret_values_anywhere(self):
        """No env var may carry a literal value for a secret key."""

        for entry in self.web.get("envVars", []):
            if isinstance(entry, dict) and entry.get("key") in SECRET_KEYS:
                self.assertNotIn("value", entry)

    def test_one_managed_database_with_persistent_plan(self):
        self.assertEqual(len(self.databases), 1)
        database = self.databases[0]
        self.assertTrue(database.get("name"))
        self.assertTrue(database.get("plan"))
        self.assertNotEqual(
            database.get("plan"),
            "free",
            "free Render Postgres expires after 30 days; use a paid plan",
        )

    def test_database_and_web_service_share_region_setting(self):
        """If a region is pinned, it must be pinned on both resources."""

        web_region = self.web.get("region")
        db_region = self.databases[0].get("region")
        if web_region or db_region:
            self.assertEqual(web_region, db_region)


if __name__ == "__main__":
    unittest.main()
