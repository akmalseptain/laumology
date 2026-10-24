"""Tes observabilitas screener.screen (batch-43) - scan manual & warm.

Kelas temuan batch-40/41/42: kegagalan best-effort yang ditelan SENYAP.
Di screener, ticker yang gagal fetch/analisis HILANG dari hasil scan tanpa
jejak - pengguna mendapat tabel "seolah sehat" yang sebenarnya tidak
lengkap. Tes ini mengunci: skip tetap best-effort (ticker lain tetap
diproses), tapi warning tercatat di logger laumology.screener.

Butuh pandas/numpy (CI). Repro lokal: py_compile saja (jalur lama).
"""
from __future__ import annotations

import unittest

import pandas as pd

import data
import screener


def _long_df(n: int = 100) -> pd.DataFrame:
    return pd.DataFrame({"Close": [1000.0 + i for i in range(n)]},
                        index=pd.date_range("2026-01-01", periods=n))


class ScreenerSilentTest(unittest.TestCase):
    def setUp(self):
        self._restore = []
        # Cache modul-global + simpan cache ke disk: isolasi antar tes.
        screener._ROW_CACHE.clear()
        self._patch(screener, "_save_cache", lambda: None)

    def tearDown(self):
        for obj, name, orig in reversed(self._restore):
            setattr(obj, name, orig)
        screener._ROW_CACHE.clear()

    def _patch(self, obj, name, value):
        self._restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def test_fetch_gagal_tidak_senyap(self):
        # Ticker gagal fetch -> warning (dulu continue senyap);
        # ticker pendek data (<80 bar) tetap dilewati TANPA warning (bukan error).
        def flaky(t, *args, **kwargs):
            if t == "AAA":
                raise RuntimeError("sumber data mati")
            return pd.DataFrame({"Close": range(10)})

        self._patch(data, "get_ohlcv", flaky)
        with self.assertLogs("laumology.screener", level="WARNING") as lg:
            out = screener.screen(["AAA", "BBB"])
        self.assertTrue(len(out) == 0)
        self.assertTrue(any("AAA" in str(x) for x in lg.output), lg.output)
        self.assertFalse(any("BBB" in str(x) for x in lg.output), lg.output)

    def test_serial_compute_gagal_ticker_sehat_tetap_keluar(self):
        # Analisis satu ticker gagal -> warning; ticker sehat tetap masuk hasil.
        def fake_get(t, *args, **kwargs):
            return _long_df()

        def fake_row(t, df):
            if t == "AAA":
                raise RuntimeError("indikator meledak")
            return {"Ticker": t, "Signal": "BUY", "Score": 80, "Conf": 70}

        self._patch(data, "get_ohlcv", fake_get)
        self._patch(screener, "_row_from_df", fake_row)
        self._patch(screener, "_plan_workers", lambda n: 1)  # paksa jalur serial
        with self.assertLogs("laumology.screener", level="WARNING") as lg:
            out = screener.screen(["AAA", "BBB"])
        self.assertTrue(any("AAA" in str(x) for x in lg.output), lg.output)
        # Ticker sehat tetap keluar meski satu ticker gagal dianalisis.
        self.assertEqual(list(out["Ticker"]), ["BBB"])

    def test_screen_one_gagal_tidak_senyap(self):
        # Worker _screen_one (dipakai ProcessPoolExecutor) gagal -> None + warning.
        def boom(*args, **kwargs):
            raise RuntimeError("worker mati")

        self._patch(data, "get_ohlcv", boom)
        with self.assertLogs("laumology.screener", level="WARNING") as lg:
            row = screener._screen_one(("AAA", None, False))
        self.assertIsNone(row)
        self.assertTrue(any("screen worker AAA" in str(x) for x in lg.output), lg.output)

    def test_prefetch_batch_gagal_tidak_senyap(self):
        # Universe besar: prefetch batch gagal -> warning, scan lanjut.
        tickers = [f"T{i:02d}" for i in range(41)]

        def boom(*args, **kwargs):
            raise RuntimeError("prefetch mati")

        self._patch(data, "prefetch", boom)
        self._patch(data, "get_ohlcv", boom)
        with self.assertLogs("laumology.screener", level="WARNING") as lg:
            screener.screen(tickers)
        self.assertTrue(any("prefetch batch" in str(x) for x in lg.output), lg.output)

    def test_value_fallback_tidak_senyap(self):
        # Kolom Volume hilang -> turnover error -> Value fallback 0.0
        # (bisa menyingkirkan saham dari filter min_value) -> warning.

        class FakeAnalysis:
            def as_row(self):
                return {"Ticker": "TEST"}

        self._patch(screener, "analyze", lambda df, t, light=True: FakeAnalysis())
        with self.assertLogs("laumology.screener", level="WARNING") as lg:
            row = screener._row_from_df("TEST", pd.DataFrame({"Close": range(100)}))
        self.assertEqual(row["Value"], 0.0)
        self.assertTrue(any("TEST" in str(x) for x in lg.output), lg.output)


if __name__ == "__main__":
    unittest.main()
