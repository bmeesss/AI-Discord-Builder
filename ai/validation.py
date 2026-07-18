"""
Typed AI plan validation.
"""

from __future__ import annotations

import re
from typing import Any

import config
from ai.capabilities import VALID_ACTION_TYPES
from ai.models import AIAction, AIPlan


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
    "administrator",
}

VALID_RISKS = {
    "low",
    "medium",
    "high",
    "critical",
}


class PlanValidationError(Exception):
    pass


def parse_plan(data: dict[str, Any]) -> AIPlan:
    if not isinstance(data, dict):
        raise PlanValidationError("AI response is geen JSON object.")

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise PlanValidationError("AI response mist een geldige summary.")

    risk = data.get("risk", "low")
    if risk not in VALID_RISKS:
        raise PlanValidationError("AI response heeft een ongeldige risk.")

    actions = data.get("actions", [])
    if not isinstance(actions, list):
        raise PlanValidationError("AI response actions is geen lijst.")

    if len(actions) > config.MAX_ACTIONS_PER_PLAN:
        raise PlanValidationError(
            f"AI plan bevat te veel acties ({len(actions)})."
        )

    typed_actions = []
    for index, action in enumerate(actions):
        typed_actions.append(
            _validate_action(action, index)
        )

    recommendations = data.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []

    return AIPlan(
        summary=summary.strip(),
        needs_clarification=bool(data.get("needs_clarification", False)),
        clarification_question=data.get("clarification_question"),
        actions=typed_actions,
        risk=risk,
        recommendations=[
            str(item)
            for item in recommendations
        ],
        selected_template=data.get("selected_template"),
    )


def _validate_action(action: dict[str, Any], index: int) -> AIAction:
    if not isinstance(action, dict):
        raise PlanValidationError(f"Actie #{index} is geen geldig object.")

    action_type = action.get("type")
    if action_type not in VALID_ACTION_TYPES:
        raise PlanValidationError(
            f"Actie #{index} heeft onbekend type: {action_type!r}"
        )

    if action_type in {
        "create_category",
        "create_channel",
        "delete_channel",
        "delete_role",
    } and not action.get("name"):
        raise PlanValidationError(f"Actie #{index} ({action_type}) mist name.")

    if action_type == "create_channel":
        channel_type = action.get("channel_type", "text")
        if channel_type not in {"text", "voice"}:
            raise PlanValidationError(f"Actie #{index}: ongeldig channel_type.")

    if action_type == "move_channel":
        if not action.get("name") or not action.get("target_category"):
            raise PlanValidationError(
                f"Actie #{index} (move_channel) mist gegevens."
            )

    if action_type == "send_message":
        if not action.get("channel") or not action.get("content"):
            raise PlanValidationError(
                f"Actie #{index} (send_message) mist channel of content."
            )

    if action_type == "create_role":
        if not action.get("name"):
            raise PlanValidationError(
                f"Actie #{index} (create_role) mist name."
            )

        permissions = action.get("permissions", [])
        if not isinstance(permissions, list):
            raise PlanValidationError(
                f"Actie #{index}: permissions moet een lijst zijn."
            )

        invalid_permissions = [
            permission
            for permission in permissions
            if permission not in VALID_PERMISSIONS
        ]
        if invalid_permissions:
            raise PlanValidationError(
                f"Actie #{index}: ongeldige permissions {invalid_permissions}"
            )

        color = action.get("color")
        if color and not re.fullmatch(r"#?[0-9a-fA-F]{6}", str(color)):
            raise PlanValidationError(f"Actie #{index}: ongeldige role color.")

    if action_type in {
        "rename_role",
        "rename_channel",
        "rename_category",
    }:
        if not action.get("old_name") or not action.get("new_name"):
            raise PlanValidationError(
                f"Actie #{index} ({action_type}) mist old_name of new_name."
            )

    return AIAction.from_dict(action)
