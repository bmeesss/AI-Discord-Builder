"""AI provider error-handling tests.

Covers the ai.client.AIClient boundary (empty/invalid/unvalidated responses,
provider failures) and the Groq/OpenAI adapters (SDK errors, empty content)
with injected fake clients.  No network access is needed.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from ai.client import AIClient, AIPlanError
from ai.providers.base import ProviderError
from ai.providers.groq import GroqProvider
from ai.providers.openai import OpenAIProvider

VALID_PLAN = (
    '{"summary": "ok", "risk": "low", "actions": '
    '[{"type": "create_category", "name": "general"}]}'
)


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, response: str | Exception = VALID_PLAN):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def healthcheck(self):
        raise NotImplementedError

    async def test_model(self):
        raise NotImplementedError


class AIClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_plan_is_returned_as_legacy_dict(self):
        client = AIClient(provider=FakeProvider())
        plan = await client.generate_plan("maak een kanaal")

        self.assertEqual(plan["summary"], "ok")
        self.assertEqual(plan["actions"][0]["type"], "create_category")

    async def test_provider_error_becomes_ai_plan_error(self):
        client = AIClient(
            provider=FakeProvider(ProviderError("api down"))
        )
        with self.assertRaises(AIPlanError):
            await client.generate_plan("test")

    async def test_unexpected_provider_crash_becomes_ai_plan_error(self):
        client = AIClient(
            provider=FakeProvider(RuntimeError("sdk exploded"))
        )
        with self.assertRaises(AIPlanError):
            await client.generate_plan("test")

    async def test_empty_response_is_rejected(self):
        client = AIClient(provider=FakeProvider("   "))
        with self.assertRaises(AIPlanError):
            await client.generate_plan("test")

    async def test_invalid_json_is_rejected(self):
        client = AIClient(provider=FakeProvider("not json at all"))
        with self.assertRaises(AIPlanError):
            await client.generate_plan("test")

    async def test_markdown_fenced_json_is_cleaned(self):
        fenced = "```json\n" + VALID_PLAN + "\n```"
        client = AIClient(provider=FakeProvider(fenced))
        plan = await client.generate_plan("test")
        self.assertEqual(plan["summary"], "ok")

    async def test_unknown_action_type_is_rejected(self):
        payload = (
            '{"summary": "x", "risk": "low", "actions": '
            '[{"type": "delete_everything"}]}'
        )
        client = AIClient(provider=FakeProvider(payload))
        with self.assertRaises(AIPlanError):
            await client.generate_plan("test")

    async def test_too_many_actions_are_rejected(self):
        import config

        actions = ", ".join(
            '{"type": "create_category", "name": "c%s"}' % index
            for index in range(config.MAX_ACTIONS_PER_PLAN + 1)
        )
        payload = (
            '{"summary": "x", "risk": "low", "actions": [' + actions + "]}"
        )
        client = AIClient(provider=FakeProvider(payload))
        with self.assertRaises(AIPlanError):
            await client.generate_plan("test")

    async def test_missing_summary_is_rejected(self):
        client = AIClient(
            provider=FakeProvider('{"risk": "low", "actions": []}')
        )
        with self.assertRaises(AIPlanError):
            await client.generate_plan("test")

    async def test_provider_only_receives_prompt_text(self):
        """Providers must never see Discord objects — only strings."""

        provider = FakeProvider()
        client = AIClient(provider=provider)
        await client.generate_plan("test", server_context="ctx")

        self.assertEqual(len(provider.calls), 1)
        system_prompt, user_prompt = provider.calls[0]
        self.assertIsInstance(system_prompt, str)
        self.assertIsInstance(user_prompt, str)


class _FakeSDKClient:
    """Mimics the small slice of the Groq/OpenAI SDKs the adapters use."""

    def __init__(self, content: str | None = None, error: Exception | None = None):
        self._content = content
        self._error = error

        completion = MagicMock()
        completion.create = AsyncMock(side_effect=self._create)
        chat = MagicMock()
        chat.completions = completion
        self.chat = chat

        self.models = MagicMock()
        self.models.list = AsyncMock(
            side_effect=self._error if self._error else None
        )

    async def _create(self, **kwargs):
        if self._error is not None:
            raise self._error
        message = MagicMock()
        message.content = self._content
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response


class GroqProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_api_key_raises_provider_error(self):
        with self.assertRaises(ProviderError):
            GroqProvider(api_key="", model="m")

    async def test_generate_returns_content(self):
        provider = GroqProvider(
            api_key="k", model="m", client=_FakeSDKClient(content="{}")
        )
        self.assertEqual(await provider.generate("s", "u"), "{}")

    async def test_sdk_error_becomes_provider_error(self):
        provider = GroqProvider(
            api_key="k",
            model="m",
            client=_FakeSDKClient(error=RuntimeError("boom")),
        )
        with self.assertRaises(ProviderError):
            await provider.generate("s", "u")

    async def test_empty_content_becomes_provider_error(self):
        provider = GroqProvider(
            api_key="k", model="m", client=_FakeSDKClient(content="")
        )
        with self.assertRaises(ProviderError):
            await provider.generate("s", "u")

    async def test_healthcheck_reports_unreachable(self):
        provider = GroqProvider(
            api_key="k",
            model="m",
            client=_FakeSDKClient(error=RuntimeError("down")),
        )
        health = await provider.healthcheck()
        self.assertFalse(health.ok)
        self.assertIn("not reachable", health.message)

    async def test_test_model_reports_failure(self):
        provider = GroqProvider(
            api_key="k",
            model="m",
            client=_FakeSDKClient(error=RuntimeError("down")),
        )
        health = await provider.test_model()
        self.assertFalse(health.ok)


class OpenAIProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_api_key_raises_provider_error(self):
        with self.assertRaises(ProviderError):
            OpenAIProvider(api_key="", model="m")

    async def test_generate_returns_content(self):
        provider = OpenAIProvider(
            api_key="k", model="m", client=_FakeSDKClient(content="{}")
        )
        self.assertEqual(await provider.generate("s", "u"), "{}")

    async def test_sdk_error_becomes_provider_error(self):
        provider = OpenAIProvider(
            api_key="k",
            model="m",
            client=_FakeSDKClient(error=RuntimeError("boom")),
        )
        with self.assertRaises(ProviderError):
            await provider.generate("s", "u")

    async def test_empty_content_becomes_provider_error(self):
        provider = OpenAIProvider(
            api_key="k", model="m", client=_FakeSDKClient(content=None)
        )
        with self.assertRaises(ProviderError):
            await provider.generate("s", "u")

    async def test_healthcheck_reports_unreachable(self):
        provider = OpenAIProvider(
            api_key="k",
            model="m",
            client=_FakeSDKClient(error=RuntimeError("down")),
        )
        health = await provider.healthcheck()
        self.assertFalse(health.ok)


if __name__ == "__main__":
    unittest.main()
