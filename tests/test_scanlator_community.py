"""Tests untuk fitur komunitas Scanlator (tanpa menyentuh Discord live)."""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ScanlatorCommunityTests(unittest.TestCase):
    def test_helper_defined_and_wired(self):
        server = open(os.path.join(ROOT, "server_management.py")).read()
        bot = open(os.path.join(ROOT, "bot.py")).read()
        self.assertIn("async def ensure_scanlator_community", server)
        self.assertIn("ensure_scanlator_community(target_guild)", bot)

    def test_command_registered(self):
        bot = open(os.path.join(ROOT, "bot.py")).read()
        self.assertIn('name="scanlator-akses"', bot)
        view = open(os.path.join(ROOT, "views", "scanlator_access_views.py")).read()
        self.assertIn("async def scanlator_akses_command", view)
        self.assertIn("remove_roles", view)
        self.assertIn("set_permissions(member, overwrite=None)", view)

    def test_config_present(self):
        config = open(os.path.join(ROOT, "config.py")).read()
        self.assertIn("ROLE_SCANLATOR_ID", config)
        self.assertIn("SCANLATOR_CHANNEL_ID", config)
        self.assertIn("scanlator-chat", config)


if __name__ == "__main__":
    unittest.main()
