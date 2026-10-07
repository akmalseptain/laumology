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

    def test_pivot_no_lookahead(self):
        import indicators
        d = indicators.add_indicators(make_df())
        i = 100
        exp = (d["High"].iloc[i - 1] + d["Low"].iloc[i - 1] + d["Close"].iloc[i - 1]) / 3.0
        self.assertAlmostEqual(float(d["pivot_pp"].iloc[i]), float(exp), places=6)


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
        self.assertIsInstance(a.market_regime, str)


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


class TestCalibration(unittest.TestCase):
    def _model(self, k):
        return {
            "horizon": 10, "features": list(k), "coef": [1.0] * len(k),
            "intercept": 0.0, "mu": [0.0] * len(k), "sd": [1.0] * len(k),
            "base_rate": 0.5, "alpha": 0.5,
        }

    def test_prob_to_score(self):
        import calibration
        self.assertAlmostEqual(calibration.prob_to_score(0.5, 0.5), 50.0, places=3)
        self.assertAlmostEqual(calibration.prob_to_score(1.0, 0.5), 100.0, places=3)
        self.assertAlmostEqual(calibration.prob_to_score(0.0, 0.5), 0.0, places=3)
        self.assertLess(calibration.prob_to_score(0.4, 0.5), 50.0)
        self.assertGreater(calibration.prob_to_score(0.6, 0.5), 50.0)

    def test_feature_frame(self):
        import calibration
        import indicators
        from factors import SCORE_COMPONENTS
        d = indicators.add_indicators(make_df())
        X = calibration.feature_frame(d)
        self.assertEqual(list(X.columns), SCORE_COMPONENTS)
        vals = X.to_numpy()
        self.assertTrue((vals >= 0).all() and (vals <= 1).all())

    def test_prob_up_with_model(self):
        import calibration
        import indicators
        from factors import SCORE_COMPONENTS
        d = indicators.add_indicators(make_df())
        p = calibration.prob_up(d, self._model(SCORE_COMPONENTS))
        self.assertIsNotNone(p)
        self.assertTrue(0.0 <= p <= 1.0)

    def test_analyze_uses_model(self):
        import os
        import tempfile

        import calibration
        import indicators
        import signals
        from config import settings
        from factors import SCORE_COMPONENTS

        d = make_df()
        model = self._model(SCORE_COMPONENTS)
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        old = settings.score_model_path
        try:
            settings.score_model_path = path
            calibration.save_model(model)
            a = signals.analyze(d, "TEST")
            self.assertTrue(a.model_used)
            self.assertIsNotNone(a.prob_up)
            self.assertIsNotNone(a.score_opt)
        finally:
            settings.score_model_path = old
            calibration._MODEL_CACHE.update(mtime=None, model=None, path=None)
            try:
                os.unlink(path)
            except OSError:
                pass


class TestLegacyRegression(unittest.TestCase):
    def _freeze(self):
        from config import settings
        old = (settings.regime_filter, settings.enable_decision, settings.use_optimized_score)
        settings.regime_filter = False
        settings.enable_decision = False
        settings.use_optimized_score = False
        return old

    def _restore(self, old):
        from config import settings
        settings.regime_filter, settings.enable_decision, settings.use_optimized_score = old

    def test_analyze_golden(self):
        import signals
        old = self._freeze()
        try:
            a = signals.analyze(make_df(), "TEST")
            self.assertEqual(a.signal, "SELL")
            self.assertEqual(a.score, 26)
            self.assertAlmostEqual(a.stop_loss, 476.26, places=1)
            self.assertAlmostEqual(a.tp1, 602.84, places=1)
        finally:
            self._restore(old)

    def test_score_frame_unchanged(self):
        import factors
        import indicators
        d = indicators.add_indicators(make_df())
        sc = factors.score_frame(d)
        self.assertEqual(list(sc.columns), factors.SCORE_COMPONENTS + ["score"])
        self.assertTrue(bool(sc["score"].between(0, 100).all()))


