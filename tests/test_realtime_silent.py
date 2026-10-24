"""Tes observabilitas realtime: config rusak tidak lagi diabaikan senyap.

realtime.py murni stdlib - tes ini bisa direpro lokal.
Jalur sehat (file absen atau terbaca baik) TETAP tanpa log (by design).
"""
import unittest
from unittest import mock

import realtime


class RealtimeSilentTest(unittest.TestCase):
    def test_cfg_ada_tapi_rusak_warning_dan_pakai_default(self):
        bad = mock.MagicMock()
        bad.exists.return_value = True
        bad.read_text.side_effect = OSError("disk error")
        with mock.patch.object(realtime, "CONFIG_PATH", bad):
            with self.assertLogs("laumology.realtime", level="WARNING") as ctx:
                cfg = realtime.load_config()
        self.assertEqual(cfg["provider"], "auto")
        self.assertTrue(any("realtime.json" in m and "tidak bisa dibaca" in m for m in ctx.output))

    def test_cfg_json_tidak_valid_warning(self):
        bad = mock.MagicMock()
        bad.exists.return_value = True
        bad.read_text.return_value = "{bukan json"
        with mock.patch.object(realtime, "CONFIG_PATH", bad):
            with self.assertLogs("laumology.realtime", level="WARNING"):
                cfg = realtime.load_config()
        self.assertEqual(cfg["provider"], "auto")

    def test_cfg_absen_tanpa_warning(self):
        absent = mock.MagicMock()
        absent.exists.return_value = False
        with mock.patch.object(realtime, "CONFIG_PATH", absent):
            with self.assertNoLogs("laumology.realtime", level="WARNING"):
                cfg = realtime.load_config()
        self.assertEqual(cfg["provider"], "auto")


if __name__ == "__main__":
    unittest.main()
