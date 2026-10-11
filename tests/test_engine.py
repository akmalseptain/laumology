from __future__ import annotations

import unittest
from pathlib import Path

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

    def test_ml_excludes_forward_nan_tail(self):
        """Baris tanpa hasil forward (horizon terakhir) tidak boleh jadi sampel berlabel."""
        import indicators
        import ml

        df = make_df(400)
        horizon = 10
        d = indicators.add_indicators(df).dropna(
            subset=["ma50", "ma200", "atr", "supertrend"]
        )
        res = ml.predict(df, "TEST", horizon=horizon, include_candidates=False)
        # Tanpa perbaikan, target NaN diubah ke 0 lebih dulu sehingga mask tidak
        # pernah aktif dan seluruh baris (termasuk yang tanpa hasil forward)
        # ikut terlatih. Sampel harus berkurang tepat `horizon` baris.
        self.assertEqual(res["samples"], len(d) - horizon)


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


class TestCalibrationLabels(unittest.TestCase):
    """Baris tanpa forward return (look-ahead) tidak boleh dilabeli 'down'."""

    def test_last_horizon_rows_not_labeled_down(self):
        import calibration
        import data

        n = 320
        idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n, freq="D")
        close = np.linspace(1000.0, 2000.0, n)
        df = pd.DataFrame({
            "Open": close * 0.999, "High": close * 1.002,
            "Low": close * 0.998, "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        }, index=idx)
        old = data.get_ohlcv
        data.get_ohlcv = lambda t, *a, **k: df
        try:
            frames, used, errors = calibration._collect(["TEST"], horizon=5, min_bars=40)
        finally:
            data.get_ohlcv = old
        self.assertTrue(frames)
        self.assertEqual(used, ["TEST"])
        for f in frames:
            # Deret naik monoton: setiap forward return yang diketahui > 0.
            self.assertTrue(bool((f["_y"] == 1).all()))


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


class TestSharedIndicators(unittest.TestCase):
    def test_analyze_with_precomputed_d_identical(self):
        import indicators
        import signals
        from config import settings
        old = (settings.regime_filter, settings.enable_decision, settings.use_optimized_score)
        settings.regime_filter = settings.enable_decision = settings.use_optimized_score = False
        try:
            df = make_df(400)
            a1 = signals.analyze(df, "T")
            d = indicators.add_indicators(df)
            a2 = signals.analyze(df, "T", d=d)
            self.assertEqual(a1.as_row(), a2.as_row())
            self.assertEqual(a1.stop_loss, a2.stop_loss)
            self.assertEqual(a1.tp1, a2.tp1)
            self.assertEqual(a1.tp2, a2.tp2)
            self.assertEqual(a1.reasons, a2.reasons)
            self.assertEqual(a1.warnings, a2.warnings)
            self.assertEqual(a1.components, a2.components)
            self.assertEqual(a1.checklist, a2.checklist)
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


class TestPortfolioInputValidation(unittest.TestCase):
    """Endpoint portofolio harus membalas 400 (bukan 500) untuk input tidak valid."""

    def setUp(self):
        import webapp
        self.client = webapp.app.test_client()

    def test_portfolio_risk_bad_capital(self):
        r = self.client.post("/api/portfolio-risk", json={"capital": "abc", "positions": []})
        self.assertEqual(r.status_code, 400)

    def test_portfolio_risk_positions_not_list(self):
        r = self.client.post("/api/portfolio-risk", json={"positions": "bukan-list"})
        self.assertEqual(r.status_code, 400)

    def test_portfolio_risk_position_not_dict(self):
        r = self.client.post("/api/portfolio-risk", json={"positions": ["x"]})
        self.assertEqual(r.status_code, 400)

    def test_portfolio_risk_unhashable_ticker(self):
        r = self.client.post("/api/portfolio-risk",
                             json={"positions": [{"ticker": ["BBCA"], "lots": 1, "entry": 100}]})
        self.assertNotEqual(r.status_code, 500)

    def test_portfolio_risk_body_not_object(self):
        r = self.client.post("/api/portfolio-risk", json=[1, 2, 3])
        self.assertEqual(r.status_code, 400)

    def test_paper_open_body_not_object(self):
        r = self.client.post("/api/paper/open", json=[1, 2, 3])
        self.assertEqual(r.status_code, 400)

    def test_paper_open_bad_stop(self):
        r = self.client.post("/api/paper/open",
                             json={"ticker": "BBCA", "entry": 100, "lots": 1, "stop": "abc"})
        self.assertEqual(r.status_code, 400)

    def test_paper_open_ticker_not_string(self):
        r = self.client.post("/api/paper/open", json={"ticker": 123, "entry": 1, "lots": 1})
        self.assertEqual(r.status_code, 400)

    def test_paper_open_bad_side(self):
        r = self.client.post("/api/paper/open",
                             json={"ticker": "BBCA", "entry": 1, "lots": 1, "side": "HOLD"})
        self.assertEqual(r.status_code, 400)

    def test_paper_open_missing_entry_rejected(self):
        # UI mengirim entry=null saat kolom Entry dibiarkan kosong. Dulu ini
        # disimpan sebagai entry=0 sehingga /api/paper menghitung P/L dari harga
        # 0 dan menampilkan seluruh notional sebagai laba. Harus 400 & tanpa DB.
        from unittest.mock import patch

        with patch("store.paper_open") as m:
            r = self.client.post("/api/paper/open",
                                 json={"ticker": "BBCA", "entry": None, "lots": 5})
        self.assertEqual(r.status_code, 400)
        m.assert_not_called()

    def test_paper_open_non_positive_entry_or_lots_rejected(self):
        from unittest.mock import patch

        for body in (
            {"ticker": "BBCA", "entry": 0, "lots": 5},
            {"ticker": "BBCA", "entry": -10, "lots": 5},
            {"ticker": "BBCA", "entry": 100, "lots": 0},
            {"ticker": "BBCA", "entry": 100, "lots": -1},
            # NaN/inf juga tidak boleh lolos (P/L jadi tidak wajar).
            {"ticker": "BBCA", "entry": "nan", "lots": 5},
            {"ticker": "BBCA", "entry": "inf", "lots": 5},
            {"ticker": "BBCA", "entry": 100, "lots": float("inf")},
        ):
            with patch("store.paper_open") as m:
                r = self.client.post("/api/paper/open", json=body)
            self.assertEqual(r.status_code, 400, msg=str(body))
            m.assert_not_called()

    def test_paper_open_note_not_string(self):
        r = self.client.post("/api/paper/open",
                             json={"ticker": "BBCA", "entry": 1, "lots": 1, "note": [1]})
        self.assertEqual(r.status_code, 400)

    def test_paper_open_note_empty_list_not_500(self):
        # `[] or ""` lolos validasi lalu nilai mentah dikirim ke SQLite -> 500.
        r = self.client.post("/api/paper/open",
                             json={"ticker": "BBCA", "entry": 1, "lots": 1, "note": []})
        self.assertEqual(r.status_code, 400)

    def test_paper_close_note_empty_list_not_500(self):
        from unittest.mock import patch

        fake_row = {"id": 999, "ticker": "BBCA", "entry": 100.0, "lots": 1}
        # Tidak menyentuh DB: paper_rows dipalsukan; validasi note gagal -> 400.
        with patch("store.paper_rows", return_value=[fake_row]):
            r = self.client.post("/api/paper/close",
                                 json={"id": 999, "exit": 100, "note": []})
        self.assertEqual(r.status_code, 400)


class TestPaperPnlSide(unittest.TestCase):
    """PnL paper trading harus mengikuti arah posisi (SELL untung saat harga turun)."""

    def setUp(self):
        import webapp
        self.client = webapp.app.test_client()

    def test_unrealized_pnl_respects_side(self):
        from unittest.mock import patch

        rows = [
            {"id": 1, "ticker": "BBCA", "side": "BUY", "entry": 1000.0, "lots": 2, "status": "OPEN"},
            {"id": 2, "ticker": "BBCA", "side": "SELL", "entry": 1000.0, "lots": 2, "status": "OPEN"},
        ]
        with patch("store.paper_rows", return_value=rows), \
             patch("data.get_quote", return_value={"last": 1100.0}):
            resp = self.client.get("/api/paper")
        self.assertEqual(resp.status_code, 200)
        out = resp.get_json()["rows"]
        # BUY: (1100-1000) * 2 lot * 100 = +20.000 (naik 10%)
        self.assertEqual(out[0]["pnl"], 20000.0)
        self.assertEqual(out[0]["pnl_pct"], 10.0)
        # SELL: harga naik 10% -> rugi -20.000
        self.assertEqual(out[1]["pnl"], -20000.0)
        self.assertEqual(out[1]["pnl_pct"], -10.0)

    def test_realized_pnl_respects_side(self):
        from unittest.mock import patch

        row = {"id": 5, "ticker": "BBCA", "side": "SELL", "entry": 1000.0, "lots": 1, "status": "OPEN"}
        captured = {}

        def fake_close(pid, exit_price, pnl, note=""):
            captured["pid"], captured["exit"], captured["pnl"] = pid, exit_price, pnl

        with patch("store.paper_rows", return_value=[row]), \
             patch("store.paper_close", side_effect=fake_close):
            resp = self.client.post("/api/paper/close", json={"id": 5, "exit": 900.0})
        self.assertEqual(resp.status_code, 200)
        # SELL: harga turun 1000 -> 900 = untung (1000-900) * 1 * 100 = +10.000
        self.assertEqual(captured["pnl"], 10000.0)
        self.assertEqual(resp.get_json()["pnl"], 10000.0)

    def test_realized_close_non_positive_or_nonfinite_exit_rejected(self):
        from unittest.mock import patch

        row = {"id": 5, "ticker": "BBCA", "side": "SELL", "entry": 1000.0, "lots": 1, "status": "OPEN"}
        for exit_price in (0, -5, "nan", "inf", float("inf")):
            with patch("store.paper_rows", return_value=[row]), \
                 patch("store.paper_close") as m:
                resp = self.client.post("/api/paper/close",
                                        json={"id": 5, "exit": exit_price})
            self.assertEqual(resp.status_code, 400, msg=str(exit_price))
            m.assert_not_called()

    def test_realized_close_fallback_quote_zero_rejected(self):
        from unittest.mock import patch

        row = {"id": 5, "ticker": "BBCA", "side": "SELL", "entry": 1000.0, "lots": 1, "status": "OPEN"}
        with patch("store.paper_rows", return_value=[row]), \
             patch("data.get_quote", return_value={"last": 0.0}), \
             patch("store.paper_close") as m:
            resp = self.client.post("/api/paper/close", json={"id": 5})
        self.assertEqual(resp.status_code, 400)
        m.assert_not_called()


class TestScreenerEfficiency(unittest.TestCase):
    """Screener tidak boleh membaca OHLCV dua kali per emiten di jalur serial."""

    def test_screen_single_ohlcv_read_serial(self):
        import data
        import screener

        calls = {}

        def fake_get_ohlcv(t, period=None, use_cache=True, **kwargs):
            calls[t] = calls.get(t, 0) + 1
            return make_df(320)

        old = data.get_ohlcv
        data.get_ohlcv = fake_get_ohlcv
        try:
            screener._ROW_CACHE.clear()
            screener.screen(["AAA", "BBB", "CCC"], refresh=True)
        finally:
            data.get_ohlcv = old
            screener._ROW_CACHE.clear()
        for t in ("AAA", "BBB", "CCC"):
            self.assertEqual(calls.get(t, 0), 1, f"{t} dibaca {calls.get(t, 0)} kali")


class TestTtlCacheBound(unittest.TestCase):
    """Cache TTL tidak boleh tumbuh tak terbatas saat entri masih segar."""

    def test_cache_stays_bounded_with_fresh_entries(self):
        import ttlcache

        ttlcache.clear()
        try:
            for i in range(1200):
                ttlcache.set(f"bound:{i}", {"i": i}, ttl=3600.0)
            size = ttlcache.stats()["size"]
            self.assertLessEqual(size, ttlcache._MAX_ENTRIES)
            # Entri terbaru tetap tersedia (eviksi dari yang paling lama).
            self.assertIsNotNone(ttlcache.get("bound:1199"))
        finally:
            ttlcache.clear()


class TestQuoteCacheBound(unittest.TestCase):
    """Cache quote tidak boleh tumbuh tak terbatas oleh ticker arbitrer dari klien."""

    def test_quote_cache_stays_bounded(self):
        from unittest.mock import patch

        import data

        data._quote_cache.clear()
        total = data._QUOTE_CACHE_MAX + 300
        try:
            with patch("realtime.fetch_quote", return_value=None), \
                 patch("data._yf_quote",
                       side_effect=lambda yt, now: {"last": 1.0, "symbol": yt}):
                for i in range(total):
                    self.assertIsNotNone(data.get_quote(f"T{i}"))
            self.assertLessEqual(len(data._quote_cache), data._QUOTE_CACHE_MAX)
            # Entri terbaru tetap tersedia (eviksi dari yang paling lama).
            self.assertIn(data.to_yahoo(f"T{total - 1}"), data._quote_cache)
        finally:
            data._quote_cache.clear()

    def test_expired_quote_evicted_on_read(self):
        """Entri kedaluwarsa harus dibuang saat dibaca (bukan menumpuk)."""
        import time
        from unittest.mock import patch

        import data

        yt = data.to_yahoo("OLD")
        data._quote_cache[yt] = (time.time() - 10_000.0, {"last": 1.0})
        try:
            # Refetch tidak menghasilkan quote -> entri kedaluwarsa tak diisi ulang.
            with patch("realtime.fetch_quote", return_value=None), \
                 patch("data._yf_quote", return_value=None):
                self.assertIsNone(data.get_quote("OLD"))
            self.assertNotIn(yt, data._quote_cache)
        finally:
            data._quote_cache.clear()


class TestRateLimitEnvRobustness(unittest.TestCase):
    """Env RATE_LIMIT_PER_MIN buruk tidak boleh melumpuhkan seluruh endpoint /api."""

    def setUp(self):
        import os

        import state

        self._state = state
        self._old = os.environ.get("RATE_LIMIT_PER_MIN")
        state._rl.clear()

    def tearDown(self):
        import os

        if self._old is None:
            os.environ.pop("RATE_LIMIT_PER_MIN", None)
        else:
            os.environ["RATE_LIMIT_PER_MIN"] = self._old
        self._state._rl.clear()

    def test_invalid_value_falls_back_to_default(self):
        import os

        os.environ["RATE_LIMIT_PER_MIN"] = "abc"
        self.assertEqual(self._state._rate_limit_per_min(), 600)

    def test_blank_value_falls_back_to_default(self):
        import os

        os.environ["RATE_LIMIT_PER_MIN"] = ""
        self.assertEqual(self._state._rate_limit_per_min(), 600)

    def test_non_positive_value_falls_back_to_default(self):
        import os

        os.environ["RATE_LIMIT_PER_MIN"] = "0"
        self.assertEqual(self._state._rate_limit_per_min(), 600)

    def test_valid_value_is_honored(self):
        import os

        os.environ["RATE_LIMIT_PER_MIN"] = "1"
        self.assertFalse(self._state.rate_limited("10.0.0.1"))
        self.assertTrue(self._state.rate_limited("10.0.0.1"))

    def test_api_still_serves_with_invalid_value(self):
        import os

        import webapp

        os.environ["RATE_LIMIT_PER_MIN"] = "abc"
        r = webapp.app.test_client().get("/api/version")
        self.assertEqual(r.status_code, 200)


class TestSchedulerEnvRobustness(unittest.TestCase):
    """Env scheduler buruk tidak boleh menggagalkan boot webapp (impor WSGI)."""

    _KEYS = ("ENABLE_SCHEDULER", "SCAN_INTERVAL", "SCAN_START_DELAY", "WARM_INTERVAL")

    def setUp(self):
        import os

        self._os = os
        self._saved = {k: os.environ.get(k) for k in self._KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                self._os.environ.pop(k, None)
            else:
                self._os.environ[k] = v

    def test_env_int_invalid_falls_back(self):
        import webapp

        self._os.environ["SCAN_INTERVAL"] = "abc"
        self.assertEqual(webapp._env_int("SCAN_INTERVAL", 900), 900)

    def test_env_int_blank_falls_back(self):
        import webapp

        self._os.environ["SCAN_INTERVAL"] = "   "
        self.assertEqual(webapp._env_int("SCAN_INTERVAL", 900), 900)

    def test_env_int_valid_honored(self):
        import webapp

        self._os.environ["SCAN_INTERVAL"] = "1200"
        self.assertEqual(webapp._env_int("SCAN_INTERVAL", 900), 1200)

    def test_maybe_start_scheduler_survives_bad_env(self):
        # Dulu `int("abc")` pada impor modul melempar ValueError -> WSGI gagal muat.
        from unittest.mock import patch

        import webapp

        self._os.environ["ENABLE_SCHEDULER"] = "1"
        self._os.environ["SCAN_INTERVAL"] = "abc"
        self._os.environ["SCAN_START_DELAY"] = "xyz"
        self._os.environ["WARM_INTERVAL"] = ""
        with patch.object(webapp.threading, "Thread") as th:
            webapp._maybe_start_scheduler()  # tidak boleh melempar
        th.assert_called_once()


class TestCachePathConfinement(unittest.TestCase):
    """``ticker`` dari klien tidak boleh menggeser path cache keluar cache_dir."""

    def _base(self):
        from config import settings

        return Path(settings.cache_dir).resolve()

    def _inside(self, ticker: str, period: str = "1y", interval: str = "1d"):
        import data

        return data._cache_path(data.to_yahoo(ticker), period, interval).resolve()

    def test_valid_ticker_name_unchanged(self):
        import data
        from config import settings

        p = data._cache_path("BBCA_JK", "1y", "1d")
        self.assertEqual(p, Path(settings.cache_dir) / "BBCA_JK_1y_1d.csv")

    def test_absolute_and_unc_tickers_stay_confined(self):
        base = self._base()
        for evil in ["//evilhost/share/x", "C:/windows/win", "/tmp/x", "..\\..\\escape"]:
            got = self._inside(evil)
            self.assertTrue(
                got.is_relative_to(base),
                f"{evil!r} keluar dari cache_dir: {got}",
            )

    def test_separators_removed_from_filename(self):
        import data

        name = data._cache_path(data.to_yahoo("//evilhost/share/x"), "1y", "1d").name
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)
        self.assertNotIn(":", name)


class TestCacheReadGuard(unittest.TestCase):
    """Cache OHLCV 0-byte/terpotong tidak boleh merusak ticker sampai TTL habis."""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self._patch = None

    def tearDown(self):
        if self._patch is not None:
            self._patch.stop()
        self._tmp.cleanup()

    def _use_tmp_cache(self):
        from unittest.mock import patch

        from config import settings

        self._patch = patch.object(settings, "cache_dir", self._tmp.name)
        self._patch.start()

    def test_read_cache_corrupt_returns_none_and_removes_file(self):
        import data

        self._use_tmp_cache()
        path = data._cache_path("FAKE_JK", "1y", "1d")
        path.write_bytes(b"")
        self.assertIsNone(data._read_cache(path))
        self.assertFalse(path.exists())

    def test_fresh_zero_byte_cache_downloads_and_repairs(self):
        from unittest.mock import patch

        import data

        self._use_tmp_cache()
        path = data._cache_path("FAKE_JK", "1y", "1d")
        path.write_bytes(b"")

        with patch.object(data.yf, "download", return_value=make_df(120)):
            out = data.get_ohlcv("FAKE", period="1y", interval="1d")

        self.assertFalse(out.empty)
        self.assertEqual(len(out), 120)
        self.assertGreater(path.stat().st_size, 0)
        self.assertFalse(data._read_cache(path).empty)

    def test_stale_valid_cache_still_returned_when_download_fails(self):
        import os
        import time
        from unittest.mock import patch

        import data

        self._use_tmp_cache()
        path = data._cache_path("FAKE_JK", "1y", "1d")
        make_df(90).to_csv(path)
        old = time.time() - 10 * 3600
        os.utime(path, (old, old))

        with patch.object(data.yf, "download", return_value=pd.DataFrame()):
            out = data.get_ohlcv("FAKE", period="1y", interval="1d")

        self.assertEqual(len(out), 90)

    def test_corrupt_stale_cache_raises_instead_of_empty_data_error(self):
        import os
        import time
        from unittest.mock import patch

        import data

        self._use_tmp_cache()
        path = data._cache_path("FAKE_JK", "1y", "1d")
        path.write_bytes(b"")
        old = time.time() - 10 * 3600
        os.utime(path, (old, old))

        with patch.object(data.yf, "download", return_value=pd.DataFrame()):
            with self.assertRaises(ValueError):
                data.get_ohlcv("FAKE", period="1y", interval="1d")
        self.assertFalse(path.exists())


class TestAtomicCacheWrite(unittest.TestCase):
    """Tulis cache OHLCV harus atomik: tak boleh ada berkas separuh saat gagal."""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self._patch = None

    def tearDown(self):
        if self._patch is not None:
            self._patch.stop()
        self._tmp.cleanup()

    def _use_tmp_cache(self):
        from unittest.mock import patch

        from config import settings

        self._patch = patch.object(settings, "cache_dir", self._tmp.name)
        self._patch.start()

    def _tmp_leftovers(self):
        return list(Path(self._tmp.name).glob("*.tmp"))

    def test_success_writes_file_and_no_temp_left(self):
        import data

        self._use_tmp_cache()
        path = data._cache_path("FAKE_JK", "1y", "1d")
        data._write_cache(make_df(50), path)

        self.assertTrue(path.exists())
        self.assertEqual(len(pd.read_csv(path, index_col=0)), 50)
        self.assertEqual(self._tmp_leftovers(), [])

    def test_failed_first_write_leaves_no_partial_file(self):
        from unittest.mock import patch

        import data

        self._use_tmp_cache()
        path = data._cache_path("FAKE_JK", "1y", "1d")

        with patch.object(data.os, "replace", side_effect=PermissionError("busy")):
            with self.assertRaises(PermissionError):
                data._write_cache(make_df(50), path)

        self.assertFalse(path.exists())
        self.assertEqual(self._tmp_leftovers(), [])

    def test_failed_overwrite_keeps_old_cache_intact(self):
        from unittest.mock import patch

        import data

        self._use_tmp_cache()
        path = data._cache_path("FAKE_JK", "1y", "1d")
        make_df(30).to_csv(path)
        before = path.read_bytes()

        with patch.object(data.os, "replace", side_effect=PermissionError("busy")):
            with self.assertRaises(PermissionError):
                data._write_cache(make_df(50), path)

        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(pd.read_csv(path, index_col=0)), 30)
        self.assertEqual(self._tmp_leftovers(), [])


if __name__ == "__main__":
    unittest.main()
