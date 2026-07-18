import unittest

from ai.validation import PlanValidationError, parse_plan


class AIValidationTests(unittest.TestCase):
    def test_parse_valid_plan_with_risk(self):
        plan = parse_plan(
            {
                "summary": "Maak een support kanaal.",
                "risk": "low",
                "needs_clarification": False,
                "clarification_question": None,
                "recommendations": [
                    "Voeg later ticket automation toe."
                ],
                "actions": [
                    {
                        "type": "create_channel",
                        "name": "support",
                        "category": None,
                        "channel_type": "text",
                    }
                ],
            }
        )

        self.assertEqual(plan.risk, "low")
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].type, "create_channel")

    def test_reject_unknown_action(self):
        with self.assertRaises(PlanValidationError):
            parse_plan(
                {
                    "summary": "Ongeldige actie.",
                    "risk": "low",
                    "actions": [
                        {
                            "type": "create_magic_channel",
                            "name": "magic",
                        }
                    ],
                }
            )

    def test_reject_invalid_role_color(self):
        with self.assertRaises(PlanValidationError):
            parse_plan(
                {
                    "summary": "Maak rol.",
                    "risk": "medium",
                    "actions": [
                        {
                            "type": "create_role",
                            "name": "Moderator",
                            "permissions": [],
                            "color": "blue",
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
