import unittest

from ai.models import (
    CategoryContext,
    ChannelContext,
    MemoryItem,
    ServerAnalysis,
    ServerContext,
    ServerIssue,
)
from builder.context import render_server_context


class ContextRenderingTests(unittest.TestCase):
    def test_render_includes_analysis_and_memory(self):
        context = ServerContext(
            guild_id="1",
            guild_name="Test Guild",
            member_count=42,
            categories=[
                CategoryContext(
                    id="10",
                    name="Community",
                )
            ],
            channels=[
                ChannelContext(
                    id="11",
                    name="general",
                    type="text",
                    category_name="Community",
                )
            ],
            memories=[
                MemoryItem(
                    id=None,
                    guild_id="1",
                    user_id=None,
                    key="style",
                    value="professional",
                    confidence=0.8,
                )
            ],
            analysis=ServerAnalysis(
                guild_id="1",
                health_score=85,
                issues=[
                    ServerIssue(
                        severity="medium",
                        category="community",
                        message="Missing support channel",
                    )
                ],
                recommendations=[
                    "Create support category"
                ],
            ),
        )

        rendered = render_server_context(context)

        self.assertIn("SERVER HEALTH SCORE: 85/100", rendered)
        self.assertIn("Missing support channel", rendered)
        self.assertIn("style: professional", rendered)
        self.assertIn("general", rendered)


if __name__ == "__main__":
    unittest.main()
