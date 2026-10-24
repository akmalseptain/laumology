"""Tes observabilitas llm: config/prompt rusak tidak lagi diabaikan senyap.

llm.py murni stdlib - tes ini bisa direpro lokal.
Jalur sehat (file absen atau terbaca baik) TETAP tanpa log (by design).
"""
import unittest
from unittest import mock

import llm


def _raise(msg):
    def _f(*_a, **_k):
        raise OSError(msg)
    return _f

class LlmSilentTest(unittest.TestCase):
    def test_cfg_ada_tapi_rusak_warning_dan_jatuh_ke_default(self):
        bad = mock.MagicMock()
        bad.exists.return_value = True
        bad.read_text.side_effect = OSError("disk error")
        with mock.patch.object(llm, "CFG_PATH", bad):
            with self.assertLogs("laumology.llm", level="WARNING") as ctx:
                cfg = llm._cfg()
        self.assertEqual(cfg, {})
        self.assertTrue(any("llm.json" in m and "tidak bisa dibaca" in m for m in ctx.output))

    def test_cfg_json_tidak_valid_warning(self):
        bad = mock.MagicMock()
        bad.exists.return_value = True
        bad.read_text.return_value = "{bukan json"
        with mock.patch.object(llm, "CFG_PATH", bad):
            with self.assertLogs("laumology.llm", level="WARNING"):
                cfg = llm._cfg()
        self.assertEqual(cfg, {})

    def test_cfg_absen_tanpa_warning(self):
        absent = mock.MagicMock()
        absent.exists.return_value = False
        with mock.patch.object(llm, "CFG_PATH", absent):
            with self.assertNoLogs("laumology.llm", level="WARNING"):
                cfg = llm._cfg()
        self.assertEqual(cfg, {})

    def test_prompt_ada_tapi_rusak_warning_dan_pakai_bawaan(self):
        bad = mock.MagicMock()
        bad.name = "prompt.md"
        bad.exists.return_value = True
        bad.read_text.side_effect = OSError("permission denied")
        with mock.patch.object(llm, "_prompt_path", lambda: bad):
            with self.assertLogs("laumology.llm", level="WARNING") as ctx:
                text = llm.load_prompt()
        self.assertTrue(text.startswith("Kamu adalah Multi-Agent"))
        self.assertTrue(any("prompt.md" in m and "prompt bawaan" in m for m in ctx.output))

    def test_prompt_sehat_tanpa_warning(self):
        good = mock.MagicMock()
        good.name = "prompt.md"
        good.exists.return_value = True
        good.read_text.return_value = "---\nfront\n---\nIsi prompt khusus."
        with mock.patch.object(llm, "_prompt_path", lambda: good):
            with self.assertNoLogs("laumology.llm", level="WARNING"):
                text = llm.load_prompt()
        self.assertEqual(text, "Isi prompt khusus.")


if __name__ == "__main__":
    unittest.main()
