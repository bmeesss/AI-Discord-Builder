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
        web_app.set_component("database", True, "postgres ok")

        payload, status = web_app.evaluate_readiness()
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")

    def test_database_down_blocks_readiness_even_when_discord_ready(self):
        web_app.set_ready(True)
        web_app.set_component("database", False, "connection refused")

        payload, status = web_app.evaluate_readiness()
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not ready")
        self.assertFalse(payload["components"]["database"]["ok"])

    def test_component_detail_is_truncated(self):
        web_app.set_component("database", False, "x" * 1000)
        self.assertEqual(
            len(web_app.get_components()["database"]["detail"]),
            200,
        )


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
        web_app.set_component("database", True, "ok")
        response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 200)

    def test_readyz_503_when_database_unhealthy(self):
        web_app.set_ready(True)
        web_app.set_component("database", False, "timeout")
        response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
