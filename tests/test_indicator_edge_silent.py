"""Tes observabilitas indicator_edge: ticker gagal dievaluasi tidak senyap.

CI-only: indicator_edge butuh pandas/numpy + modul data/screener/indicators.
Ticker yang melempar exception saat event study dilewati - payload tetap
jujur (tickers_evaluated < tickers_total), kini dengan jejak log baru.
"""
import types
import unittest
from unittest import mock

try:
    import pandas as pd
    import indicator_edge as edge_mod
    _OK = True
except Exception:
    _OK = False


def _frame(n=280):
    idx = pd.date_range(end=pd.Timestamp("2026-10-23"), periods=n, freq="D")
    close = [100.0 + (i % 7) * 0.5 + 0.01 * i for i in range(n)]
    return pd.DataFrame(
        {"Open": close, "High": [c + 1.0 for c in close],
         "Low": [c - 1.0 for c in close], "Close": close,
         "Volume": [1e6 + 1000.0 * i for i in range(n)]},
        index=idx,
    )


def _fake_data(fail_tickers):
    def get_ohlcv(sym, *a, **k):
        if sym in fail_tickers:
            raise RuntimeError("fetch gagal")
        return _frame()
    return types.SimpleNamespace(get_ohlcv=get_ohlcv)


@unittest.skipUnless(_OK, "pandas/indicator_edge tidak tersedia (CI-only)")
class IndicatorEdgeSilentTest(unittest.TestCase):
    def test_ticker_gagal_dilewati_warning_dan_payload_jujur(self):
        fake_screener = types.SimpleNamespace(
            resolve_watchlist=lambda u: ["GAGAL1", "OKAA", "OKBB"])
        with mock.patch.object(edge_mod, "data", _fake_data({"GAGAL1"})), \
             mock.patch.object(edge_mod, "screener", fake_screener):
            with self.assertLogs("laumology.indicator_edge", level="WARNING") as ctx:
                out = edge_mod.evaluate(universe="uji", horizon=5, min_count=1)
        self.assertEqual(out["tickers_total"], 3)
        self.assertEqual(out["tickers_evaluated"], 2)
        self.assertEqual(len(ctx.output), 1)
        self.assertIn("GAGAL1", ctx.output[0])
        self.assertIn("RuntimeError", ctx.output[0])

    def test_semua_ticker_sehat_tanpa_warning(self):
        fake_screener = types.SimpleNamespace(
            resolve_watchlist=lambda u: ["OKAA", "OKBB"])
        with mock.patch.object(edge_mod, "data", _fake_data(set())), \
             mock.patch.object(edge_mod, "screener", fake_screener):
            with self.assertNoLogs("laumology.indicator_edge", level="WARNING"):
                out = edge_mod.evaluate(universe="uji", horizon=5, min_count=1)
        self.assertEqual(out["tickers_total"], 2)
        self.assertEqual(out["tickers_evaluated"], 2)


if __name__ == "__main__":
    unittest.main()
