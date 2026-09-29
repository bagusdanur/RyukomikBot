"""Test bahwa jalur Discord tidak pernah aktif saat tes berjalan.

Insiden: menjalankan `unittest discover -s tests` mengirim notifikasi
"📢 Payrate Staff Diperbarui" yang asli ke tiket staff di Discord, tiga kali.
Sebabnya `dashboard.backend.deps.DEV_BYPASS` dibaca sekali saat modul dimuat,
dan `test_projects_tracker` menarik `dashboard.backend.routers.projects` di
level modul -- sebelum `setUp` milik `test_dashboard_api` sempat menyetel
`DASHBOARD_DEV_BYPASS`. Nilai beku `False` itu membuat `discord_api` benar
benar memanggil Discord.

Test ini menjaga agar (a) `discord_api` menolak saat mode dev/uji, dan
(b) tidak ada tes yang lolos ke jaringan asli.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp  # noqa: E402

from dashboard.backend.helpers import _live_discord_allowed  # noqa: E402


class LiveDiscordGuardTest(unittest.TestCase):
    """`_live_discord_allowed` harus menutup jalur jaringan di mode uji."""

    def test_dev_bypass_dari_env_menutup_jalur(self):
        with patch.dict(os.environ, {"DASHBOARD_DEV_BYPASS": "true"}, clear=False):
            self.assertFalse(_live_discord_allowed())

    def test_no_discord_menutup_jalur(self):
        with patch.dict(os.environ, {"DASHBOARD_DEV_BYPASS": "false",
                                     "DASHBOARD_NO_DISCORD": "true"}, clear=False):
            self.assertFalse(_live_discord_allowed())

    def test_test_mode_menutup_jalur(self):
        with patch.dict(os.environ, {"DASHBOARD_DEV_BYPASS": "false",
                                     "DASHBOARD_NO_DISCORD": "false",
                                     "DASHBOARD_TEST_MODE": "true"}, clear=False):
            self.assertFalse(_live_discord_allowed())

    def test_flag_beku_dari_deps_ikut_dihormati(self):
        """DEV_BYPASS yang beku tetap menutup jalur walau env sudah berubah."""
        with patch.dict(os.environ, {"DASHBOARD_DEV_BYPASS": "false",
                                     "DASHBOARD_NO_DISCORD": "false",
                                     "DASHBOARD_TEST_MODE": "false"}, clear=False):
            import dashboard.backend.deps as deps
            with patch.object(deps, "DEV_BYPASS", True):
                self.assertFalse(_live_discord_allowed())

    def test_hanya_produksi_yang_membuka_jalur(self):
        with patch.dict(os.environ, {"DASHBOARD_DEV_BYPASS": "false",
                                     "DASHBOARD_NO_DISCORD": "false",
                                     "DASHBOARD_TEST_MODE": "false"}, clear=False):
            import dashboard.backend.deps as deps
            with patch.object(deps, "DEV_BYPASS", False):
                self.assertTrue(_live_discord_allowed())


class DiscordApiRefusesNetworkTest(unittest.IsolatedAsyncioTestCase):
    """`discord_api` tidak boleh membuka sesi HTTP saat mode uji."""

    async def test_tidak_memanggil_jaringan_saat_mode_uji(self):
        from dashboard.backend import helpers

        opened = []

        class _Boom:
            def __init__(self, *a, **k):
                opened.append("ClientSession")
                raise AssertionError("discord_api membuka sesi jaringan di mode uji")

        with patch.dict(os.environ, {"DASHBOARD_NO_DISCORD": "true"}, clear=False):
            with patch.object(helpers.aiohttp, "ClientSession", _Boom):
                result = await helpers.discord_api("POST", "/channels/1/messages", {"content": "x"})
        self.assertIsNone(result)
        self.assertEqual(opened, [], "tidak boleh ada sesi jaringan")

    async def test_tanpa_token_tidak_memanggil_jaringan(self):
        from dashboard.backend import helpers

        opened = []

        class _Boom:
            def __init__(self, *a, **k):
                opened.append("ClientSession")
                raise AssertionError("tidak boleh membuka sesi tanpa token")

        with patch.dict(os.environ, {"DASHBOARD_DEV_BYPASS": "false",
                                     "DASHBOARD_NO_DISCORD": "false",
                                     "DASHBOARD_TEST_MODE": "false"}, clear=False):
            with patch.object(helpers, "TOKEN", ""):
                with patch.object(helpers.aiohttp, "ClientSession", _Boom):
                    result = await helpers.discord_api("POST", "/channels/1/messages", {})
        self.assertIsNone(result)
        self.assertEqual(opened, [])


class BroadcastGuardedTest(unittest.IsolatedAsyncioTestCase):
    """Pemanggil tingkat router juga harus menghormati mode uji."""

    async def test_broadcast_payrate_tidak_mengirim_saat_mode_uji(self):
        from dashboard.backend.routers import payrate

        calls = []

        async def fake_discord_api(*a, **k):
            calls.append(a)
            raise AssertionError("broadcast menembak Discord di mode uji")

        with patch.dict(os.environ, {"DASHBOARD_NO_DISCORD": "true"}, clear=False):
            with patch.object(payrate, "discord_api", fake_discord_api):
                sent = await payrate.broadcast_payrate_to_staff("TL", 4000, 8000)
        self.assertEqual(sent, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
