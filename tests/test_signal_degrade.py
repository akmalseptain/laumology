"""Tes observabilitas degradasi sinyal (batch-42) - jalur otomatis scan.

Kelas temuan batch-40/41: kegagalan best-effort yang ditelan SENYAP. Di
jalur sinyal, degradasi LEBIH BERBAHAYA dari crash: engine tetap
mengeluarkan sinyal, tapi dengan data keputusan/regime/RS/trend kosong
tanpa jejak. Tes ini mengunci dua sisi:
- fallback tetap bekerja (sinyal/nilai fallback tetap keluar), dan
- warning tercatat di logger laumology.signals (tidak senyap).

Butuh pandas/numpy (CI). Repro lokal: py_compile saja (jalur lama).
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

import data
import signals


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


def _no_datetime_df(n: int = 120) -> pd.DataFrame:
    """Index integer -> resample() melempar TypeError -> jalur except
    weekly/monthly trend tereksekusi secara deterministik."""
    return pd.DataFrame(
        {"Open": [999.0 + i for i in range(n)],
         "High": [1001.0 + i for i in range(n)],
         "Low": [998.0 + i for i in range(n)],
         "Close": [1000.0 + i for i in range(n)],
         "Volume": [1_000_000.0] * n},
        index=list(range(n)),
    )


class SignalDegradeTest(unittest.TestCase):
    def setUp(self):
        self._restore = []
        self._patch(data, "get_ohlcv", self._boom_fetch)

    def tearDown(self):
        for obj, name, orig in reversed(self._restore):
            setattr(obj, name, orig)

    def _patch(self, obj, name, value):
        self._restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    @staticmethod
    def _boom_fetch(*args, **kwargs):
        raise RuntimeError("sumber data mati")

    def test_market_regime_gagal_tidak_senyap(self):
        # Paksa recompute: umur cache regime dibuat nol.
        signals._MKT_CACHE.update(ts=0.0, regime="uptrend", recovery=False)
        with self.assertLogs("laumology.signals", level="WARNING") as lg:
            regime = signals.market_regime()
        self.assertEqual(regime, "unknown")
        self.assertTrue(any("market_regime" in str(x) for x in lg.output), lg.output)

    def test_relative_strength_gagal_tidak_senyap(self):
        with self.assertLogs("laumology.signals", level="WARNING") as lg:
            rs = signals.relative_strength(make_df())
        self.assertEqual(rs, (None, None))
        self.assertTrue(any("relative_strength" in str(x) for x in lg.output), lg.output)

    def test_weekly_monthly_trend_gagal_tidak_senyap(self):
        df = _no_datetime_df()
        with self.assertLogs("laumology.signals", level="WARNING") as lg:
            w = signals.weekly_trend(df)
            m = signals.monthly_trend(df)
        self.assertEqual(w, "Netral")
        self.assertEqual(m, "Netral")
        self.assertTrue(any("weekly_trend" in str(x) for x in lg.output), lg.output)
        self.assertTrue(any("monthly_trend" in str(x) for x in lg.output), lg.output)

    def test_decision_gagal_sinyal_tetap_keluar_dan_tidak_senyap(self):
        import decision as decision_mod

        def boom(*args, **kwargs):
            raise RuntimeError("decision engine meledak")

        self._patch(decision_mod, "evaluate", boom)
        with self.assertLogs("laumology.signals", level="WARNING") as lg:
            a = signals.analyze(make_df(), "TEST")
        # Sinyal tetap keluar (best-effort by design) - tidak meledak.
        self.assertTrue(hasattr(a, "signal"))
        # ...tapi TIDAK senyap: warning menyebut decision + ticker.
        self.assertTrue(
            any("decision" in str(x) and "TEST" in str(x) for x in lg.output),
            lg.output)


if __name__ == "__main__":
    unittest.main()
