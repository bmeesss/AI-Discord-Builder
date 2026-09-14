"""Opt-in Ollama integration test.

Run only with:

    RUN_OLLAMA_TESTS=1 python -m unittest tests.integration.test_ollama_integration

Normal CI and unit tests never require an Ollama server.
"""

from __future__ import annotations

import asyncio
import os
import unittest

import config
from ai.providers.ollama import OllamaProvider


@unittest.skipUnless(
    os.getenv("RUN_OLLAMA_TESTS") == "1",
    "Set RUN_OLLAMA_TESTS=1 to enable the Ollama integration test.",
)
class OllamaIntegrationTests(unittest.TestCase):
    def test_configured_ollama_model(self):
        provider = OllamaProvider(
            config.OLLAMA_BASE_URL,
            config.OLLAMA_MODEL,
            timeout=config.AI_REQUEST_TIMEOUT_SECONDS,
        )
        health = asyncio.run(provider.healthcheck())
        self.assertTrue(health.ok, health.message)
        model_test = asyncio.run(provider.test_model())
        self.assertTrue(model_test.ok, model_test.message)
