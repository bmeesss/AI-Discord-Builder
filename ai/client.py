"""Provider-neutral AI planning client.

The client owns prompt construction and plan validation.  Provider adapters only
return text; they never receive a Discord object and never execute an action.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ai.prompts import SYSTEM_PROMPT, build_user_prompt
from ai.providers.base import AIProvider, ProviderError, ProviderHealth
from ai.providers.factory import create_provider
from ai.validation import PlanValidationError, parse_plan

logger = logging.getLogger("ai_discord_builder.ai_client")


class AIPlanError(Exception):
    """Raised when a provider or its output cannot produce a safe plan."""


class AIClient:
    """Generate and validate plans through the configured provider."""

    def __init__(
        self,
        provider: AIProvider | None = None,
        provider_name: str | None = None,
    ) -> None:
        self._provider = provider or create_provider(provider_name)
        self.provider = self._provider.name
        self._model = self._provider.model

    async def generate_plan(
        self,
        user_instruction: str,
        server_context: str | None = None,
        validation_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send an instruction to the provider and return a validated plan."""

        user_prompt = build_user_prompt(
            user_instruction,
            server_context,
            validation_errors=validation_errors,
        )

        try:
            raw_content = await self._provider.generate(
                SYSTEM_PROMPT,
                user_prompt,
            )
        except ProviderError as exc:
            logger.exception(
                "AI provider request failed (provider=%s, model=%s)",
                self.provider,
                self._model,
            )
            raise AIPlanError(
                f"{self.provider} is unavailable. Check the provider configuration."
            ) from exc
        except Exception as exc:  # defensive boundary for third-party SDKs
            logger.exception(
                "Unexpected AI provider failure (provider=%s, model=%s)",
                self.provider,
                self._model,
            )
            raise AIPlanError("The AI provider request failed.") from exc

        plan = self._parse_and_validate(raw_content)
        return plan.to_legacy_dict()

    async def healthcheck(self) -> ProviderHealth:
        """Check connectivity for setup tooling and operational health probes."""

        return await self._provider.healthcheck()

    async def test_connection(self) -> ProviderHealth:
        """Run a provider/model smoke test."""

        return await self._provider.test_model()

    def _parse_and_validate(self, raw_content: str | None):
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise AIPlanError("The AI provider returned an empty response.")

        cleaned = raw_content.strip()

        # Defensive JSON cleanup for providers that still wrap JSON in markdown.
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].strip().lower().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error(
                "AI returned invalid JSON (provider=%s, model=%s)",
                self.provider,
                self._model,
            )
            raise AIPlanError("The AI provider returned invalid JSON.") from exc

        try:
            return parse_plan(data)
        except PlanValidationError as exc:
            raise AIPlanError(str(exc)) from exc
