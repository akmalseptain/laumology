"""Tes observabilitas market.overview (batch-45) - ticker hilang dari breadth tidak senyap.

Butuh pandas/numpy (CI). Repro lokal: py_compile saja (jalur lama).
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

import data
import market


def make_df(n: int = 320, seed: int = 7) -> pd.DataFrame:
    """Resep df engine (sama dengan tests/test_engine.py, deterministik)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n, freq="D")
    ret = rng.normal(0.0006, 0.02, n)
    close = 1000.0 * np.cumprod(1.0 + ret)
    open_ = close * (1.0 + rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0, 0.008, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0, 0.008, n)))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


class MarketSilentTest(unittest.TestCase):
    def setUp(self):
        self._restore = []

        def flaky(t, *args, **kwargs):
            if t == "AAA":
                raise RuntimeError("hulu mati")
            return make_df()

        self._patch(data, "get_ohlcv", flaky)

    def tearDown(self):
        for obj, name, orig in reversed(self._restore):
            setattr(obj, name, orig)

    def _patch(self, obj, name, value):
        self._restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def test_overview_ticker_gagal_tidak_senyap(self):
        # Ticker gagal -> warning; ticker sehat tetap masuk ringkasan.
        with self.assertLogs("laumology.market", level="WARNING") as lg:
            out = market.overview(["AAA", "BBB"])
        self.assertTrue(any("AAA" in str(x) for x in lg.output), lg.output)
        self.assertIn("ihsg", out)
        # Ticker sehat tetap dihitung (bukan dibatalkan semua).
        self.assertFalse(any("BBB" in str(x) for x in lg.output), lg.output)


if __name__ == "__main__":
    unittest.main()
