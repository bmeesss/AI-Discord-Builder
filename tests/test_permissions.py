"""Discord permission-check tests for security/permissions.py.

These tests cover the authorization boundary: only guild Administrators may
use the builder (unless REQUIRE_ADMIN=false), and non-member objects fail
closed.  No Discord connection is needed.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class CanUseBuilderTests(unittest.TestCase):
    def _member(self, administrator: bool):
        member = MagicMock()
        member.guild_permissions.administrator = administrator
        return member

    def test_administrator_may_use_builder(self):
        from security.permissions import can_use_builder

        with patch("config.REQUIRE_ADMIN", True):
            self.assertTrue(can_use_builder(self._member(True)))

    def test_non_administrator_is_denied(self):
        from security.permissions import can_use_builder

        with patch("config.REQUIRE_ADMIN", True):
            self.assertFalse(can_use_builder(self._member(False)))

    def test_everyone_allowed_when_require_admin_disabled(self):
        from security.permissions import can_use_builder

        with patch("config.REQUIRE_ADMIN", False):
            self.assertTrue(can_use_builder(self._member(False)))

    def test_object_without_guild_permissions_fails_closed(self):
        """A cache-miss fallback (plain User) must never gain access."""

        from security.permissions import can_use_builder

        class FakeUser:
            pass

        with patch("config.REQUIRE_ADMIN", True):
            self.assertFalse(can_use_builder(FakeUser()))

    def test_none_member_fails_closed(self):
        from security.permissions import can_use_builder

        with patch("config.REQUIRE_ADMIN", True):
            self.assertFalse(can_use_builder(None))

    def test_missing_permission_message_mentions_administrator(self):
        from security.permissions import missing_permission_message

        message = missing_permission_message()
        self.assertIn("Administrator", message)


class BotPermissionTests(unittest.TestCase):
    def _guild(self, manage_channels: bool, manage_roles: bool):
        guild = MagicMock()
        guild.me.guild_permissions.manage_channels = manage_channels
        guild.me.guild_permissions.manage_roles = manage_roles
        return guild

    def test_bot_with_all_permissions_is_ok(self):
        from security.permissions import bot_has_required_permissions

        ok, missing = bot_has_required_permissions(self._guild(True, True))
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_bot_missing_manage_roles_is_reported(self):
        from security.permissions import bot_has_required_permissions

        ok, missing = bot_has_required_permissions(self._guild(True, False))
        self.assertFalse(ok)
        self.assertIn("manage_roles", missing)
        self.assertNotIn("manage_channels", missing)

    def test_bot_not_in_guild_is_reported(self):
        from security.permissions import bot_has_required_permissions

        guild = MagicMock()
        guild.me = None
        ok, missing = bot_has_required_permissions(guild)
        self.assertFalse(ok)
        self.assertTrue(missing)


if __name__ == "__main__":
    unittest.main()
