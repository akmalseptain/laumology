"""Tes observabilitas boot scanner (batch-45) - import scheduler gagal tidak senyap.

webapp._maybe_start_scheduler: bila import scheduler gagal, auto-scanner
tidak jalan SAMA SEKALI (Senin tanpa sinyal apa pun) dan dulu pulang SENYAP.
Butuh flask (CI). Repro lokal: py_compile saja (jalur lama).
"""
from __future__ import annotations

import builtins
import os
import unittest
import unittest.mock

import webapp


class WebappBootSilentTest(unittest.TestCase):
    def test_import_scheduler_gagal_warning_dan_pulang_tenang(self):
        old = os.environ.get("ENABLE_SCHEDULER")
        os.environ["ENABLE_SCHEDULER"] = "1"
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "scheduler":
                raise ImportError("scheduler rusak")
            return real_import(name, *args, **kwargs)

        try:
            with unittest.mock.patch("builtins.__import__", fake_import):
                with self.assertLogs("laumology.webapp", level="WARNING") as lg:
                    webapp._maybe_start_scheduler()
        finally:
            if old is None:
                os.environ.pop("ENABLE_SCHEDULER", None)
            else:
                os.environ["ENABLE_SCHEDULER"] = old
        self.assertTrue(any("auto-scanner" in str(x) for x in lg.output), lg.output)


if __name__ == "__main__":
    unittest.main()
