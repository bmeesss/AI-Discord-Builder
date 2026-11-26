"""Static validation of render.yaml (Render Blueprint) — free-tier edition.

The deployment contract for hosted installs is: ONE free web service, zero
databases, zero paid resources, secrets only via ``sync: false`` prompts
(never literal values).  UptimeRobot Free polls /readyz every 5 minutes,
which is also what keeps the free instance awake.  These tests run offline.
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
        cls.web = next(
            (service for service in cls.services if service.get("type") == "web"),
            None,
        )

    def test_exactly_one_web_service(self):
        self.assertEqual(len(self.services), 1)
        self.assertIsNotNone(self.web)

    def test_no_databases_anywhere(self):
        """The hard requirement: zero database resources."""

        self.assertNotIn("databases", self.blueprint)
        rendered = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertNotIn("fromDatabase", rendered)
        for key in ("DATABASE_URL", "DATABASE_BACKEND", "SUPABASE_URL"):
            self.assertNotIn(key, rendered)

    def test_web_service_builds_from_dockerfile(self):
        self.assertEqual(self.web["runtime"], "docker")

    def test_web_service_is_on_the_free_plan(self):
        """€0 per month: the free compute plan and nothing else."""

        self.assertEqual(self.web.get("plan"), "free")

    def test_no_paid_resources(self):
        for service in self.services:
            self.assertEqual(service.get("plan", "free"), "free")

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

    def test_no_literal_secret_values_anywhere(self):
        for entry in self.web.get("envVars", []):
            if isinstance(entry, dict) and entry.get("key") in SECRET_KEYS:
                self.assertNotIn("value", entry)

    def test_data_dir_points_at_container_path(self):
        env = self._env_vars()
        self.assertEqual(env["DATA_DIR"].get("value"), "/app/data")


if __name__ == "__main__":
    unittest.main()