class TestDecision(unittest.TestCase):
    def test_structure(self):
        import indicators
        import structure
        d = indicators.add_indicators(make_df())
        s = structure.market_structure(d)
        self.assertIn(s["bias"], ("bullish", "bearish", "ranging"))
        self.assertIn("bos", s)
        self.assertIn("last_swing_low", s)

    def test_decision_shape(self):
        import decision
        import indicators
        d = indicators.add_indicators(make_df())
        dec = decision.evaluate(d, "TEST", market="ranging", weekly="Netral", monthly="Netral")
        self.assertIn(dec["direction"], ("BUY", "SELL", "HOLD", "ACCUMULATE", "HOLD (REDUCE)", "NO TRADE"))
        self.assertTrue(0 <= dec["confidence"] <= 100)
        self.assertTrue(0 <= dec["signal_score"] <= 100)
        self.assertIn("regime", dec)
        self.assertIn("reasons", dec)

    def test_signal_series(self):
        import decision
        import indicators
        d = indicators.add_indicators(make_df())
        sig = decision.signal_series(d)
        self.assertEqual(len(sig), len(d))
        self.assertTrue(set(int(x) for x in sig.unique()).issubset({-1, 0, 1}))


class TestABCompare(unittest.TestCase):
    def test_decision_backtest_runs(self):
        import backtest
        r = backtest.backtest_decision(make_df(320), "TEST")
        self.assertGreaterEqual(r.n_trades, 0)
        self.assertEqual(len(r.equity_curve), len(r.dates))

    def test_compare_keys(self):
        import backtest
        res = backtest.compare_backtest(make_df(320), "TEST", max_hold=20, tp_rr=3.0, sl_mult=2.0)
        for side in ("legacy", "decision"):
            for f in ("n_trades", "win_rate", "profit_factor", "expectancy",
                      "avg_bars", "tp_rate", "sl_rate", "timeout_rate"):
                self.assertIn(f, res[side])


class TestStockLayer(unittest.TestCase):
    def test_liquidity_dq_gap(self):
        import indicators
        import stock
        d = indicators.add_indicators(make_df())
        self.assertIn(stock.liquidity(d)["status"], ("GOOD", "OK", "LOW"))
        self.assertIn(stock.data_quality(d)["status"], ("GOOD", "WARNING", "INSUFFICIENT"))
        self.assertIn(stock.gap(d)["type"], ("up", "down", "none"))

    def test_price_limit(self):
        import stock
        self.assertEqual(stock.price_limit_pct(1000), 7.0)
        self.assertEqual(stock.price_limit_pct(6000), 13.0)

    def test_evaluate_stock(self):
        import decision
        import indicators
        import stock
        d = indicators.add_indicators(make_df())
        dec = decision.evaluate(d, "TEST", market="ranging")
        st = stock.evaluate_stock(d, "TEST", dec, sector_name="Perbankan")
        for k in ("market", "sector", "technical", "relative_strength", "liquidity", "risk"):
            self.assertIn(k, st["scores"])
        self.assertIn("risk_factors", st)


def make_trend_df(n: int = 320, drift: float = 0.001, vol: float = 0.015, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n, freq="D")
    ret = rng.normal(drift, vol, n)
    close = 1000.0 * np.cumprod(1.0 + ret)
    open_ = close * (1.0 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0, 0.006, n)))
    vol_u = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol_u}, index=idx)


