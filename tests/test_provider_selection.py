import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ai.client import AIClient
from ai.providers.base import ProviderError, ProviderHealth
from ai.providers.factory import SUPPORTED_PROVIDERS, create_provider
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.providers.registry import CLOUD_PRESETS, OPENAI_COMPATIBLE_NAMES


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
        self.assertEqual(
            SUPPORTED_PROVIDERS,
            {
                "groq",
                "openai",
                "gemini",
                "mistral",
                "openrouter",
                "deepseek",
                "anthropic",
                "xai",
                "together",
                "perplexity",
                "ollama",
            },
        )

    def test_provider_registries_stay_in_sync(self):
        import ai.providers
        import config

        self.assertEqual(config.VALID_AI_PROVIDERS, SUPPORTED_PROVIDERS)
        self.assertEqual(ai.providers.SUPPORTED_PROVIDERS, SUPPORTED_PROVIDERS)

    def test_every_cloud_provider_has_a_preset_with_key_and_model(self):
        for name in SUPPORTED_PROVIDERS - {"ollama"}:
            preset = CLOUD_PRESETS[name]
            self.assertEqual(preset.name, name)
            self.assertTrue(preset.api_key_env.endswith("_API_KEY"))
            self.assertTrue(preset.model_env.endswith("_MODEL"))
            self.assertTrue(preset.default_model)

    def test_only_openai_compatible_presets_go_through_the_shared_adapter(self):
        self.assertEqual(
            OPENAI_COMPATIBLE_NAMES,
            frozenset(CLOUD_PRESETS) - {"groq"},
        )

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


class OpenAICompatibleFactoryTests(unittest.TestCase):
    def _settings(self, provider, **overrides):
        values = {
            "AI_PROVIDER": provider,
            "AI_REQUEST_TIMEOUT_SECONDS": 12,
        }
        for preset in CLOUD_PRESETS.values():
            values[preset.api_key_env] = None
            values[preset.model_env] = "unused"
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_preset_selection_passes_base_url_and_model(self):
        settings = self._settings(
            "gemini",
            GEMINI_API_KEY="test-key",
            GEMINI_MODEL="gemini-4-hydrogen",
        )
        with patch("ai.providers.factory.OpenAICompatibleProvider") as adapter:
            create_provider(settings=settings)
        adapter.assert_called_once_with(
            name="gemini",
            display="Google Gemini",
            api_key="test-key",
            key_env="GEMINI_API_KEY",
            model="gemini-4-hydrogen",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=12,
            json_mode=True,
        )

    def test_openai_keeps_custom_base_url_override(self):
        settings = self._settings(
            "openai",
            OPENAI_API_KEY="test-key",
            OPENAI_MODEL="gpt-4o-mini",
            OPENAI_BASE_URL="https://example.com/v1",
        )
        with patch("ai.providers.factory.OpenAICompatibleProvider") as adapter:
            create_provider(settings=settings)
        self.assertEqual(
            adapter.call_args.kwargs["base_url"],
            "https://example.com/v1",
        )

    def test_presets_without_json_mode_disable_response_format(self):
        for name in ("anthropic", "openrouter", "perplexity"):
            settings = self._settings(
                name,
                **{CLOUD_PRESETS[name].api_key_env: "test-key"},
            )
            with patch("ai.providers.factory.OpenAICompatibleProvider") as adapter:
                create_provider(settings=settings)
            self.assertFalse(
                adapter.call_args.kwargs["json_mode"],
                f"{name} must not request unsupported JSON mode",
            )

    def test_unknown_provider_error_lists_every_provider(self):
        settings = self._settings("bogus")
        with self.assertRaises(ProviderError) as ctx:
            create_provider(settings=settings)
        for name in SUPPORTED_PROVIDERS:
            self.assertIn(name, str(ctx.exception))


class OpenAICompatibleAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _adapter(self, **overrides):
        kwargs = {
            "name": "gemini",
            "display": "Google Gemini",
            "api_key": "test-key",
            "model": "gemini-4-hydrogen",
            "key_env": "GEMINI_API_KEY",
            "client": SimpleNamespace(),
        }
        kwargs.update(overrides)
        return OpenAICompatibleProvider(**kwargs)

    def test_missing_key_error_names_the_provider_and_env_var(self):
        with self.assertRaises(ProviderError) as ctx:
            self._adapter(api_key="")
        self.assertEqual(
            str(ctx.exception),
            "GEMINI_API_KEY is required when AI_PROVIDER=gemini.",
        )

    async def test_json_mode_sends_response_format(self):
        calls = {}

        class FakeChat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    calls.update(kwargs)
                    message = SimpleNamespace(content='{"status":"ok"}')
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=message)]
                    )

        provider = self._adapter(
            client=SimpleNamespace(chat=FakeChat()),
            json_mode=True,
        )
        await provider.generate("system", "user")
        self.assertEqual(calls["response_format"], {"type": "json_object"})

    async def test_without_json_mode_omits_response_format(self):
        calls = {}

        class FakeChat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    calls.update(kwargs)
                    message = SimpleNamespace(content='{"status":"ok"}')
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=message)]
                    )

        provider = self._adapter(
            client=SimpleNamespace(chat=FakeChat()),
            json_mode=False,
        )
        await provider.generate("system", "user")
        self.assertNotIn("response_format", calls)

    async def test_empty_response_is_rejected(self):
        class FakeChat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    message = SimpleNamespace(content="  ")
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=message)]
                    )

        provider = self._adapter(client=SimpleNamespace(chat=FakeChat()))
        with self.assertRaises(ProviderError) as ctx:
            await provider.generate("system", "user")
        self.assertIn("empty response", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
