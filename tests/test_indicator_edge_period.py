"""Tes periode riwayat indicator_edge: event study minta 3y, bukan default 1y.

CI-only: indicator_edge butuh pandas/numpy + modul data/screener/indicators.
Bug produksi (batch-51): /api/edge 0/45 emiten dievaluasi karena get_ohlcv
dipanggil tanpa period -> default 1y (~250 bar) < WARMUP_BARS + horizon + 5.
Fix: minta period="3y" + warning bila 0 emiten lolos ambang riwayat.
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


@unittest.skipUnless(_OK, "pandas/indicator_edge tidak tersedia (CI-only)")
class IndicatorEdgePeriodTest(unittest.TestCase):
    def test_evaluate_meminta_periode_3y_dan_payload_jujur(self):
        minta = []

        def get_ohlcv(sym, *a, **k):
            minta.append((sym, k.get("period")))
            return _frame(280)

        fake_data = types.SimpleNamespace(get_ohlcv=get_ohlcv)
        fake_screener = types.SimpleNamespace(
            resolve_watchlist=lambda u: ["OKAA", "OKBB"])
        with mock.patch.object(edge_mod, "data", fake_data), \
             mock.patch.object(edge_mod, "screener", fake_screener):
            with self.assertNoLogs("laumology.indicator_edge", level="WARNING"):
                out = edge_mod.evaluate(universe="uji", horizon=5, min_count=1)
        self.assertEqual(minta, [("OKAA", "3y"), ("OKBB", "3y")])
        self.assertEqual(out["tickers_evaluated"], 2)
        self.assertEqual(out["tickers_total"], 2)

    def test_riwayat_pendek_0_dari_1_dengan_warning(self):
        fake_data = types.SimpleNamespace(
            get_ohlcv=lambda sym, *a, **k: _frame(200))
        fake_screener = types.SimpleNamespace(
            resolve_watchlist=lambda u: ["PENDEK"])
        with mock.patch.object(edge_mod, "data", fake_data), \
             mock.patch.object(edge_mod, "screener", fake_screener):
            with self.assertLogs("laumology.indicator_edge", level="WARNING") as ctx:
                out = edge_mod.evaluate(universe="uji", horizon=5, min_count=1)
        self.assertEqual(out["tickers_evaluated"], 0)
        self.assertEqual(out["tickers_total"], 1)
        self.assertEqual(len(ctx.output), 1)
        self.assertIn("0/1", ctx.output[0])


if __name__ == "__main__":
    unittest.main()