class TestBaselineRegimes(unittest.TestCase):
    def _regimes(self):
        return {
            "uptrend": make_trend_df(drift=0.002, vol=0.012),
            "downtrend": make_trend_df(drift=-0.002, vol=0.012),
            "sideways": make_trend_df(drift=0.0, vol=0.010),
            "highvol": make_trend_df(drift=0.0, vol=0.05),
            "flat": make_trend_df(drift=0.0, vol=0.0001),
        }

    def test_analyze_all_regimes(self):
        import signals
        from config import settings
        old = settings.regime_filter, settings.enable_decision
        settings.regime_filter = False
        settings.enable_decision = True
        try:
            for name, df in self._regimes().items():
                a = signals.analyze(df, "REG")
                self.assertIn(a.signal, ["STRONG BUY", "BUY", "ACCUMULATE", "HOLD", "SELL", "AVOID"], name)
                self.assertTrue(0 <= a.score <= 100)
                if a.decision:
                    self.assertIn(a.decision["direction"],
                                  ("BUY", "SELL", "HOLD", "ACCUMULATE", "HOLD (REDUCE)", "NO TRADE"))
        finally:
            settings.regime_filter, settings.enable_decision = old

    def test_decision_runs_all_regimes(self):
        import decision
        import indicators
        for name, df in self._regimes().items():
            d = indicators.add_indicators(df)
            dec = decision.evaluate(d, "REG", market="ranging")
            self.assertTrue(0 <= dec["signal_score"] <= 100, name)
            self.assertTrue(0 <= dec["confidence"] <= 100, name)


class TestDataQualityGate(unittest.TestCase):
    def test_quality_score_clean(self):
        import validate
        q = validate.quality_score(make_df(320))
        self.assertGreaterEqual(q["score"], 80)
        self.assertEqual(q["status"], "GOOD")

    def test_quality_score_bad(self):
        import validate
        df = make_df(320)
        df.iloc[5, df.columns.get_loc("High")] = df["Low"].iloc[5] - 1.0
        q = validate.quality_score(df)
        self.assertLess(q["score"], 80)
        self.assertIn(q["status"], ("WARNING", "INSUFFICIENT"))

    def test_decision_no_trade_low_quality(self):
        import decision
        import indicators
        d = indicators.add_indicators(make_df())
        dec = decision.evaluate(d, "X", data_quality_score=5.0)
        self.assertTrue(dec["no_trade"])
        self.assertTrue(any("Kualitas data" in r for r in dec["no_trade_reasons"]))


class TestMusyawarahReconcile(unittest.TestCase):
    def test_veto_on_no_trade(self):
        import musyawarah
        v = musyawarah.reconcile_vetoes("BUY", {"no_trade": True, "no_trade_reasons": ["Volatilitas ekstrem (pctl 98)"]}, "uptrend")
        self.assertTrue(any("NO TRADE" in x for x in v))

    def test_veto_on_conflicting_direction(self):
        import musyawarah
        v = musyawarah.reconcile_vetoes("BUY", {"direction": "SELL", "no_trade": False}, "uptrend")
        self.assertTrue(any("SELL" in x for x in v))

    def test_veto_on_downtrend(self):
        import musyawarah
        v = musyawarah.reconcile_vetoes("BUY", {"direction": "HOLD", "no_trade": False}, "downtrend")
        self.assertTrue(any("downtrend" in x for x in v))

    def test_no_veto_when_wait_or_aligned(self):
        import musyawarah
        self.assertEqual(musyawarah.reconcile_vetoes("WAIT", {"no_trade": True}, "uptrend"), [])
        self.assertEqual(musyawarah.reconcile_vetoes("BUY", {"direction": "BUY", "no_trade": False}, "uptrend"), [])


class TestLightAnalyze(unittest.TestCase):
    def test_light_matches_full_row(self):
        import signals
        from config import settings
        old = (settings.regime_filter, settings.enable_decision, settings.use_optimized_score)
        settings.regime_filter = settings.enable_decision = settings.use_optimized_score = False
        try:
            df = make_df(400)
            full = signals.analyze(df, "T", light=False)
            light = signals.analyze(df, "T", light=True)
            self.assertEqual(full.as_row(), light.as_row())
            self.assertEqual(full.signal, light.signal)
            self.assertEqual(full.score, light.score)
        finally:
            settings.regime_filter, settings.enable_decision, settings.use_optimized_score = old


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
