import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ai.client import AIClient
from ai.providers.base import ProviderHealth
from ai.providers.factory import SUPPORTED_PROVIDERS, create_provider


class FakeProvider:
    name = "fake"
    model = "fake-model"

    async def generate(self, system_prompt, user_prompt):
        return json.dumps(
            {
                "summary": "Maak een kanaal.",
                "risk": "low",
                "actions": [
                    {
                        "type": "create_channel",
                        "name": "support",
                        "channel_type": "text",
                    }
                ],
            }
        )

    async def healthcheck(self):
        return ProviderHealth(True, self.name, self.model, "ok")

    async def test_model(self):
        return ProviderHealth(True, self.name, self.model, "ok")


class ProviderSelectionTests(unittest.TestCase):
    def test_all_official_providers_are_registered(self):
        self.assertEqual(SUPPORTED_PROVIDERS, {"groq", "openai", "ollama"})

    def test_ollama_factory_uses_local_settings(self):
        settings = SimpleNamespace(
            AI_PROVIDER="ollama",
            GROQ_API_KEY=None,
            GROQ_MODEL="unused",
            OPENAI_API_KEY=None,
            OPENAI_MODEL="unused",
            OPENAI_BASE_URL=None,
            OLLAMA_BASE_URL="http://ollama:11434",
            OLLAMA_MODEL="qwen3:4b",
            AI_REQUEST_TIMEOUT_SECONDS=12,
        )
        provider = create_provider(settings=settings)
        self.assertEqual(provider.name, "ollama")
        self.assertEqual(provider.model, "qwen3:4b")
        self.assertEqual(provider.base_url, "http://ollama:11434")

    def test_cloud_provider_selection_does_not_construct_other_providers(self):
        settings = SimpleNamespace(
            AI_PROVIDER="groq",
            GROQ_API_KEY="test-key",
            GROQ_MODEL="test-model",
            OPENAI_API_KEY=None,
            OPENAI_MODEL="unused",
            OPENAI_BASE_URL=None,
            OLLAMA_BASE_URL="http://localhost:11434",
            OLLAMA_MODEL="qwen3:4b",
            AI_REQUEST_TIMEOUT_SECONDS=12,
        )
        with patch("ai.providers.factory.GroqProvider") as groq:
            create_provider(settings=settings)
        groq.assert_called_once_with(
            api_key="test-key",
            model="test-model",
            timeout=12,
        )

    def test_ai_client_keeps_existing_plan_validation_contract(self):
        client = AIClient(provider=FakeProvider())
        plan = __import__("asyncio").run(
            client.generate_plan("maak een support kanaal")
        )
        self.assertEqual(plan["actions"][0]["type"], "create_channel")
        self.assertEqual(client.provider, "fake")


if __name__ == "__main__":
    unittest.main()
