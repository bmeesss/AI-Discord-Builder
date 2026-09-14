"""
Context Intelligence Engine.

Builds one typed ServerContext containing Discord state, analysis, memory,
conversation summaries and template candidates.
"""

from __future__ import annotations

import discord

from ai.models import (
    CategoryContext,
    ChannelContext,
    PermissionContext,
    RoleContext,
    ServerContext,
)
from security.permissions import bot_has_required_permissions
from services.conversation_intelligence import ConversationIntelligence
from services.memory_service import MemoryService
from services.server_analyzer import ServerAnalyzer
from services.template_service import TemplateService


class ContextIntelligenceEngine:
    def __init__(
        self,
        analyzer: ServerAnalyzer | None = None,
        memory_service: MemoryService | None = None,
        conversation_service: ConversationIntelligence | None = None,
        template_service: TemplateService | None = None,
    ):
        self.analyzer = analyzer or ServerAnalyzer()
        self.memory_service = memory_service or MemoryService()
        self.conversation_service = conversation_service or ConversationIntelligence()
        self.template_service = template_service or TemplateService()

    async def build(
        self,
        guild: discord.Guild,
        user: discord.abc.User | None,
        user_request: str,
    ) -> ServerContext:
        bot_ok, missing = bot_has_required_permissions(guild)
        me = guild.me

        permissions = PermissionContext(
            bot_permissions=_enabled_permissions(me.guild_permissions) if me else [],
            missing_bot_permissions=[] if bot_ok else missing,
            bot_top_role_position=me.top_role.position if me else None,
        )

        member_count = getattr(guild, "member_count", None)

        context = ServerContext(
            guild_id=str(guild.id),
            guild_name=guild.name,
            member_count=member_count,
            categories=[
                CategoryContext(
                    id=str(category.id),
                    name=category.name,
                    position=category.position,
                )
                for category in guild.categories
            ],
            channels=[
                _channel_context(channel)
                for channel in guild.channels
                if isinstance(
                    channel,
                    (
                        discord.TextChannel,
                        discord.VoiceChannel,
                        discord.StageChannel,
                        discord.ForumChannel,
                    ),
                )
            ],
            roles=[
                RoleContext(
                    id=str(role.id),
                    name=role.name,
                    position=role.position,
                    permissions=_enabled_permissions(role.permissions),
                    color=str(role.color),
                    hoist=role.hoist,
                    mentionable=role.mentionable,
                    managed=role.managed,
                )
                for role in guild.roles
                if role.name != "@everyone"
            ],
            permissions=permissions,
        )

        context.analysis = self.analyzer.analyze(guild)
        context.memories = await self.memory_service.get_relevant_memories(
            guild_id=guild.id,
            user_id=user.id if user else None,
        )
        context.conversations = await self.conversation_service.get_summaries(
            guild_id=guild.id,
        )
        context.templates = await self.template_service.get_candidates(
            guild_id=guild.id,
            user_request=user_request,
            member_count=member_count,
        )

        return context


def _enabled_permissions(permissions: discord.Permissions) -> list[str]:
    return [
        name
        for name, enabled in permissions
        if enabled
    ]


def _channel_context(channel) -> ChannelContext:
    category = getattr(channel, "category", None)
    channel_type = channel.__class__.__name__.replace("Channel", "").lower()

    return ChannelContext(
        id=str(channel.id),
        name=channel.name,
        type=channel_type,
        category_id=str(category.id) if category else None,
        category_name=category.name if category else None,
        topic=getattr(channel, "topic", None),
        position=getattr(channel, "position", None),
        slowmode_delay=getattr(channel, "slowmode_delay", None),
        nsfw=getattr(channel, "nsfw", None),
    )
