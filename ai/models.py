"""
Typed AI and context models for AI Discord Builder.

These models keep AI output and Discord context structured before any data is
converted back to the legacy dictionaries used by the current executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass(slots=True)
class ChannelContext:
    id: str
    name: str
    type: str
    category_id: str | None = None
    category_name: str | None = None
    topic: str | None = None
    position: int | None = None
    slowmode_delay: int | None = None
    nsfw: bool | None = None


@dataclass(slots=True)
class CategoryContext:
    id: str
    name: str
    position: int | None = None


@dataclass(slots=True)
class RoleContext:
    id: str
    name: str
    position: int
    permissions: list[str] = field(default_factory=list)
    color: str | None = None
    hoist: bool = False
    mentionable: bool = False
    managed: bool = False


@dataclass(slots=True)
class PermissionContext:
    bot_permissions: list[str] = field(default_factory=list)
    missing_bot_permissions: list[str] = field(default_factory=list)
    bot_top_role_position: int | None = None


@dataclass(slots=True)
class MemoryItem:
    id: str | None
    guild_id: str
    user_id: str | None
    key: str
    value: str
    memory_type: str = "preference"
    confidence: float = 0.5
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class ConversationSummary:
    guild_id: str
    summary: str
    preferences: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    updated_at: str | None = None


@dataclass(slots=True)
class TemplateCandidate:
    id: str | None
    name: str
    description: str
    category: str
    version: str = "1"
    tags: list[str] = field(default_factory=list)
    recommended_for: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ServerIssue:
    severity: RiskLevel
    category: str
    message: str
    recommendation: str | None = None


@dataclass(slots=True)
class ServerAnalysis:
    guild_id: str
    health_score: int
    issues: list[ServerIssue] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )


@dataclass(slots=True)
class ServerContext:
    guild_id: str
    guild_name: str
    member_count: int | None
    categories: list[CategoryContext] = field(default_factory=list)
    channels: list[ChannelContext] = field(default_factory=list)
    roles: list[RoleContext] = field(default_factory=list)
    permissions: PermissionContext = field(default_factory=PermissionContext)
    memories: list[MemoryItem] = field(default_factory=list)
    conversations: list[ConversationSummary] = field(default_factory=list)
    templates: list[TemplateCandidate] = field(default_factory=list)
    analysis: ServerAnalysis | None = None


@dataclass(slots=True)
class AIAction:
    type: str
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, action: dict[str, Any]) -> "AIAction":
        data = dict(action)
        action_type = str(data.pop("type", ""))
        return cls(
            type=action_type,
            data=data,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            **self.data,
        }


@dataclass(slots=True)
class AIPlan:
    summary: str
    actions: list[AIAction]
    needs_clarification: bool = False
    clarification_question: str | None = None
    risk: RiskLevel = "low"
    recommendations: list[str] = field(default_factory=list)
    selected_template: str | None = None

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "risk": self.risk,
            "recommendations": self.recommendations,
            "selected_template": self.selected_template,
            "actions": [
                action.to_dict()
                for action in self.actions
            ],
        }
