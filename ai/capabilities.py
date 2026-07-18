"""
Capability registry for AI-generated plans.

The registry is the source of truth for action types the AI may propose.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Capability:
    action_type: str
    description: str
    risk: str
    rollback: str
    required_permissions: tuple[str, ...] = ()


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "create_category",
        "Create a Discord category.",
        "low",
        "full",
        ("manage_channels",),
    ),
    Capability(
        "rename_category",
        "Rename an existing Discord category.",
        "medium",
        "full",
        ("manage_channels",),
    ),
    Capability(
        "create_channel",
        "Create a text or voice channel.",
        "low",
        "full",
        ("manage_channels",),
    ),
    Capability(
        "rename_channel",
        "Rename an existing channel.",
        "medium",
        "full",
        ("manage_channels",),
    ),
    Capability(
        "delete_channel",
        "Delete an existing channel only when explicitly requested.",
        "high",
        "partial",
        ("manage_channels",),
    ),
    Capability(
        "move_channel",
        "Move a channel to another category.",
        "medium",
        "full",
        ("manage_channels",),
    ),
    Capability(
        "send_message",
        "Send a message to an existing text channel.",
        "medium",
        "full",
        ("send_messages",),
    ),
    Capability(
        "create_role",
        "Create a role with safe permissions.",
        "medium",
        "full",
        ("manage_roles",),
    ),
    Capability(
        "rename_role",
        "Rename an existing role.",
        "medium",
        "full",
        ("manage_roles",),
    ),
    Capability(
        "delete_role",
        "Delete an existing role only when explicitly requested.",
        "high",
        "partial",
        ("manage_roles",),
    ),
)


VALID_ACTION_TYPES = {
    capability.action_type
    for capability in CAPABILITIES
}


def render_capabilities() -> str:
    lines = []

    for capability in CAPABILITIES:
        lines.append(
            (
                f"- {capability.action_type}: {capability.description} "
                f"risk={capability.risk}, rollback={capability.rollback}, "
                f"requires={', '.join(capability.required_permissions) or 'none'}"
            )
        )

    return "\n".join(lines)
