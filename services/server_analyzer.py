"""
Server analysis service.

Scores a Discord guild and produces issues/recommendations for the AI planner.
"""

from __future__ import annotations

from collections import Counter

import discord

from ai.models import ServerAnalysis, ServerIssue


DANGEROUS_PERMISSIONS = {
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "ban_members",
    "kick_members",
}


class ServerAnalyzer:
    def analyze(self, guild: discord.Guild) -> ServerAnalysis:
        issues: list[ServerIssue] = []
        recommendations: list[str] = []

        self._analyze_channels(guild, issues, recommendations)
        self._analyze_roles(guild, issues, recommendations)
        self._analyze_community(guild, issues, recommendations)

        penalty = 0
        for issue in issues:
            if issue.severity == "critical":
                penalty += 20
            elif issue.severity == "high":
                penalty += 12
            elif issue.severity == "medium":
                penalty += 7
            else:
                penalty += 3

        score = max(
            0,
            min(100, 100 - penalty),
        )

        return ServerAnalysis(
            guild_id=str(guild.id),
            health_score=score,
            issues=issues,
            recommendations=recommendations,
        )

    def _analyze_channels(
        self,
        guild: discord.Guild,
        issues: list[ServerIssue],
        recommendations: list[str],
    ) -> None:
        channel_names = [
            channel.name.lower().strip()
            for channel in guild.channels
        ]

        for name, count in Counter(channel_names).items():
            if count > 1:
                issues.append(
                    ServerIssue(
                        severity="medium",
                        category="channels",
                        message=f"Duplicate channel name: {name}",
                        recommendation="Rename duplicate channels for clarity.",
                    )
                )

        for category in guild.categories:
            if not category.channels:
                issues.append(
                    ServerIssue(
                        severity="low",
                        category="channels",
                        message=f"Empty category: {category.name}",
                        recommendation="Remove it or add relevant channels.",
                    )
                )

        normalized = {
            name.replace("-", " ").replace("_", " ")
            for name in channel_names
        }

        required = {
            "rules": "Add a rules channel.",
            "welcome": "Add a welcome channel.",
            "support": "Add support or ticket information.",
        }

        for keyword, recommendation in required.items():
            if not any(keyword in name for name in normalized):
                issues.append(
                    ServerIssue(
                        severity="medium",
                        category="community",
                        message=f"Missing important channel: {keyword}",
                        recommendation=recommendation,
                    )
                )
                recommendations.append(recommendation)

    def _analyze_roles(
        self,
        guild: discord.Guild,
        issues: list[ServerIssue],
        recommendations: list[str],
    ) -> None:
        role_names = {
            role.name.lower().strip()
            for role in guild.roles
        }

        staff_terms = {
            "admin",
            "administrator",
            "moderator",
            "mod",
            "staff",
        }

        if not role_names & staff_terms:
            issues.append(
                ServerIssue(
                    severity="medium",
                    category="roles",
                    message="Missing staff role structure.",
                    recommendation="Create clear Admin/Moderator roles.",
                )
            )
            recommendations.append("Create clear staff roles.")

        for role in guild.roles:
            if role.name == "@everyone":
                continue

            permissions = role.permissions
            dangerous = [
                permission
                for permission, enabled in permissions
                if enabled and permission in DANGEROUS_PERMISSIONS
            ]

            if "administrator" in dangerous:
                issues.append(
                    ServerIssue(
                        severity="critical",
                        category="security",
                        message=f"Role has administrator permission: {role.name}",
                        recommendation="Use scoped moderation permissions instead.",
                    )
                )
            elif len(dangerous) >= 3:
                issues.append(
                    ServerIssue(
                        severity="high",
                        category="security",
                        message=f"Role has many dangerous permissions: {role.name}",
                        recommendation="Reduce permissions to least privilege.",
                    )
                )

    def _analyze_community(
        self,
        guild: discord.Guild,
        issues: list[ServerIssue],
        recommendations: list[str],
    ) -> None:
        channel_names = {
            channel.name.lower().replace("-", " ").replace("_", " ")
            for channel in guild.channels
        }

        if not any("ticket" in name or "support" in name for name in channel_names):
            recommendations.append("Consider adding a support or ticket system.")

        if not any("announce" in name or "news" in name for name in channel_names):
            recommendations.append("Consider adding an announcements channel.")
