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

    def test_analysis_has_modern_indicators(self):
        import signals
        a = signals.analyze(make_df(), "TEST")
        self.assertGreater(a.hma20, 0)
        self.assertGreater(a.kama, 0)
        self.assertGreaterEqual(a.aroon_up, 0)
        self.assertGreaterEqual(a.vortex_plus, 0)
        self.assertGreaterEqual(a.rvol, 0)


class TestCandidates(unittest.TestCase):
    def test_candidate_frame(self):
        import indicators
        import signals
        d = indicators.add_indicators(make_df())
        cf = signals.candidate_frame(d)
        for k in signals.CANDIDATE_FACTORS:
            self.assertIn(k, cf.columns, k)
            self.assertEqual(len(cf[k]), len(d))
        self.assertIn("confidence", cf.columns)

    def test_accuracy_reports_candidates(self):
        import validation
        res = validation.analyze_accuracy(make_df(400), horizon=10)
        self.assertIn("candidates", res)
        self.assertIn("recommendations", res)
        self.assertIn("min_edge", res)
        for c in res["candidates"]:
            self.assertIn(c["factor"], __import__("signals").CANDIDATE_FACTORS)

    def test_ml_include_candidates(self):
        import ml
        base = ml.predict(make_df(400), "TEST", include_candidates=False)
        full = ml.predict(make_df(400), "TEST", include_candidates=True)
        self.assertEqual(len(base["features"]), len(__import__("signals").FACTOR_KEYS))
        self.assertTrue(full["include_candidates"])
        self.assertGreater(len(full["features"]), len(base["features"]))


class TestNews(unittest.TestCase):
    def test_market_news_shape(self):
        import news
        res = news.get_market_news()
        for key in ("ticker", "count", "avg_sentiment", "label", "items"):
            self.assertIn(key, res)


class TestWiring(unittest.TestCase):
    def test_factor_reexport(self):
        import factors
        import signals
        self.assertEqual(signals.FACTOR_KEYS, factors.FACTOR_KEYS)
        self.assertEqual(signals.CANDIDATE_FACTORS, factors.CANDIDATE_FACTORS)

    def test_routes_registered(self):
        import webapp
        paths = {str(r) for r in webapp.app.url_map.iter_rules()}
        for p in ["/", "/health", "/api/analyze", "/api/ohlc", "/api/screen",
                  "/api/calibrate", "/api/news/market", "/api/scan/start", "/api/paper"]:
            self.assertIn(p, paths)


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
