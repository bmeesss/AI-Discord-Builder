"""
ai/client.py
Verantwoordelijk voor het aanroepen van de AI provider (Groq of OpenAI) en het
veilig parsen/valideren van de JSON response volgens ons action-schema.

Belangrijk: dit bestand vertrouwt de AI-output NOOIT blind. Alles wordt
gevalideerd voordat het bij de executor terechtkomt.
"""

import json
import logging

import config
from ai.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("ai_discord_builder.ai_client")

VALID_ACTION_TYPES = {
    "create_category",
    "create_channel",
    "delete_channel",
    "move_channel",
    "create_role",
    "delete_role",
    "rename_role",
}

VALID_PERMISSIONS = {
    "manage_messages",
    "moderate_members",
    "kick_members",
    "ban_members",
    "manage_channels",
    "manage_roles",
    "mention_everyone",
    "view_channel",
    "connect",
    "speak",
    "administrator",  # toegestaan in schema, maar executor/AI ontmoedigen misbruik
}


class AIPlanError(Exception):
    """Raised wanneer de AI geen bruikbaar/veilig plan teruggeeft."""


class AIClient:
    def __init__(self):
        self.provider = config.AI_PROVIDER
        if self.provider == "groq":
            from groq import AsyncGroq
            self._client = AsyncGroq(api_key=config.GROQ_API_KEY)
            self._model = config.GROQ_MODEL
        elif self.provider == "openai":
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            self._model = config.OPENAI_MODEL
        else:
            raise ValueError(f"Onbekende AI_PROVIDER: {self.provider}")

    async def generate_plan(self, user_instruction: str, server_context: str | None = None) -> dict:
        """
        Stuurt de instructie naar de AI en geeft een gevalideerd plan-dict terug:
        {
            "summary": str,
            "needs_clarification": bool,
            "clarification_question": str | None,
            "actions": list[dict]
        }
        Raised AIPlanError als de response niet te vertrouwen/parsen is.
        """
        user_prompt = build_user_prompt(user_instruction, server_context)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw_content = response.choices[0].message.content
        except Exception as e:
            logger.exception("AI API call mislukt")
            raise AIPlanError(f"AI provider fout: {e}") from e

        return self._parse_and_validate(raw_content)

    def _parse_and_validate(self, raw_content: str) -> dict:
        # Sommige modellen wrappen JSON toch in code fences ondanks instructies; strip die defensief.
        cleaned = raw_content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("AI gaf geen valide JSON: %s", raw_content[:500])
            raise AIPlanError("De AI gaf geen valide JSON terug. Probeer je vraag anders te formuleren.") from e

        if not isinstance(data, dict):
            raise AIPlanError("AI response is geen JSON object.")

        summary = data.get("summary")
        needs_clarification = data.get("needs_clarification", False)
        clarification_question = data.get("clarification_question")
        actions = data.get("actions", [])

        if not isinstance(summary, str) or not summary:
            raise AIPlanError("AI response mist een geldige 'summary'.")

        if not isinstance(actions, list):
            raise AIPlanError("AI response 'actions' is geen lijst.")

        if len(actions) > config.MAX_ACTIONS_PER_PLAN:
            raise AIPlanError(
                f"AI plan bevat te veel acties ({len(actions)} > {config.MAX_ACTIONS_PER_PLAN}). "
                f"Vraag om iets kleinschaligers."
            )

        validated_actions = []
        for i, action in enumerate(actions):
            validated_actions.append(self._validate_action(action, i))

        return {
            "summary": summary,
            "needs_clarification": bool(needs_clarification),
            "clarification_question": clarification_question,
            "actions": validated_actions,
        }

    def _validate_action(self, action: dict, index: int) -> dict:
        if not isinstance(action, dict):
            raise AIPlanError(f"Actie #{index} is geen geldig object.")

        action_type = action.get("type")
        if action_type not in VALID_ACTION_TYPES:
            raise AIPlanError(f"Actie #{index} heeft onbekend type: {action_type!r}")

        if action_type in ("create_category", "create_channel", "delete_channel", "delete_role"):
            if not action.get("name"):
                raise AIPlanError(f"Actie #{index} ({action_type}) mist 'name'.")

        if action_type == "create_channel":
            channel_type = action.get("channel_type", "text")
            if channel_type not in ("text", "voice"):
                raise AIPlanError(f"Actie #{index}: ongeldig channel_type {channel_type!r}")

        if action_type == "move_channel":
            if not action.get("name") or not action.get("target_category"):
                raise AIPlanError(f"Actie #{index} (move_channel) mist 'name' of 'target_category'.")

        if action_type == "create_role":
            if not action.get("name"):
                raise AIPlanError(f"Actie #{index} (create_role) mist 'name'.")
            perms = action.get("permissions", [])
            if not isinstance(perms, list):
                raise AIPlanError(f"Actie #{index}: 'permissions' moet een lijst zijn.")
            invalid_perms = [p for p in perms if p not in VALID_PERMISSIONS]
            if invalid_perms:
                raise AIPlanError(f"Actie #{index}: ongeldige permissions {invalid_perms}")

        if action_type == "rename_role":
            if not action.get("old_name") or not action.get("new_name"):
                raise AIPlanError(f"Actie #{index} (rename_role) mist 'old_name' of 'new_name'.")

        return action
