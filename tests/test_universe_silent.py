"""Tes observabilitas universe dinamis (batch-45) - cakupan scan tidak berubah senyap.

universe.py: bila query TradingView gagal/kosong/terlalu sedikit, fallback
ke daftar statis IDX_LIQUID DULU SENYAP - cakupan scan berubah tanpa jejak
dan hasil antar hari jadi tak bisa dibandingkan. Tes ini mengunci: fallback
tetap jalan (best-effort), tapi warning laumology.universe tercatat.

Stdlib murni - jalan di mana pun (lokal + CI).
"""
from __future__ import annotations

import time
import unittest

import universe
from config import IDX_LIQUID


class UniverseSilentTest(unittest.TestCase):
    def setUp(self):
        self._restore = []
        self._reset(universe._cache)
        self._reset(universe._full)

    def tearDown(self):
        for obj, name, orig in reversed(self._restore):
            setattr(obj, name, orig)
        self._reset(universe._cache)
        self._reset(universe._full)

    @staticmethod
    def _reset(c: dict) -> None:
        c["t"] = 0.0
        c["data"] = []

    def _patch(self, obj, name, value):
        self._restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    @staticmethod
    def _boom(*args, **kwargs):
        raise RuntimeError("TradingView mati")

    def test_query_gagal_fallback_statis_tidak_senyap(self):
        self._patch(universe, "_tv_query", self._boom)
        with self.assertLogs("laumology.universe", level="WARNING") as lg:
            out = universe.auto_universe(10)
        self.assertEqual(out, IDX_LIQUID[:10])
        self.assertTrue(any("fallback statis" in str(x) for x in lg.output), lg.output)

    def test_respons_kosong_fallback_statis_tidak_senyap(self):
        self._patch(universe, "_tv_query", lambda limit: [])
        with self.assertLogs("laumology.universe", level="WARNING") as lg:
            out = universe.auto_universe(10)
        self.assertEqual(out, IDX_LIQUID[:10])
        self.assertTrue(any("kosong" in str(x) for x in lg.output), lg.output)

    def test_full_universe_query_gagal_fallback_statis_tidak_senyap(self):
        self._patch(universe, "_tv_query", self._boom)
        with self.assertLogs("laumology.universe", level="WARNING") as lg:
            out = universe.full_universe(10)
        self.assertEqual(out, IDX_LIQUID[:10])
        self.assertTrue(any("fallback statis" in str(x) for x in lg.output), lg.output)

    def test_full_universe_respons_terlalu_sedikit_tidak_senyap(self):
        self._patch(universe, "_tv_query", lambda limit: ["Y1", "Y2"])
        with self.assertLogs("laumology.universe", level="WARNING") as lg:
            out = universe.full_universe(10)
        self.assertEqual(out, IDX_LIQUID[:10])
        self.assertTrue(any("terlalu sedikit" in str(x) for x in lg.output), lg.output)

    def test_cache_segar_tanpa_query_tanpa_warning(self):
        # Cache segar -> tidak boleh ada query baru (hemat + tanpa warning).
        universe._cache.update(t=time.time(), data=["X1", "X2", "X3"])
        calls = []

        def spy(limit):
            calls.append(limit)
            return ["Y1"]

        self._patch(universe, "_tv_query", spy)
        out = universe.auto_universe(3)
        self.assertEqual(out, ["X1", "X2", "X3"])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
