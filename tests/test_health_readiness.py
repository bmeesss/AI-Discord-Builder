"""Health/readiness logic tests for web/app.py."""

from __future__ import annotations

import unittest

from web import app as web_app


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        web_app.set_ready(False)
        web_app.clear_components()

    def tearDown(self):
        web_app.set_ready(False)
        web_app.clear_components()

    def test_not_ready_while_discord_is_starting(self):
        payload, status = web_app.evaluate_readiness()
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not ready")

    def test_ready_after_discord_and_components_ok(self):
        web_app.set_ready(True)
        web_app.set_component("storage", True, "json storage ok")

        payload, status = web_app.evaluate_readiness()
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")

    def test_storage_down_blocks_readiness_even_when_discord_ready(self):
        web_app.set_ready(True)
        web_app.set_component("storage", False, "connection refused")

        payload, status = web_app.evaluate_readiness()
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not ready")
        self.assertEqual(payload["components"]["storage"], "unhealthy")

    def test_component_detail_is_truncated(self):
        web_app.set_component("storage", False, "x" * 1000)
        self.assertEqual(
            len(web_app.get_components()["storage"]["detail"]),
            200,
        )

    def test_readiness_payload_never_contains_component_details(self):
        """/readyz is public on hosted deployments: details stay internal."""

        web_app.set_ready(True)
        web_app.set_component(
            "storage",
            False,
            "postgresql://user:secret@db-host:5432/prod password auth failed",
        )

        payload, status = web_app.evaluate_readiness()
        self.assertEqual(status, 503)
        serialized = str(payload)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("db-host", serialized)
        self.assertNotIn("postgresql://", serialized)
        self.assertEqual(payload["components"]["storage"], "unhealthy")


class HttpEndpointTests(unittest.TestCase):
    def setUp(self):
        web_app.set_ready(False)
        web_app.clear_components()
        self.client = web_app.app.test_client()

    def tearDown(self):
        web_app.set_ready(False)
        web_app.clear_components()

    def test_healthz_is_always_ok_while_process_runs(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_readyz_503_until_discord_ready(self):
        response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)

        web_app.set_ready(True)
        web_app.set_component("storage", True, "ok")
        response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 200)

    def test_readyz_503_when_storage_unhealthy(self):
        web_app.set_ready(True)
        web_app.set_component("storage", False, "timeout")
        response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
