from __future__ import annotations

import unittest

import numpy as np
import pandas as pd


def make_df(n: int = 320, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n, freq="D")
    ret = rng.normal(0.0006, 0.02, n)
    close = 1000.0 * np.cumprod(1.0 + ret)
    open_ = close * (1.0 + rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0, 0.008, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0, 0.008, n)))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


class TestIndicators(unittest.TestCase):
    def test_columns(self):
        import indicators
        d = indicators.add_indicators(make_df())
        for col in ["ma20", "ma50", "ma200", "rsi", "macd", "atr", "supertrend",
                    "squeeze_on", "sqz_mom", "chop", "adr_pct", "avwap",
                    "dc_upper", "dc_lower", "efi", "gk_vol"]:
            self.assertIn(col, d.columns, col)


class TestSignals(unittest.TestCase):
    def test_analyze(self):
        import signals
        a = signals.analyze(make_df(), "TEST")
        self.assertIn(a.signal, ["STRONG BUY", "BUY", "ACCUMULATE", "HOLD", "SELL", "AVOID"])
        self.assertLess(a.stop_loss, a.entry)
        self.assertIn("konfluensi", a.components)
        self.assertGreaterEqual(a.confidence, 0)
        self.assertLessEqual(a.confidence, 100)


class TestBacktest(unittest.TestCase):
    def test_backtest_fields(self):
        import backtest
        r = backtest.backtest(make_df(), "TEST")
        self.assertGreaterEqual(r.n_trades, 0)
        self.assertEqual(len(r.equity_curve), len(r.dates))
        self.assertTrue(0.0 <= r.win_rate <= 1.0)

    def test_costs_reduce_return(self):
        import backtest
        df = make_df()
        gross = backtest.backtest(df, "TEST", fee_buy=0.0, fee_sell=0.0, slip=0.0)
        net = backtest.backtest(df, "TEST", fee_buy=0.003, fee_sell=0.004, slip=0.002)
        self.assertLessEqual(net.total_return, gross.total_return + 1e-9)


class TestValidate(unittest.TestCase):
    def test_clean(self):
        import validate
        self.assertTrue(validate.check_df(make_df(250))["ok"])

    def test_bad_hl(self):
        import validate
        df = make_df(250)
        df.iloc[5, df.columns.get_loc("High")] = df["Low"].iloc[5] - 1.0
        self.assertFalse(validate.check_df(df)["ok"])


class TestRisk(unittest.TestCase):
    def test_position_size(self):
        import risk
        r = risk.position_size(100_000_000, 1.5, 1000, 950)
        self.assertAlmostEqual(r["risk_amount"], 1_500_000)
        self.assertGreaterEqual(r["lots"], 0)

    def test_metrics(self):
        import metrics
        m = metrics.risk_metrics([1.0, 1.1, 1.05, 1.2, 1.15, 1.3], [5, -2, 8])
        self.assertIn("sharpe", m)
        self.assertIn("kelly", m)


if __name__ == "__main__":
    unittest.main()
