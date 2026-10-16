from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

# Nilai API_KEY asli (bila ada di lingkungan) disimpan agar dipulihkan seusai tes.
_SAVED_API_KEY = None


def setUpModule():
    """Isolasi tes dari `.env` lokal: kosongkan kredensial auth saat pengujian.

    ``webapp`` memuat berkas ``.env`` (termasuk ``API_KEY`` pribadi) saat impor.
    Tanpa ini, endpoint tulis yang terlindungi membalas 401 dan tes validasi
    input gagal. Nilai asli disimpan dan dipulihkan di ``tearDownModule``.
    """
    global _SAVED_API_KEY
    import os
    _SAVED_API_KEY = os.environ.get("API_KEY")
    os.environ["API_KEY"] = ""


def tearDownModule():
    import os
    if _SAVED_API_KEY is None:
        os.environ.pop("API_KEY", None)
    else:
        os.environ["API_KEY"] = _SAVED_API_KEY


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

    def test_avwap_no_lookahead(self):
        import indicators
        df = make_df()
        d = indicators.add_indicators(df)
        for cut in (50, 120, 200, 260):
            d_cut = indicators.add_indicators(df.iloc[: cut + 1])
            full = float(d["avwap"].iloc[cut])
            trunc = float(d_cut["avwap"].iloc[cut])
            if np.isnan(full) and np.isnan(trunc):
                continue
            self.assertAlmostEqual(full, trunc, places=9, msg=f"avwap[{cut}] bocor look-ahead")

    def test_avwap_last_bar_matches_legacy(self):
        import indicators
        df = make_df()
        d = indicators.add_indicators(df)
        anchor = indicators.auto_anchor_index(df["Low"], df["High"], lookback=120, order=5)
        legacy = indicators.anchored_vwap(df["High"], df["Low"], df["Close"], df["Volume"], anchor)
        self.assertAlmostEqual(
            float(d["avwap"].iloc[-1]), float(legacy.iloc[-1]), places=9
        )


class TestIndicatorCausality(unittest.TestCase):
    """Pagar kausalitas keluaran `add_indicators` (integritas data #1).

    Setiap kolom indikator wajib *truncation-invariant*: nilai bar ke-t dari
    ``add_indicators(df.iloc[:t+1])`` harus sama dengan ``add_indicators(df)``
    pada bar yang sama (toleransi 1e-9; pasangan NaN-NaN dilewati). Kolom yang
    butuh data setelah bar t (look-ahead) akan gagal di sini — pagar ini menjaga
    backtest/ML/kalibrasi tetap jujur, bukan menambah rumus baru.

    Kolom non-kausal sengaja TIDAK di-whitelist (fail-closed). Yang dikecualikan
    hanya kolom input mentah dan ``month`` (turunan index, bukan indikator).
    """

    INPUT_COLUMNS = frozenset({"Open", "High", "Low", "Close", "Volume"})
    NON_INDICATOR_COLUMNS = frozenset({"month"})
    # Whitelist non-kausal harus kosong; jangan jadikan pelarian.
    NON_CAUSAL_WHITELIST = frozenset()
    CUTS = (60, 120, 200, 280)
    SEEDS = (7, 42)
    TOL = 1e-9

    def _indicator_columns(self, d: pd.DataFrame) -> list[str]:
        excluded = self.INPUT_COLUMNS | self.NON_INDICATOR_COLUMNS
        cols = []
        for col in d.columns:
            if col in excluded:
                continue
            if pd.api.types.is_numeric_dtype(d[col]) or pd.api.types.is_bool_dtype(d[col]):
                cols.append(col)
        return cols

    def test_whitelist_starts_empty(self):
        self.assertEqual(self.NON_CAUSAL_WHITELIST, frozenset())

    def test_exclusions_are_minimal(self):
        import indicators
        d = indicators.add_indicators(make_df())
        covered = set(self._indicator_columns(d))
        excluded = set(d.columns) - covered
        # Bila kolom indikator ikut tergusur, pagar ini bolong diam-diam.
        self.assertEqual(excluded, set(self.INPUT_COLUMNS) | set(self.NON_INDICATOR_COLUMNS))

    def test_all_indicator_columns_truncation_invariant(self):
        import indicators
        for seed in self.SEEDS:
            df = make_df(seed=seed)
            full = indicators.add_indicators(df)
            cols = self._indicator_columns(full)
            self.assertTrue(cols)
            for cut in self.CUTS:
                trunc = indicators.add_indicators(df.iloc[: cut + 1])
                for col in cols:
                    full_v = full[col].iloc[cut]
                    trunc_v = trunc[col].iloc[cut]
                    full_nan = pd.isna(full_v)
                    trunc_nan = pd.isna(trunc_v)
                    if full_nan and trunc_nan:
                        continue
                    self.assertFalse(
                        full_nan or trunc_nan,
                        f"{col}[{cut}] seed={seed}: NaN tak konsisten (indikasi look-ahead)",
                    )
                    self.assertAlmostEqual(
                        float(full_v), float(trunc_v), delta=self.TOL,
                        msg=f"{col}[{cut}] seed={seed}: bocor look-ahead",
                    )


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

    def test_orphan_indicators_are_measured_on_swing_horizon(self):
        """W-0012: indikator orphan (williams_r/stoch_k/cci/efi/gk_vol) wajib
        punya boolean kandidat non-NaN, terlabel, dan terukur edge+n pada horizon
        swing yang sama — tanpa mengubah skor inti."""
        import indicators
        import validation
        from config import settings
        from factors import CANDIDATE_FACTORS, CANDIDATE_LABELS, candidate_frame

        orphans = ["williams_r_bull", "stoch_k_cross", "cci_bull", "efi_bull", "gk_vol_rendah"]
        for k in orphans:
            self.assertIn(k, CANDIDATE_FACTORS, k)
            self.assertIn(k, CANDIDATE_LABELS, k)

        d = indicators.add_indicators(make_df(400))
        cf = candidate_frame(d)
        for k in orphans:
            self.assertIn(k, cf.columns, k)
            self.assertFalse(bool(cf[k].isna().any()), k)
            self.assertEqual(str(cf[k].dtype), "bool", k)
        self.assertTrue(bool(((cf["confidence"] >= 0) & (cf["confidence"] <= 100)).all()))

        res = validation.analyze_accuracy(make_df(400))
        self.assertEqual(res["horizon"], settings.swing_horizon_days)
        measured = {c["factor"]: c["n"] for c in res["candidates"]}
        for k in orphans:
            self.assertIn(k, measured, k)
            self.assertGreaterEqual(measured[k], 20, k)

    def test_wilson_lower_bound_fixed_numbers(self):
        """W-0012: rumus Wilson lower-bound dikunci pakai angka tetap."""
        import validation
        self.assertAlmostEqual(validation.wilson_lower_bound(0.6, 30), 0.4232, places=4)
        self.assertAlmostEqual(validation.wilson_lower_bound(0.6, 20), 0.3866, places=4)
        self.assertEqual(validation.wilson_lower_bound(0.0, 30), 0.0)
        self.assertEqual(validation.wilson_lower_bound(0.5, 0), 0.0)

    def test_borderline_candidate_measured_but_not_promoted(self):
        """W-0012: kandidat dengan edge >= min_edge tapi keyakinan statistik
        belum menang (win_rate_lo <= base) tetap terukur di `candidates`,
        tapi TIDAK masuk `recommendations`; promosi tak pernah menambah."""
        import validation
        res = validation.analyze_accuracy(make_df(400), min_edge=0.0)
        base_wr = res["base_win_rate"]

        for c in res["candidates"]:
            self.assertIn("win_rate_lo", c, c["factor"])

        reco = {c["factor"] for c in res["recommendations"]}
        old_rule = {c["factor"] for c in res["candidates"] if c["edge"] >= 0.0}
        self.assertTrue(reco.issubset(old_rule))
        for c in res["recommendations"]:
            self.assertGreater(c["win_rate_lo"], base_wr, c["factor"])

        borderline = {
            c["factor"] for c in res["candidates"]
            if c["edge"] >= 0.0 and c["win_rate_lo"] <= base_wr
        }
        self.assertTrue(borderline)
        self.assertTrue(reco.isdisjoint(borderline))
        # Kandidat borderline harus tetap terukur (punya n dan win_rate).
        for c in res["candidates"]:
            if c["factor"] in borderline:
                self.assertGreaterEqual(c["n"], 20)
                self.assertIn("win_rate", c)

    def test_calibrate_gate_uses_win_rate_lo(self):
        """W-0012: jalur `calibrate` ikut memakai `win_rate_lo` (bukan cuma
        `analyze_accuracy`) sehingga `promoted` tak bolong/KeyError."""
        from unittest import mock
        import data
        import validation

        def fake_analyze(df, horizon=None, min_edge=0.03):
            return {
                "base_win_rate": 0.5,
                "samples": 100,
                "factors": [],
                "candidates": [
                    {"factor": "aroon_bull", "n": 100, "win_rate": 0.60, "edge": 0.10},
                    {"factor": "cci_bull", "n": 100, "win_rate": 0.52, "edge": 0.02},
                ],
            }

        with mock.patch.object(validation, "analyze_accuracy", side_effect=fake_analyze), \
                mock.patch.object(data, "get_ohlcv", return_value=None):
            out = validation.calibrate(["A", "B", "C", "D", "E"], min_edge=0.0)

        for r in out["factors"]:
            self.assertIn("win_rate_lo", r, r["factor"])
        promoted = {r["factor"] for r in out["promoted"]}
        self.assertIn("aroon_bull", promoted)
        self.assertNotIn("cci_bull", promoted)
        for r in out["promoted"]:
            self.assertGreater(r["win_rate_lo"], out["base_win_rate"])

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


class TestCandidateOutOfSample(unittest.TestCase):
    """Gate OOS kandidat (`candidate_out_of_sample`) — additive, tak menyentuh skor."""

    def test_oos_shape_and_verdict_enum(self):
        import validation
        res = validation.candidate_out_of_sample(make_df(400), horizon=10, folds=5)
        self.assertEqual(res["horizon"], 10)
        self.assertLessEqual(res["folds"], validation.MAX_FOLDS)
        prom = set(res["promoted"])
        for c in res["candidates"]:
            self.assertIn(c["factor"], __import__("signals").CANDIDATE_FACTORS)
            self.assertIn(c["verdict"], validation.RELIABILITY_LEVELS)
            self.assertEqual(c["promote"], c["factor"] in prom)

    def test_oos_min_edge_nonfinite_falls_back(self):
        """`min_edge` non-finite (mis. `-inf`) tak boleh mempromosikan semua."""
        import validation
        for bad in (float("-inf"), float("inf"), float("nan")):
            res = validation.candidate_out_of_sample(make_df(400), horizon=10, min_edge=bad)
            self.assertEqual(res["min_edge"], validation.MIN_EDGE)

    def test_oos_caps_folds_and_horizon(self):
        """K/horizon dibatasi agar loop K×horizon tak jadi DoS."""
        import validation
        res = validation.candidate_out_of_sample(make_df(400), horizon=10_000, folds=10_000)
        self.assertEqual(res["horizon"], validation.MAX_HORIZON)
        self.assertLessEqual(res["folds"], validation.MAX_FOLDS)

    def test_oos_does_not_touch_score_frame(self):
        import factors
        import indicators
        import validation
        df = make_df(400)
        d = indicators.add_indicators(df)
        before = factors.score_frame(d)
        validation.candidate_out_of_sample(df, horizon=10, d=d)
        self.assertTrue(before.equals(factors.score_frame(d)))

    def test_oos_promotes_consistent_rejects_inconsistent(self):
        """Gate: mayoritas fold edge>0 → `terbukti`; sebaliknya ditolak."""
        from unittest import mock

        import pandas as pd
        import validation
        from factors import CANDIDATE_FACTORS

        df = make_df(400)
        d = validation.add_indicators(df)
        close = d["Close"]
        fwd = close.shift(-10) / close - 1.0
        cf = pd.DataFrame(index=d.index)
        for k in CANDIDATE_FACTORS:
            cf[k] = False
        cf["ao>0"] = (fwd > 0).fillna(False)     # menang di tiap bar naik
        cf["cci_bull"] = (fwd < 0).fillna(False)  # selalu salah
        with mock.patch.object(validation, "candidate_frame", return_value=cf):
            res = validation.candidate_out_of_sample(df, horizon=10, folds=5, d=d)
        by = {c["factor"]: c for c in res["candidates"]}
        self.assertTrue(by["ao>0"]["promote"])
        self.assertEqual(by["ao>0"]["verdict"], "terbukti")
        self.assertIn("ao>0", res["promoted"])
        self.assertFalse(by["cci_bull"]["promote"])
        self.assertEqual(by["cci_bull"]["verdict"], "tidak_ada_edge")


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
        for key in ("ticker", "count", "avg_sentiment", "label", "items",
                    "degraded", "source"):
            self.assertIn(key, res)


class TestLlmPromptInfo(unittest.TestCase):
    """W-0023: prompt LLM dapat diketahui namanya & dialihkan via LLM_PROMPT_PATH.

    Env dibaca lazily di dalam fungsi (bukan konstanta import) supaya override
    lewat ``mock.patch.dict`` benar-benar berpengaruh; ``tearDown`` memulihkan
    lingkungan agar tidak bocor antar-tes.
    """

    def test_default_prompt_info_reports_basename_or_default(self):
        import os
        from unittest import mock

        import llm
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_PROMPT_PATH", None)
            info = llm.prompt_info()
        if llm.PROMPT_PATH.exists():
            self.assertEqual(info["source"], "file")
            self.assertEqual(info["file"], llm.PROMPT_PATH.name)
        else:
            self.assertEqual(info, {"file": None, "source": "default"})
        if info["file"]:
            self.assertNotIn(os.sep, info["file"])
            self.assertNotIn("/", info["file"])

    def test_env_override_switches_file_lazily(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        import llm
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "custom-prompt.md"
            p.write_text("---\nmeta\n---\nIsi prompt kustom", encoding="utf-8")
            with mock.patch.dict(os.environ, {"LLM_PROMPT_PATH": str(p)}, clear=False):
                info = llm.prompt_info()
                text = llm.load_prompt()
        self.assertEqual(info, {"file": "custom-prompt.md", "source": "file"})
        self.assertEqual(text, "Isi prompt kustom")

    def test_missing_env_file_reports_default_not_file(self):
        import os
        from unittest import mock

        import llm
        with mock.patch.dict(os.environ, {"LLM_PROMPT_PATH": "tidak-ada-xyz.md"}, clear=False):
            info = llm.prompt_info()
        self.assertEqual(info, {"file": None, "source": "default"})

    def test_rejects_dotfile_and_foreign_extension(self):
        import os
        from unittest import mock

        import llm
        for bad in (".env", "llm.json", "secrets.yaml"):
            with mock.patch.dict(os.environ, {"LLM_PROMPT_PATH": bad}, clear=False):
                info = llm.prompt_info()
            self.assertEqual(info, {"file": None, "source": "default"}, bad)

    def test_status_endpoint_reflects_env_override_basename(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        import webapp
        client = webapp.app.test_client()
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "custom.md"
            p.write_text("isi prompt", encoding="utf-8")
            with mock.patch.dict(os.environ, {"LLM_PROMPT_PATH": str(p)}, clear=False):
                resp = client.get("/api/llm/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("prompt", data)  # field lama tetap ada (kompatibel)
        self.assertEqual(data["prompt_file"], "custom.md")
        self.assertEqual(data["prompt_source"], "file")
        self.assertTrue(data["prompt"])


class TestPublicBaseCanonical(unittest.TestCase):
    """Base kanonik SEO (robots/sitemap/canonical) tak boleh tervalidasi lemah.

    Regresi anti Host-spoof/cache poisoning: env tak dikonfigurasi/invalid →
    jalur relatif (fail-safe) + ``no-store``; env valid → absolut + cache.
    """

    def setUp(self):
        import webapp
        self.client = webapp.app.test_client()

    def test_missing_env_does_not_echo_host(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LAUM_PUBLIC_BASE_URL", None)
            robots = self.client.get("/robots.txt", headers={"Host": "evil.example"})
            sitemap = self.client.get("/sitemap.xml", headers={"Host": "evil.example"})
            home = self.client.get("/", headers={"Host": "evil.example"})

        rb = robots.get_data(as_text=True)
        sm = sitemap.get_data(as_text=True)
        self.assertEqual(robots.status_code, 200)
        self.assertNotIn("evil.example", rb)
        self.assertNotIn("Sitemap:", rb)
        self.assertEqual(robots.headers.get("Cache-Control"), "no-store")
        self.assertEqual(robots.headers.get("Vary"), "Host")
        self.assertNotIn("evil.example", sm)
        self.assertIn("<loc>/</loc>", sm)
        self.assertEqual(sitemap.headers.get("Cache-Control"), "no-store")
        self.assertEqual(sitemap.headers.get("Vary"), "Host")
        self.assertEqual(home.headers.get("Cache-Control"), "no-store")
        self.assertNotIn("evil.example", home.get_data(as_text=True))
        hb = home.get_data(as_text=True)
        self.assertIn("<h1", hb)
        self.assertIn("application/ld+json", hb)
        self.assertIn('rel="canonical" href="/"', hb)
        self.assertNotIn('"url":', hb)  # base kosong → url di-omit (fail-safe)

    def test_invalid_env_is_ignored(self):
        import os
        from unittest import mock

        for bad in (
            "not-a-url",
            "ftp://evil.example",
            "https://evil.example/path",
            "https://evil.example/?q=1",
            "https://evil.example#frag",
            "https://evil.example</loc>",
            "https://evil.example\n<loc>x</loc>",
        ):
            with mock.patch.dict(os.environ, {"LAUM_PUBLIC_BASE_URL": bad}, clear=False):
                robots = self.client.get("/robots.txt", headers={"Host": "evil.example"})
                sitemap = self.client.get("/sitemap.xml", headers={"Host": "evil.example"})
            rb = robots.get_data(as_text=True)
            sm = sitemap.get_data(as_text=True)
            self.assertNotIn("evil.example", rb, bad)
            self.assertNotIn("evil.example", sm, bad)
            self.assertIn("<loc>/</loc>", sm, bad)
            self.assertEqual(robots.headers.get("Cache-Control"), "no-store", bad)

    def test_valid_env_used_absolute(self):
        import os
        from unittest import mock

        with mock.patch.dict(
            os.environ, {"LAUM_PUBLIC_BASE_URL": "https://laumology.example/"}, clear=False
        ):
            robots = self.client.get("/robots.txt", headers={"Host": "evil.example"})
            sitemap = self.client.get("/sitemap.xml", headers={"Host": "evil.example"})
            home = self.client.get("/", headers={"Host": "evil.example"})

        rb = robots.get_data(as_text=True)
        sm = sitemap.get_data(as_text=True)
        self.assertNotIn("evil.example", rb)
        self.assertIn("Sitemap: https://laumology.example/sitemap.xml", rb)
        self.assertEqual(robots.headers.get("Cache-Control"), "public, max-age=3600")
        self.assertIn("<loc>https://laumology.example/</loc>", sm)
        hb = home.get_data(as_text=True)
        self.assertIn("https://laumology.example/", hb)
        self.assertIn("<h1", hb)
        self.assertIn("application/ld+json", hb)
        self.assertIn('"url": "https://laumology.example"', hb)

    @staticmethod
    def _ld_json_block(html: str) -> dict:
        import json

        marker = '<script type="application/ld+json">'
        start = html.index(marker) + len(marker)
        end = html.index("</script>", start)
        return json.loads(html[start:end])

    def test_ld_json_valid_graph_without_base(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LAUM_PUBLIC_BASE_URL", None)
            hb = self.client.get("/", headers={"Host": "evil.example"}).get_data(as_text=True)

        data = self._ld_json_block(hb)
        self.assertEqual(data["@context"], "https://schema.org")
        types = [node["@type"] for node in data["@graph"]]
        self.assertIn("WebApplication", types)
        self.assertIn("WebSite", types)
        self.assertIn("Organization", types)
        # Base kosong → semua key url di-omit (fail-safe); SearchAction butuh absolut.
        for node in data["@graph"]:
            self.assertNotIn("url", node)
            self.assertNotIn("potentialAction", node)
        self.assertNotIn("evil.example", hb)

    def test_ld_json_searchaction_uses_validated_base(self):
        import os
        from unittest import mock

        with mock.patch.dict(
            os.environ, {"LAUM_PUBLIC_BASE_URL": "https://laumology.example/"}, clear=False
        ):
            hb = self.client.get("/", headers={"Host": "evil.example"}).get_data(as_text=True)

        data = self._ld_json_block(hb)
        by_type = {node["@type"]: node for node in data["@graph"]}
        self.assertEqual(by_type["WebApplication"]["url"], "https://laumology.example")
        self.assertEqual(by_type["Organization"]["url"], "https://laumology.example")
        self.assertEqual(
            by_type["Organization"]["logo"],
            "https://laumology.example/static/icon-512.png",
        )
        action = by_type["WebSite"]["potentialAction"]
        self.assertEqual(action["@type"], "SearchAction")
        self.assertEqual(
            action["target"]["urlTemplate"],
            "https://laumology.example/?ticker={search_term_string}",
        )
        self.assertNotIn("evil.example", hb)


class TestGscVerificationMeta(unittest.TestCase):
    """Meta verifikasi Google Search Console.

    Tanpa env, tag memakai token publik default. Env valid menimpa.
    Nilai kotor (``"``, ``<``) tidak pernah masuk ke atribut ``content``.
    """

    def setUp(self):
        import webapp
        self.client = webapp.app.test_client()

    def test_env_unset_uses_public_token(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LAUM_GOOGLE_SITE_VERIFICATION", None)
            hb = self.client.get("/").get_data(as_text=True)
        self.assertIn(
            '<meta name="google-site-verification" content="RnwQXP6N7GmFJnEJwvC_cPmgesMpyroVameSBPihrKE">',
            hb,
        )
        self.assertLess(
            hb.find("google-site-verification"),
            hb.find("<title>"),
        )

    def test_html_file_method(self):
        resp = self.client.get("/google42f09fe8816f0fe6.html")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.get_data(as_text=True).strip(),
            "google-site-verification: google42f09fe8816f0fe6.html",
        )

    def test_env_valid_tag_rendered(self):
        import os
        from unittest import mock

        with mock.patch.dict(
            os.environ, {"LAUM_GOOGLE_SITE_VERIFICATION": "AbC123_-xyz"}, clear=False
        ):
            hb = self.client.get("/").get_data(as_text=True)
        self.assertIn(
            '<meta name="google-site-verification" content="AbC123_-xyz">', hb
        )

    def test_env_invalid_is_ignored(self):
        import os
        from unittest import mock

        for bad in ('a"b', "a>b", "<script>", "a b", 'a" onmouseover="x'):
            with mock.patch.dict(
                os.environ, {"LAUM_GOOGLE_SITE_VERIFICATION": bad}, clear=False
            ):
                hb = self.client.get("/").get_data(as_text=True)
            self.assertNotIn("google-site-verification", hb, bad)


class TestAboutPageSeo(unittest.TestCase):
    """Halaman konten statis ``/tentang`` yang terindeks (W-0026).

    Mengunci kriteria penerimaan: 200 ``text/html``, ada H1 + teks deskriptif,
    canonical (absolut saat env valid, relatif bila kosong), terdaftar di
    sitemap beserta ``lastmod``, dan ``robots.txt`` tetap Allow. Anti
    Host-spoof: Host asing tak pernah dipantulkan.
    """

    def setUp(self):
        import webapp
        self.client = webapp.app.test_client()

    def test_about_page_absolute_when_env_set(self):
        import os
        from unittest import mock

        with mock.patch.dict(
            os.environ, {"LAUM_PUBLIC_BASE_URL": "https://laumology.example/"}, clear=False
        ):
            resp = self.client.get("/tentang", headers={"Host": "evil.example"})

        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content_type.startswith("text/html"))
        self.assertIn("<h1", html)
        self.assertIn("Tentang LAUMOLOGY", html)
        self.assertIn(
            '<link rel="canonical" href="https://laumology.example/tentang">', html
        )
        self.assertIn(
            '<meta property="og:url" content="https://laumology.example/tentang">', html
        )
        self.assertNotIn("evil.example", html)
        # CSP wajib nempel di dokumen HTML dan tetap melarang inline script.
        self.assertIn("script-src 'self'", resp.headers.get("Content-Security-Policy", ""))
        self.assertNotIn("onclick=", html)

    def test_about_page_relative_when_env_missing(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LAUM_PUBLIC_BASE_URL", None)
            resp = self.client.get("/tentang", headers={"Host": "evil.example"})

        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<link rel="canonical" href="/tentang">', html)
        self.assertNotIn("evil.example", html)

    def test_footer_links_to_about_so_root_not_broken(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn('href="/tentang"', home.get_data(as_text=True))

    def test_home_faq_is_in_raw_html(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Apa itu LAUMOLOGY?", html)
        self.assertIn('"@type": "FAQPage"', html)
        self.assertIn("Bukan nasihat investasi.", html)
        self.assertIn("<h1>LAUMOLOGY</h1>", html)
        self.assertIn("<title>LAUMOLOGY</title>", html)

    def test_sitemap_lists_about_with_lastmod(self):
        import os
        from unittest import mock

        with mock.patch.dict(
            os.environ, {"LAUM_PUBLIC_BASE_URL": "https://laumology.example/"}, clear=False
        ):
            sm = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("<loc>https://laumology.example/tentang</loc>", sm)
        self.assertIn("<lastmod>", sm)

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LAUM_PUBLIC_BASE_URL", None)
            sm = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("<loc>/tentang</loc>", sm)
        self.assertIn("<lastmod>", sm)

    def test_robots_still_allows_crawlers(self):
        rb = self.client.get("/robots.txt").get_data(as_text=True)
        self.assertIn("Allow: /", rb)


class TestPanduanPageSeo(unittest.TestCase):
    """Halaman konten statis ``/panduan`` yang terindeks (W-0026 lanjutan).

    Mengunci kriteria penerimaan: 200 ``text/html``, H1 + teks panduan ada di
    HTML mentah (tanpa JS), canonical (absolut saat env valid, relatif bila
    kosong), terdaftar di sitemap, dan tautan internal dari ``/`` dan
    ``/tentang``. Anti Host-spoof: Host asing tak pernah dipantulkan.
    """

    def setUp(self):
        import webapp
        self.client = webapp.app.test_client()

    def test_panduan_page_absolute_when_env_set(self):
        import os
        from unittest import mock

        with mock.patch.dict(
            os.environ, {"LAUM_PUBLIC_BASE_URL": "https://laumology.example/"}, clear=False
        ):
            resp = self.client.get("/panduan", headers={"Host": "evil.example"})

        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content_type.startswith("text/html"))
        self.assertIn("<h1", html)
        self.assertIn("Panduan Analisis Saham IDX", html)
        self.assertIn(
            '<link rel="canonical" href="https://laumology.example/panduan">', html
        )
        self.assertIn(
            '<meta property="og:url" content="https://laumology.example/panduan">', html
        )
        self.assertNotIn("evil.example", html)
        # CSP wajib nempel di dokumen HTML dan tetap melarang inline script.
        self.assertIn("script-src 'self'", resp.headers.get("Content-Security-Policy", ""))
        self.assertNotIn("onclick=", html)

    def test_panduan_content_present_without_js(self):
        resp = self.client.get("/panduan")
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        # Teks panduan wajib ada di HTML mentah, bukan dirender lewat JS.
        self.assertIn("position sizing", html)
        self.assertIn("Uji dengan backtest", html)
        self.assertIn('"@type": "BreadcrumbList"', html)
        self.assertIn('"@type": "Article"', html)

    def test_panduan_page_relative_when_env_missing(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LAUM_PUBLIC_BASE_URL", None)
            resp = self.client.get("/panduan", headers={"Host": "evil.example"})

        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<link rel="canonical" href="/panduan">', html)
        self.assertNotIn("evil.example", html)

    def test_internal_links_to_panduan_from_root_and_about(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn('href="/panduan"', home.get_data(as_text=True))
        about = self.client.get("/tentang")
        self.assertEqual(about.status_code, 200)
        self.assertIn('href="/panduan"', about.get_data(as_text=True))

    def test_sitemap_lists_panduan_and_is_valid_xml(self):
        import os
        import xml.etree.ElementTree as ET
        from unittest import mock

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        with mock.patch.dict(
            os.environ, {"LAUM_PUBLIC_BASE_URL": "https://laumology.example/"}, clear=False
        ):
            sm = self.client.get("/sitemap.xml").get_data(as_text=True)
        root = ET.fromstring(sm)
        locs = [e.text for e in root.findall("sm:url/sm:loc", ns)]
        self.assertIn("https://laumology.example/panduan", locs)
        self.assertIn("https://laumology.example/tentang", locs)
        self.assertIn("https://laumology.example/indikator-saham", locs)
        self.assertIn("https://laumology.example/", locs)
        self.assertEqual(len(locs), 4)

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LAUM_PUBLIC_BASE_URL", None)
            sm = self.client.get("/sitemap.xml").get_data(as_text=True)
        root = ET.fromstring(sm)
        locs = [e.text for e in root.findall("sm:url/sm:loc", ns)]
        self.assertIn("/panduan", locs)
        self.assertIn("/tentang", locs)
        self.assertIn("/indikator-saham", locs)


class TestIndikatorSahamPageSeo(unittest.TestCase):
    """Halaman konten statis ``/indikator-saham`` yang terindeks (W-0026 lanjutan).

    Mengunci kriteria penerimaan: 200 ``text/html``, H1 + teks glosarium ada di
    HTML mentah (tanpa JS), canonical (absolut saat env valid, relatif bila
    kosong), ``FAQPage`` + ``BreadcrumbList`` valid, terdaftar di sitemap, dan
    tautan internal dari ``/``. Anti Host-spoof: Host asing tak pernah
    dipantulkan.
    """

    def setUp(self):
        import webapp
        self.client = webapp.app.test_client()

    def test_indikator_page_absolute_when_env_set(self):
        import os
        from unittest import mock

        with mock.patch.dict(
            os.environ, {"LAUM_PUBLIC_BASE_URL": "https://laumology.example/"}, clear=False
        ):
            resp = self.client.get("/indikator-saham", headers={"Host": "evil.example"})

        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content_type.startswith("text/html"))
        self.assertIn("<h1", html)
        self.assertIn("Glosarium Indikator Saham IDX", html)
        self.assertIn(
            '<link rel="canonical" href="https://laumology.example/indikator-saham">', html
        )
        self.assertIn(
            '<meta property="og:url" content="https://laumology.example/indikator-saham">', html
        )
        self.assertNotIn("evil.example", html)
        self.assertIn("script-src 'self'", resp.headers.get("Content-Security-Policy", ""))
        self.assertNotIn("onclick=", html)

    def test_indikator_content_present_without_js(self):
        resp = self.client.get("/indikator-saham")
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("indikator saham", html)
        self.assertIn("RSI (Relative Strength Index)", html)
        self.assertIn("MACD", html)
        self.assertIn('"@type": "Article"', html)
        self.assertIn('"@type": "FAQPage"', html)
        self.assertIn('"@type": "BreadcrumbList"', html)
        self.assertIn('"@type": "Organization"', html)
        self.assertIn(
            '<meta property="article:published_time" content="2026-10-16">', html
        )
        self.assertIn(
            '<meta property="article:modified_time" content="2026-10-16">', html
        )

    def test_indikator_page_relative_when_env_missing(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LAUM_PUBLIC_BASE_URL", None)
            resp = self.client.get("/indikator-saham", headers={"Host": "evil.example"})

        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<link rel="canonical" href="/indikator-saham">', html)
        self.assertNotIn("evil.example", html)

    def test_internal_links_to_indikator_from_root(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        html = home.get_data(as_text=True)
        self.assertIn('href="/indikator-saham"', html)
        self.assertIn("indikator saham", html)


class TestBrandShareAssets(unittest.TestCase):
    """Aset brand W-0025: kartu berbagi + ikon harus ada dan valid.

    Scraper FB/X/WhatsApp/LinkedIn tak merender SVG → ``og:image`` wajib PNG
    dan (di produksi) absolut. Uji ini mengunci keberadaan aset agar gate tak
    lolos bila PNG tak ter-commit.
    """

    STATIC = Path(__file__).resolve().parent.parent / "static"
    EXPECTED = {
        "og-cover.png": (1200, 630),
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
        "apple-touch-icon.png": (180, 180),
    }
    MAX_BYTES = 300 * 1024

    def test_assets_exist_png_and_sized(self):
        import struct

        for name, want in self.EXPECTED.items():
            path = self.STATIC / name
            self.assertTrue(path.is_file(), f"{name} tidak ada (commit aset PNG)")
            data = path.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", f"{name} bukan PNG valid")
            self.assertLess(len(data), self.MAX_BYTES, f"{name} melebihi 300 KB")
            self.assertEqual(struct.unpack(">II", data[16:24]), want, name)

    def test_head_has_absolute_share_images_and_icons(self):
        import os
        from unittest import mock

        import webapp

        client = webapp.app.test_client()
        with mock.patch.dict(
            os.environ, {"LAUM_PUBLIC_BASE_URL": "https://laumology.example/"}, clear=False
        ):
            hb = client.get("/", headers={"Host": "evil.example"}).get_data(as_text=True)

        self.assertIn('<meta name="robots" content="index, follow, max-image-preview:large">', hb)
        self.assertIn(
            '<meta property="og:image" content="https://laumology.example/static/og-cover.png">', hb
        )
        self.assertIn('<meta property="og:image:type" content="image/png">', hb)
        self.assertIn('<meta property="og:image:width" content="1200">', hb)
        self.assertIn('<meta property="og:image:height" content="630">', hb)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', hb)
        self.assertIn(
            '<meta name="twitter:image" content="https://laumology.example/static/og-cover.png">', hb
        )
        self.assertIn('rel="apple-touch-icon"', hb)
        self.assertIn('rel="icon"', hb)
        self.assertNotIn("evil.example", hb)


class TestOgImageMetaTags(unittest.TestCase):
    """Meta ``og:image:*`` halaman konten wajib lengkap (W-0026 lanjutan).

    Mengunci agar kartu berbagi WA/FB/X/LinkedIn seragam dengan ``index.html``:
    tiga halaman konten merender ``og:image:type/width/height/alt``, dan
    ``panduan`` (schema Article) merender ``article:published_time`` +
    ``article:modified_time``.
    """

    PAGES = {
        "/tentang": "LAUMOLOGY · Tentang",
        "/panduan": "LAUMOLOGY · Panduan Analisis Saham IDX",
        "/indikator-saham": "LAUMOLOGY · Glosarium Indikator Saham IDX",
    }

    def setUp(self):
        import webapp
        self.client = webapp.app.test_client()

    def test_all_content_pages_render_full_og_image_meta(self):
        for path, alt in self.PAGES.items():
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)
            html = resp.get_data(as_text=True)
            self.assertIn('<meta property="og:image:type" content="image/png">', html, path)
            self.assertIn('<meta property="og:image:width" content="1200">', html, path)
            self.assertIn('<meta property="og:image:height" content="630">', html, path)
            self.assertIn(
                f'<meta property="og:image:alt" content="{alt}">', html, path
            )

    def test_panduan_renders_article_datetime_meta(self):
        html = self.client.get("/panduan").get_data(as_text=True)
        self.assertIn(
            '<meta property="article:published_time" content="2026-10-16">', html
        )
        self.assertIn(
            '<meta property="article:modified_time" content="2026-10-16">', html
        )


class TestNewsRssFallback(unittest.TestCase):
    """Fallback sumber berita (Google News RSS) + pelaporan kegagalan jujur."""

    RSS = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<rss version="2.0"><channel>'
        b'<item><title>BBCA naik laba</title>'
        b'<link>https://example.test/1</link>'
        b'<pubDate>Wed, 07 Oct 2026 04:24:00 GMT</pubDate>'
        b'<source>TestMedia</source></item>'
        b'</channel></rss>'
    )

    def tearDown(self):
        import news
        news._cache.clear()

    def test_parse_rss_matches_item_schema(self):
        import news
        items = news._parse_rss(self.RSS)
        self.assertEqual(len(items), 1)
        it = items[0]
        for key in ("title", "publisher", "url", "time", "sentiment", "pos", "neg"):
            self.assertIn(key, it)
        self.assertEqual(it["title"], "BBCA naik laba")
        self.assertEqual(it["publisher"], "TestMedia")
        self.assertEqual(it["url"], "https://example.test/1")

    # Shape nyata Google News RSS: `<title>` = "Judul - Penerbit" sedangkan
    # `<description>` = "Judul Penerbit" (HTML, tanpa tanda hubung).
    RSS_DUP = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<rss version="2.0"><channel>'
        b'<item><title>IHSG Diprediksi Menguat - KabarBursa.com</title>'
        b'<link>https://example.test/2</link>'
        b'<pubDate>Wed, 07 Oct 2026 04:24:00 GMT</pubDate>'
        b'<source url="https://example.test/kb">KabarBursa.com</source>'
        b'<description><![CDATA[<a href="https://example.test/2">'
        b'IHSG Diprediksi Menguat</a>&nbsp;<font color="#6f6f6f">'
        b'KabarBursa.com</font>]]></description>'
        b'</item>'
        b'</channel></rss>'
    )

    RSS_CLUSTER = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<rss version="2.0"><channel>'
        b'<item><title>Topik Pasar - KabarBursa.com</title>'
        b'<link>https://example.test/3</link>'
        b'<source>KabarBursa.com</source>'
        b'<description><![CDATA[<ol><li><a href="https://example.test/3a">'
        b'Headline A</a>&nbsp;<font>Pub A</font></li>'
        b'<li><a href="https://example.test/3b">Headline B</a>&nbsp;'
        b'<font>Pub B</font></li></ol>]]></description>'
        b'</item>'
        b'</channel></rss>'
    )

    RSS_GENUINE = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<rss version="2.0"><channel>'
        b'<item><title>Prospek Bank - KabarBursa.com</title>'
        b'<link>https://example.test/4</link>'
        b'<source>KabarBursa.com</source>'
        b'<description><![CDATA[Analis menilai prospek emiten perbankan '
        b'masih solid sepanjang kuartal ini.]]></description>'
        b'</item>'
        b'</channel></rss>'
    )

    def test_parse_rss_drops_title_publisher_duplicate_summary(self):
        import news
        items = news._parse_rss(self.RSS_DUP)
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["summary"])

    # `<source url>` valid tanpa `<enclosure>` → favicon host dipakai sebagai
    # gambar cadangan (client-side), dan `publisher_url` tersimpan.
    RSS_SOURCE_URL = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<rss version="2.0"><channel>'
        b'<item><title>Emiten bagikan dividen - KabarBursa.com</title>'
        b'<link>https://example.test/5</link>'
        b'<source url="https://example.test/kb">KabarBursa.com</source>'
        b'</item>'
        b'</channel></rss>'
    )

    # `<source url>` skema tak valid (javascript:) → JANGAN simpan; gambar None.
    RSS_SOURCE_BAD = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<rss version="2.0"><channel>'
        b'<item><title>Judul jahat - Jahat</title>'
        b'<link>https://example.test/6</link>'
        b'<source url="javascript:alert(1)">Jahat</source>'
        b'</item>'
        b'</channel></rss>'
    )

    # `<enclosure>` tetap menang atas favicon cadangan (jangan nimpa gambar).
    RSS_ENCLOSURE = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<rss version="2.0"><channel>'
        b'<item><title>Berita bergambar - KabarBursa.com</title>'
        b'<link>https://example.test/7</link>'
        b'<source url="https://example.test/kb">KabarBursa.com</source>'
        b'<enclosure url="https://cdn.test/photo.jpg" type="image/jpeg"/>'
        b'</item>'
        b'</channel></rss>'
    )

    def test_parse_rss_source_url_fills_publisher_and_favicon(self):
        import news
        items = news._parse_rss(self.RSS_SOURCE_URL)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["publisher_url"], "https://example.test/kb")
        self.assertEqual(it["image"], "https://example.test/favicon.ico")

    def test_parse_rss_invalid_source_url_is_none(self):
        import news
        items = news._parse_rss(self.RSS_SOURCE_BAD)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertIsNone(it["publisher_url"])
        self.assertIsNone(it["image"])

    def test_parse_rss_enclosure_wins_over_favicon(self):
        import news
        items = news._parse_rss(self.RSS_ENCLOSURE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["image"], "https://cdn.test/photo.jpg")

    def test_parse_rss_drops_cluster_summary(self):
        import news
        items = news._parse_rss(self.RSS_CLUSTER)
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["summary"])

    def test_parse_rss_keeps_genuine_summary(self):
        import news
        items = news._parse_rss(self.RSS_GENUINE)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["summary"],
            "Analis menilai prospek emiten perbankan masih solid sepanjang kuartal ini.",
        )

    def test_clean_summary_regex_meta_safe(self):
        """Penerbit/judul ber-karakter regex tak boleh jadi pola liar/ReDoS."""
        import news
        out = news._clean_summary(
            "Headline A.B+C (Group) A.B+C (Group)",
            title="Headline A.B+C (Group) - A.B+C (Group)",
            publisher="A.B+C (Group)",
        )
        self.assertIsNone(out)

    def test_clean_summary_short_genuine_preserved(self):
        import news
        s = "Emiten mencatat laba bersih naik."
        self.assertEqual(news._clean_summary(s), s)

    def test_clean_summary_rss_short_residual_dropped(self):
        import news
        self.assertIsNone(
            news._clean_summary("Laba naik", title="X - Pub", publisher="Pub")
        )

    def test_parse_rss_rejects_dtd(self):
        import news
        with self.assertRaises(ValueError):
            news._parse_rss(b'<!DOCTYPE rss [<!ENTITY x "y">]><rss/>')

    def test_parse_rss_rejects_dtd_utf16(self):
        """DTD tetap tertangkap walau XML di-encode UTF-16 (byte nol menyelip)."""
        import news
        payload = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<!DOCTYPE rss [<!ENTITY e "boom">]><rss/>'
        ).encode("utf-16")
        with self.assertRaises(ValueError):
            news._parse_rss(payload)

    def test_parse_rss_rejects_dtd_beyond_head_window(self):
        """DTD yang digeser melewati 4 KB pertama tetap ditolak (scan seluruh body)."""
        import news
        pad = b"<!--" + b"x" * 6000 + b"-->"
        payload = (b'<?xml version="1.0" encoding="UTF-8"?>' + pad
                   + b'<!DOCTYPE rss [<!ENTITY e "boom">]><rss/>')
        with self.assertRaises(ValueError):
            news._parse_rss(payload)

    # Shape nyata Bing News RSS: namespace `News:` ber-URI dinamis (memuat
    # query), gambar `News:Image` (host www.bing.com, http) + `News:Source`,
    # tautan `apiclick.aspx?...&url=<encoded>` ke penerbit asli, dan
    # `<description>` = ringkasan asli (bukan "judul penerbit").
    BING_RSS = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<rss version="2.0" xmlns:News="https://www.bing.com/news/search?q=BBCA">'
        b'<channel><item>'
        b'<title>BBCA dilirik investor asing</title>'
        b'<link>https://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url='
        b'https%3A%2F%2Fexample.test%2Fbbca&amp;c=1</link>'
        b'<description>Investor asing mulai melirik saham BBCA setelah '
        b'keputusan FTSE menambah bobot pasar Indonesia.</description>'
        b'<pubDate>Sat, 10 Oct 2026 20:02:00 GMT</pubDate>'
        b'<News:Source>TestMedia</News:Source>'
        b'<News:Image>http://www.bing.com/th?id=abc&amp;pid=News</News:Image>'
        b'</item></channel></rss>'
    )

    def test_parse_bing_rss_matches_item_schema(self):
        import news
        items = news._parse_bing_rss(self.BING_RSS)
        self.assertEqual(len(items), 1)
        it = items[0]
        for key in ("title", "publisher", "url", "time", "sentiment", "pos", "neg",
                    "summary", "image"):
            self.assertIn(key, it)
        self.assertEqual(it["title"], "BBCA dilirik investor asing")
        self.assertEqual(it["publisher"], "TestMedia")
        self.assertEqual(it["time"], "Sat, 10 Oct 2026 20:02:00 GMT")
        # apiclick `url=` di-decode ke penerbit asli (bukan URL bing).
        self.assertEqual(it["url"], "https://example.test/bbca")
        # gambar http dipaksa https + host `.bing.com` dipertahankan.
        self.assertEqual(it["image"], "https://www.bing.com/th?id=abc&pid=News")
        self.assertIn("Investor asing mulai melirik", it["summary"])
        self.assertNotEqual(it["summary"], it["title"])

    def test_parse_bing_rss_upgrades_www_host_image(self):
        import news
        items = news._parse_bing_rss(self.BING_RSS)
        self.assertTrue(items[0]["image"].startswith("https://www.bing.com/th"))

    def test_parse_bing_rss_rejects_foreign_image_host(self):
        import news
        payload = self.BING_RSS.replace(
            b"http://www.bing.com/th?id=abc&amp;pid=News",
            b"http://evil.test/track.gif",
        )
        items = news._parse_bing_rss(payload)
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["image"])

    def test_parse_bing_rss_rejects_nonstandard_image_port(self):
        import news
        payload = self.BING_RSS.replace(
            b"http://www.bing.com/th?id=abc&amp;pid=News",
            b"http://www.bing.com:8443/th?id=abc&amp;pid=News",
        )
        items = news._parse_bing_rss(payload)
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["image"])

    def test_bing_image_url_drops_default_https_port(self):
        import news
        self.assertEqual(
            news._bing_image_url("https://www.bing.com:443/th?id=abc"),
            "https://www.bing.com/th?id=abc",
        )

    def test_parse_bing_rss_rejects_javascript_link_keeps_item(self):
        import news
        payload = self.BING_RSS.replace(
            b"https%3A%2F%2Fexample.test%2Fbbca",
            b"javascript%3Aalert(1)",
        )
        items = news._parse_bing_rss(payload)
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["url"])

    def test_parse_bing_rss_missing_url_param_is_none(self):
        import news
        payload = self.BING_RSS.replace(
            b"url=https%3A%2F%2Fexample.test%2Fbbca&amp;c=1",
            b"c=1",
        )
        items = news._parse_bing_rss(payload)
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["url"])

    def test_parse_bing_rss_rejects_dtd(self):
        import news
        with self.assertRaises(ValueError):
            news._parse_bing_rss(b'<!DOCTYPE rss [<!ENTITY x "y">]><rss/>')

    def test_bing_request_url_with_ua(self):
        from unittest.mock import MagicMock, patch

        import news

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["ua"] = req.headers.get("User-agent")
            captured["timeout"] = timeout
            cm = MagicMock()
            cm.read.return_value = self.BING_RSS
            cm.__enter__.return_value = cm
            cm.__exit__.return_value = False
            return cm

        with patch("news.urllib.request.urlopen", fake_urlopen):
            items = news._bing_items("BBCA.JK")
        self.assertGreaterEqual(len(items), 1)
        self.assertIn("bing.com/news/search", captured["url"])
        self.assertIn("format=RSS", captured["url"])
        self.assertIn("BBCA", captured["url"])
        self.assertTrue(captured["ua"])
        self.assertIsNotNone(captured["timeout"])

    def test_rss_request_google_url_with_ua(self):
        from unittest.mock import MagicMock, patch

        import news

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["ua"] = req.headers.get("User-agent")
            captured["timeout"] = timeout
            cm = MagicMock()
            cm.read.return_value = self.RSS
            cm.__enter__.return_value = cm
            cm.__exit__.return_value = False
            return cm

        with patch("news.urllib.request.urlopen", fake_urlopen):
            items = news._rss_items("BBCA.JK")
        self.assertGreaterEqual(len(items), 1)
        self.assertIn("news.google.com/rss/search", captured["url"])
        self.assertIn("BBCA", captured["url"])
        self.assertTrue(captured["ua"])
        self.assertIsNotNone(captured["timeout"])

    def test_fallback_used_when_yahoo_empty(self):
        from unittest.mock import patch

        import news

        with patch("news.yf.Ticker") as mock_ticker, \
             patch("news._bing_items", return_value=[]), \
             patch("news._rss_items", return_value=news._parse_rss(self.RSS)):
            mock_ticker.return_value.news = []
            res = news.get_news("BBCA")
        self.assertGreater(res["count"], 0)
        self.assertEqual(res["source"], "google_news_rss")
        self.assertFalse(res["degraded"])

    def test_degraded_when_sources_fail(self):
        from unittest.mock import patch

        import news

        with patch("news.yf.Ticker", side_effect=RuntimeError("boom")), \
             patch("news._bing_items", side_effect=RuntimeError("net")), \
             patch("news._rss_items", side_effect=RuntimeError("net")):
            res = news.get_news("BBCA")
        self.assertEqual(res["count"], 0)
        self.assertTrue(res["degraded"])
        self.assertIsNone(res["source"])
        for key in ("ticker", "count", "avg_sentiment", "label", "items"):
            self.assertIn(key, res)

    def test_empty_but_reachable_sources_not_degraded(self):
        """Dua sumber merespons tanpa exception, tapi nihil berita → bukan degraded.

        Sumber yang benar-benar sukses (walau kosong) berarti memang tidak ada
        berita; UI harus bilang "Tidak ada berita", bukan "sumber tidak tersedia".
        """
        from unittest.mock import patch

        import news

        with patch("news.yf.Ticker") as mock_ticker, \
             patch("news._bing_items", return_value=[]), \
             patch("news._rss_items", return_value=[]):
            mock_ticker.return_value.news = []
            res = news.get_news("BBCA")
        self.assertEqual(res["count"], 0)
        self.assertFalse(res["degraded"])
        self.assertIsNone(res["source"])

    def test_yahoo_empty_then_rss_fails_is_degraded(self):
        """Yahoo balas `[]` (tanpa exception) lalu RSS gagal → `degraded=True`.

        Feed Yahoo kerap mengembalikan daftar kosong tanpa melempar; itu BUKAN
        bukti sumber hidup. Bila RSS kemudian error, tak ada satu pun sumber
        yang benar-benar menyajikan berita → UI harus jujur bilang "sumber
        tidak tersedia", bukan menyesatkan "Tidak ada berita".
        """
        from unittest.mock import patch

        import news

        with patch("news.yf.Ticker") as mock_ticker, \
             patch("news._bing_items", side_effect=RuntimeError("net")), \
             patch("news._rss_items", side_effect=RuntimeError("net")):
            mock_ticker.return_value.news = []
            res = news.get_news("BBCA")
        self.assertEqual(res["count"], 0)
        self.assertTrue(res["degraded"])
        self.assertIsNone(res["source"])

    def test_one_failed_source_still_not_degraded(self):
        """Yahoo gagal (exception) tapi RSS sukses-kosong → jangan salah-lapor degraded.

        Dulu ``degraded = bool(errors) and not items`` menyalakan degraded hanya
        karena ada error, padahal sumber cadangan hidup. Dengan ``source_ok``
        eksplisit, keberadaan satu sumber yang merespons mencegah false-degraded.
        """
        from unittest.mock import patch

        import news

        with patch("news.yf.Ticker", side_effect=RuntimeError("boom")), \
             patch("news._bing_items", return_value=[]), \
             patch("news._rss_items", return_value=[]):
            res = news.get_news("BBCA")
        self.assertEqual(res["count"], 0)
        self.assertFalse(res["degraded"])

    def test_bing_preferred_over_google_when_both_populated(self):
        """Bing didahulukan saat Bing DAN Google sama-sama menyajikan berita.

        Bing membawa gambar + ringkasan asli, jadi urutan sumber di
        ``news._raw_items`` wajib memilih Bing lebih dulu dan tak boleh
        memanggil Google setelahnya; prioritas itu dikunci di sini.
        """
        from unittest.mock import patch

        import news

        with patch("news.yf.Ticker") as mock_ticker, \
             patch("news._bing_items",
                   return_value=news._parse_bing_rss(self.BING_RSS)) as mock_bing, \
             patch("news._rss_items",
                   return_value=news._parse_rss(self.RSS)) as mock_rss:
            mock_ticker.return_value.news = []
            res = news.get_news("BBCA")
        self.assertGreater(res["count"], 0)
        self.assertEqual(res["source"], "bing_news_rss")
        self.assertFalse(res["degraded"])
        mock_bing.assert_called_once()
        mock_rss.assert_not_called()

    def test_bing_empty_then_google_fails_not_degraded_errors_kept(self):
        """Bing balas kosong (sumber hidup) lalu Google gagal → bukan degraded.

        Satu sumber merespons tanpa exception berarti jaringan hidup, jadi UI
        jujur "Tidak ada berita"; error Google tetap dicatat di ``_raw_items``
        sebagai jejak diagnostik.
        """
        from unittest.mock import patch

        import news

        with patch("news.yf.Ticker") as mock_ticker, \
             patch("news._bing_items", return_value=[]), \
             patch("news._rss_items", side_effect=RuntimeError("net")):
            mock_ticker.return_value.news = []
            raw = news._raw_items("BBCA.JK", 10)
            res = news.get_news("BBCA")
        self.assertTrue(raw.source_ok)
        self.assertIsNone(raw.source)
        self.assertTrue(
            any(str(e).startswith("google_news_rss") for e in raw.errors),
            raw.errors,
        )
        self.assertEqual(res["count"], 0)
        self.assertFalse(res["degraded"])
        self.assertIsNone(res["source"])

    def test_plain_list_mock_degrades_on_empty(self):
        """Mock list polos (tanpa atribut ``source_ok``) → safe-default degraded."""
        from unittest.mock import patch

        import news

        with patch("news._raw_items", return_value=[]):
            res = news.get_news("BBCA")
        self.assertEqual(res["count"], 0)
        self.assertTrue(res["degraded"])

    def test_invalid_ticker_rejected_without_fetch(self):
        from unittest.mock import patch

        import news

        with patch("news.yf.Ticker") as mock_ticker, patch("news._bing_items") as mock_bing, \
             patch("news._rss_items") as mock_rss:
            for bad in ("A&x", "A#b", "A/B", "A B", "A" * 40):
                res = news.get_news(bad)
                self.assertEqual(res["count"], 0)
                self.assertTrue(res["degraded"])
                self.assertIn("error", res)
            mock_ticker.assert_not_called()
            mock_bing.assert_not_called()
            mock_rss.assert_not_called()
        self.assertEqual(news._cache, {})

    def test_negative_ttl_cached_when_degraded(self):
        from unittest.mock import patch

        import news

        with patch("news.yf.Ticker", side_effect=RuntimeError("boom")), \
             patch("news._bing_items", side_effect=RuntimeError("net")), \
             patch("news._rss_items", side_effect=RuntimeError("net")):
            news.get_news("BBCA")
        self.assertIn("t:BBCA.JK", news._cache)
        self.assertEqual(news._cache["t:BBCA.JK"][2], news._NEGATIVE_TTL)


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
                  "/api/calibrate", "/api/news/market", "/api/external", "/api/scan/start", "/api/paper"]:
            self.assertIn(p, paths)

    def test_security_headers_on_html(self):
        import webapp
        client = webapp.app.test_client()
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(resp.headers.get("Referrer-Policy"),
                         "strict-origin-when-cross-origin")
        csp = resp.headers.get("Content-Security-Policy", "")
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("script-src 'self';", csp + ";")
        # jangan longgarkan script dengan 'unsafe-inline'
        script_dir = csp.split("script-src", 1)[1].split(";", 1)[0]
        self.assertNotIn("unsafe-inline", script_dir)

    def test_no_inline_onclick_attributes(self):
        """CSP `script-src 'self'` memblokir atribut onclick; aksi UI wajib
        lewat delegasi `data-action` (W-0022)."""
        js_dir = Path(__file__).resolve().parent.parent / "static" / "js"
        offenders = [js.name for js in sorted(js_dir.glob("*.js"))
                     if 'onclick="' in js.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [], f"atribut onclick masih ada: {offenders}")

    def test_click_delegation_allowlist_no_dynamic_dispatch(self):
        """Delegasi klik tunggal di core.js: allowlist aksi tetap, tanpa
        dispatch dinamis window[...] (cegah permukaan injeksi baru)."""
        core = (Path(__file__).resolve().parent.parent / "static" / "js" / "core.js").read_text(encoding="utf-8")
        self.assertIn('document.addEventListener("click"', core)
        self.assertIn('closest("[data-action]")', core)
        self.assertIn("hasOwnProperty.call(CLICK_ACTIONS, action)", core)
        self.assertNotIn("window[action]", core)

    def test_security_headers_nosniff_global_no_csp_json(self):
        import webapp
        client = webapp.app.test_client()
        for path in ("/health", "/api/version"):
            resp = client.get(path)
            self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff", path)
            self.assertIsNone(resp.headers.get("Content-Security-Policy"), path)
            self.assertIsNone(resp.headers.get("X-Frame-Options"), path)

    def test_security_headers_sse_not_html(self):
        """Deteksi berbasis content_type: SSE tidak boleh dapat CSP."""
        from unittest.mock import patch

        import webapp
        with patch("screener.resolve_watchlist", return_value=[]):
            client = webapp.app.test_client()
            resp = client.get("/api/screen/stream?list=lq45")
        self.assertTrue(resp.content_type.startswith("text/event-stream"))
        self.assertIsNone(resp.headers.get("Content-Security-Policy"))
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")

    def test_hsts_only_when_forwarded_https(self):
        import webapp
        client = webapp.app.test_client()
        self.assertIsNone(client.get("/").headers.get("Strict-Transport-Security"))
        resp = client.get("/", headers={"X-Forwarded-Proto": "https"})
        self.assertIsNotNone(resp.headers.get("Strict-Transport-Security"))


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

    def test_default_horizon_from_settings(self):
        """Horizon backtest default harus mengikuti satu sumber settings.swing_horizon_days."""
        import backtest
        from config import settings
        df = make_df(320)
        old = settings.swing_horizon_days
        try:
            settings.swing_horizon_days = 7
            dflt = backtest.backtest(df, "TEST")
            explicit = backtest.backtest(df, "TEST", max_hold=7)
        finally:
            settings.swing_horizon_days = old
        self.assertEqual(dflt.total_return, explicit.total_return)
        self.assertEqual(dflt.n_trades, explicit.n_trades)

    def test_explicit_horizon_respected(self):
        """max_hold eksplisit tidak boleh ditimpa oleh settings."""
        import backtest
        from config import settings
        df = make_df(320)
        old = settings.swing_horizon_days
        try:
            settings.swing_horizon_days = 7
            explicit = backtest.backtest(df, "TEST", max_hold=20)
            settings.swing_horizon_days = 20
            dflt20 = backtest.backtest(df, "TEST")
        finally:
            settings.swing_horizon_days = old
        self.assertEqual(explicit.total_return, dflt20.total_return)
        self.assertEqual(explicit.n_trades, dflt20.n_trades)


class TestValidate(unittest.TestCase):
    def test_clean(self):
        import validate
        self.assertTrue(validate.check_df(make_df(250))["ok"])

    def test_bad_hl(self):
        import validate
        df = make_df(250)
        df.iloc[5, df.columns.get_loc("High")] = df["Low"].iloc[5] - 1.0
        self.assertFalse(validate.check_df(df)["ok"])

    def test_check_df_tz_aware_stale(self):
        """Index tz-aware tidak boleh jatuh ke except -> stale_days bohong 0."""
        import validate
        df = make_df(250)
        end = pd.Timestamp.now().normalize() - pd.Timedelta(days=30)
        df.index = pd.date_range(end=end, periods=len(df), freq="D").tz_localize("Asia/Jakarta")
        r = validate.check_df(df)
        self.assertGreaterEqual(r["stale_days"], 25)


class TestSwingHorizonFreshness(unittest.TestCase):
    """W-0012: horizon swing satu sumber + kesegaran data transparan (delta skor = 0)."""

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

    def test_api_analyze_has_horizon_and_freshness(self):
        import data
        import indicators
        import signals
        import webapp
        from config import settings

        df = make_df()
        import external
        old_ohlcv, old_quote = data.get_ohlcv, data.get_quote
        old_ext = external.for_stock
        data.get_ohlcv = lambda *a, **k: df
        data.get_quote = lambda *a, **k: None
        external.for_stock = lambda *a, **k: {
            "status": "netral", "label": "Netral", "intensity": 0,
            "summary": "Tidak ada tekanan luar yang teridentifikasi.",
            "drivers": [], "coupling": None,
        }
        old = self._freeze()
        try:
            r = webapp.app.test_client().get("/api/analyze?ticker=TEST")
            base = signals.analyze(df, "TEST", d=indicators.add_indicators(df))
        finally:
            data.get_ohlcv, data.get_quote = old_ohlcv, old_quote
            external.for_stock = old_ext
            self._restore(old)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["horizon"], settings.swing_horizon_days)
        self.assertEqual(body["horizon"], 10)
        self.assertIn("data_freshness", body)
        self.assertEqual(body["data_freshness"]["stale_days"], 0)
        self.assertTrue(body["data_freshness"]["fresh"])
        self.assertIn("last_bar", body["data_freshness"])
        # Field baru murni informatif: skor tidak boleh bergeser.
        self.assertEqual(body["score"], base.score)

    def test_stale_history_with_live_quote_is_not_fresh(self):
        """Riwayat basi + quote live: fresh jujur dari histori, skor tetap identik."""
        import data
        import indicators
        import signals
        import webapp

        df = make_df()
        df.index = df.index - pd.Timedelta(days=30)
        last_close = float(df["Close"].iloc[-1])
        quote = {
            "last": last_close * 1.01,
            "prev_close": last_close,
            "open": last_close,
            "day_high": last_close * 1.02,
            "day_low": last_close * 0.99,
            "volume": 2_000_000.0,
            "time": "now",
            "source": "test",
        }
        import external
        old_ohlcv, old_quote = data.get_ohlcv, data.get_quote
        old_ext = external.for_stock
        data.get_ohlcv = lambda *a, **k: df
        data.get_quote = lambda *a, **k: quote
        external.for_stock = lambda *a, **k: {
            "status": "netral", "label": "Netral", "intensity": 0,
            "summary": "Tidak ada tekanan luar yang teridentifikasi.",
            "drivers": [], "coupling": None,
        }
        old = self._freeze()
        try:
            r = webapp.app.test_client().get("/api/analyze?ticker=TEST")
            df_live, live = data.apply_live_quote(df, quote, "1d")
            base = signals.analyze(df_live, "TEST", d=indicators.add_indicators(df_live))
        finally:
            data.get_ohlcv, data.get_quote = old_ohlcv, old_quote
            external.for_stock = old_ext
            self._restore(old)
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(live)
        body = r.get_json()
        f = body["data_freshness"]
        self.assertGreater(f["stale_days"], 0)
        self.assertFalse(f["fresh"])
        self.assertTrue(f["live_bar"])
        self.assertIn("history_last_bar", f)
        self.assertEqual(body["score"], base.score)

    def test_default_horizon_single_source(self):
        import ml
        import validation
        from config import settings

        old = settings.swing_horizon_days
        try:
            settings.swing_horizon_days = 7
            df = make_df(320)
            self.assertEqual(validation.analyze_accuracy(df)["horizon"], 7)
            self.assertEqual(ml.predict(df, "TEST")["horizon"], 7)
        finally:
            settings.swing_horizon_days = old

    def test_api_backtest_uses_settings_horizon(self):
        import backtest
        import data
        import webapp
        from config import settings

        df = make_df(320)
        old_ohlcv = data.get_ohlcv
        data.get_ohlcv = lambda *a, **k: df
        old = settings.swing_horizon_days
        try:
            settings.swing_horizon_days = 7
            r = webapp.app.test_client().get("/api/backtest?ticker=TEST")
            expected = backtest.backtest(
                df, "TEST", min_score=65, max_hold=7, tp_rr=3.0, sl_mult=2.0,
                fee_buy=0.0015, fee_sell=0.0025, slip=0.001,
            )
        finally:
            data.get_ohlcv = old_ohlcv
            settings.swing_horizon_days = old
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["total_return"], expected.total_return)
        self.assertEqual(body["n_trades"], expected.n_trades)

    def test_api_backtest_explicit_horizon_respected(self):
        import backtest
        import data
        import webapp
        from config import settings

        df = make_df(320)
        old_ohlcv = data.get_ohlcv
        data.get_ohlcv = lambda *a, **k: df
        old = settings.swing_horizon_days
        try:
            settings.swing_horizon_days = 7
            r = webapp.app.test_client().get("/api/backtest?ticker=TEST&max_hold=20")
            expected = backtest.backtest(
                df, "TEST", min_score=65, max_hold=20, tp_rr=3.0, sl_mult=2.0,
                fee_buy=0.0015, fee_sell=0.0025, slip=0.001,
            )
        finally:
            data.get_ohlcv = old_ohlcv
            settings.swing_horizon_days = old
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["total_return"], expected.total_return)
        self.assertEqual(body["n_trades"], expected.n_trades)



class TestAccuracyByHorizon(unittest.TestCase):
    """W-0017: studi akurasi lintas horizon — forward-WR vs trade-WR, additive."""

    def test_runs_four_horizons_lookahead_free(self):
        import validation

        df = make_df(400)
        res = validation.accuracy_by_horizon(df, horizons=(1, 5, 10, 15))
        self.assertEqual(res["horizons"], [1, 5, 10, 15])
        self.assertEqual(len(res["rows"]), 4)
        base_bars = validation.analyze_accuracy(df, horizon=1)["bars"]

        for row in res["rows"]:
            h = row["horizon"]
            # Dua konstruk wajib terpisah & terlabel tegas.
            self.assertIn("forward", row)
            self.assertIn("trade", row)
            self.assertIn("win_rate", row["forward"])
            self.assertIn("win_rate", row["trade"])
            # Sampel forward = bars - horizon (look-ahead free).
            self.assertEqual(row["forward"]["samples"], base_bars - h)
            self.assertIn("best_factor", row["forward"])
            for k in ("profit_factor", "avg_bars", "n_trades", "sufficient"):
                self.assertIn(k, row["trade"], k)

    def test_rows_include_per_factor_edge(self):
        """W-0017: tiap row horizon memuat edge per-indikator (bukan cuma best)."""
        import validation

        df = make_df(400)
        res = validation.accuracy_by_horizon(df, horizons=(1, 5))
        upper = len(validation.FACTOR_KEYS) + len(validation.CANDIDATE_FACTORS)

        for row in res["rows"]:
            self.assertIn("factors", row)
            self.assertIn("candidates", row)
            # Jumlah bisa beda per horizon (min_n motong faktor) ⇒ batas atas.
            self.assertLessEqual(len(row["factors"]), len(validation.FACTOR_KEYS))
            self.assertLessEqual(len(row["candidates"]), len(validation.CANDIDATE_FACTORS))
            self.assertLessEqual(len(row["factors"]) + len(row["candidates"]), upper)
            for f in row["factors"]:
                self.assertFalse(f["candidate"])
                for k in ("factor", "n", "win_rate", "edge"):
                    self.assertIn(k, f, k)
            for c in row["candidates"]:
                self.assertTrue(c["candidate"])
            # Bandingkan langsung dengan analyze_accuracy horizon yang sama.
            acc = validation.analyze_accuracy(df, horizon=row["horizon"])
            self.assertEqual([f["factor"] for f in row["factors"]],
                             [f["factor"] for f in acc["factors"]])
            self.assertEqual([c["factor"] for c in row["candidates"]],
                             [c["factor"] for c in acc["candidates"]])

    def test_horizon_one_is_timeout_dominated(self):
        """horizon=1 ⇒ max_hold=1 ⇒ TP/SL praktis tak tersentuh (TIMEOUT)."""
        import validation

        res = validation.accuracy_by_horizon(make_df(400), horizons=(1,))
        row = res["rows"][0]
        self.assertEqual(row["horizon"], 1)
        self.assertLessEqual(row["trade"]["avg_bars"], 1.0)
        pf = row["trade"]["profit_factor"]
        # PF tak hingga tidak boleh lolos sebagai inf; harus None.
        self.assertTrue(pf is None or pf != float("inf"))
        self.assertEqual(
            row["trade"]["sufficient"],
            row["trade"]["n_trades"] >= 20 and pf is not None,
        )

    def test_api_accuracy_additive(self):
        import data
        import webapp

        df = make_df(400)
        old = data.get_ohlcv
        data.get_ohlcv = lambda *a, **k: df
        try:
            client = webapp.app.test_client()
            old_r = client.get("/api/accuracy?ticker=TEST")
            new_r = client.get("/api/accuracy?ticker=TEST&horizons=1,5")
        finally:
            data.get_ohlcv = old

        self.assertEqual(old_r.status_code, 200)
        ob = old_r.get_json()
        for k in ("horizon", "calibration", "factors", "agreement", "ticker"):
            self.assertIn(k, ob)
        self.assertNotIn("rows", ob)

        self.assertEqual(new_r.status_code, 200)
        nb = new_r.get_json()
        self.assertEqual(nb["horizons"], [1, 5])
        self.assertEqual(len(nb["rows"]), 2)
        self.assertEqual(nb["ticker"], "TEST")
        for row in nb["rows"]:
            self.assertIn("forward", row)
            self.assertIn("trade", row)

    def test_api_accuracy_single_carries_reliability(self):
        """W-0021: jalur tunggal memuat `reliability` enum valid & identik dgn multi."""
        import data
        import validation
        import webapp

        df = make_df(400)
        old = data.get_ohlcv
        data.get_ohlcv = lambda *a, **k: df
        try:
            client = webapp.app.test_client()
            r = client.get("/api/accuracy?ticker=TEST&horizon=10")
            mult = validation.accuracy_by_horizon(df, horizons=(10,))
        finally:
            data.get_ohlcv = old

        self.assertEqual(r.status_code, 200)
        ob = r.get_json()
        # Bentuk payload lama tetap utuh (additive, bukan ganti konstruk).
        for k in ("horizon", "calibration", "factors", "agreement", "ticker"):
            self.assertIn(k, ob)
        self.assertIn("reliability", ob)
        rel = ob["reliability"]
        self.assertIn(rel["level"], validation.RELIABILITY_LEVELS)
        # Konsisten by construction dengan jalur lintas-horizon.
        self.assertEqual(rel, mult["rows"][0]["reliability"])

    def test_api_accuracy_reliability_failsoft(self):
        """W-0021: kegagalan pelampiran `reliability` TIDAK menjatuhkan mode tunggal."""
        import data
        import validation
        import webapp
        from unittest import mock

        df = make_df(400)
        old = data.get_ohlcv
        data.get_ohlcv = lambda *a, **k: df
        try:
            client = webapp.app.test_client()
            with mock.patch.object(validation, "accuracy_by_horizon",
                                   side_effect=RuntimeError("boom")):
                r = client.get("/api/accuracy?ticker=TEST&horizon=10")
        finally:
            data.get_ohlcv = old

        self.assertEqual(r.status_code, 200)
        ob = r.get_json()
        # Payload dasar tetap tersaji; hanya verdict keandalan yang absen (None).
        for k in ("horizon", "calibration", "factors", "agreement", "ticker"):
            self.assertIn(k, ob)
        self.assertIsNone(ob.get("reliability"))

    def test_api_accuracy_single_carries_oos(self):
        """Gerbang OOS additif: jalur tunggal memuat `oos` (promoted + verdict_levels)."""
        import data
        import validation
        import webapp

        df = make_df(400)
        old = data.get_ohlcv
        data.get_ohlcv = lambda *a, **k: df
        try:
            client = webapp.app.test_client()
            r = client.get("/api/accuracy?ticker=TEST&horizon=10")
        finally:
            data.get_ohlcv = old

        self.assertEqual(r.status_code, 200)
        ob = r.get_json()
        # Bentuk payload lama tetap utuh (additive, bukan ganti konstruk).
        for k in ("horizon", "calibration", "factors", "agreement", "ticker"):
            self.assertIn(k, ob)
        self.assertIn("oos", ob)
        oos = ob["oos"]
        self.assertIsNotNone(oos)
        self.assertIn("promoted", oos)
        self.assertEqual(oos["verdict_levels"], list(validation.RELIABILITY_LEVELS))
        # `oos.horizon` bisa ter-clamp; di sini horizon=10 → identik.
        self.assertEqual(oos["horizon"], 10)
        self.assertEqual(oos["min_edge"], validation.MIN_EDGE)

    def test_api_accuracy_oos_failsoft(self):
        """Kegagalan `candidate_out_of_sample` (mis. sampel tipis) → oos None, status 200."""
        import data
        import validation
        import webapp
        from unittest import mock

        df = make_df(400)
        old = data.get_ohlcv
        data.get_ohlcv = lambda *a, **k: df
        try:
            client = webapp.app.test_client()
            with mock.patch.object(validation, "candidate_out_of_sample",
                                   side_effect=ValueError("Data tidak cukup untuk uji OOS")):
                r = client.get("/api/accuracy?ticker=TEST&horizon=10")
        finally:
            data.get_ohlcv = old

        self.assertEqual(r.status_code, 200)
        ob = r.get_json()
        for k in ("horizon", "calibration", "factors", "agreement", "ticker"):
            self.assertIn(k, ob)
        self.assertIsNone(ob.get("oos"))

    def test_oos_thin_sample_fails_closed(self):
        """Sampel tipis (`n<80`) menolak aman (raise) sehingga endpoint fail-soft → oos None."""
        import validation

        with self.assertRaises(ValueError):
            validation.candidate_out_of_sample(make_df(60), horizon=10)

    def test_api_accuracy_multi_has_no_oos(self):
        """Mode multi-horizon tak berubah: tak mendapat field `oos`."""
        import data
        import webapp

        df = make_df(400)
        old = data.get_ohlcv
        data.get_ohlcv = lambda *a, **k: df
        try:
            client = webapp.app.test_client()
            r = client.get("/api/accuracy?ticker=TEST&horizons=1,5")
        finally:
            data.get_ohlcv = old

        self.assertEqual(r.status_code, 200)
        nb = r.get_json()
        self.assertNotIn("oos", nb)
        self.assertEqual(nb["horizons"], [1, 5])


class TestIndicatorStability(unittest.TestCase):
    """W-0017 lanjutan: agregasi lintas horizon + signifikansi per-indikator."""

    def test_rows_carry_significance(self):
        import validation

        df = make_df(400)
        res = validation.accuracy_by_horizon(df, horizons=(1, 5, 10))
        for row in res["rows"]:
            acc = validation.analyze_accuracy(df, horizon=row["horizon"])
            base_wr = acc["base_win_rate"]
            for f in row["factors"] + row["candidates"]:
                self.assertIn("win_rate_lo", f)
                self.assertIn("significant", f)
                self.assertAlmostEqual(
                    f["win_rate_lo"],
                    validation.wilson_lower_bound(f["win_rate"], f["n"]),
                )
                # Definisi `significant` disamakan dengan `recommendations`.
                self.assertEqual(
                    f["significant"],
                    f["edge"] >= validation.MIN_EDGE and f["win_rate_lo"] > base_wr,
                )

    def test_stability_invariants_and_weighted_edge(self):
        import validation

        df = make_df(400)
        res = validation.accuracy_by_horizon(df, horizons=(1, 5, 10))
        self.assertIn("indicator_stability", res)
        hs = res["horizons"]

        # Presence per faktor dihitung dari row (faktor n<min_n dibuang).
        per_factor: dict[str, list[dict]] = {}
        for row in res["rows"]:
            for f in row["factors"] + row["candidates"]:
                per_factor.setdefault(f["factor"], []).append(f)

        for st in res["indicator_stability"]:
            self.assertEqual(st["candidate"], all(f["candidate"] for f in per_factor[st["factor"]]))
            self.assertEqual(st["n_horizons"], len(per_factor[st["factor"]]))
            self.assertLessEqual(st["n_horizons"], len(hs))
            # consistent hanya bila hadir SEMUA horizon & >=2 horizon & edge>0 semua.
            if st["consistent"]:
                self.assertEqual(st["n_horizons"], len(hs))
                self.assertGreaterEqual(st["n_horizons"], 2)
                self.assertEqual(st["n_positive_edge"], st["n_horizons"])
            # min_edge <= avg_edge <= max_edge; avg_edge dibobot n.
            self.assertLessEqual(st["min_edge"], st["avg_edge"] + 1e-12)
            self.assertLessEqual(st["avg_edge"], st["max_edge"] + 1e-12)
            wsum = sum(f["n"] for f in per_factor[st["factor"]])
            edges = [f["edge"] for f in per_factor[st["factor"]]]
            expected = sum(f["edge"] * f["n"] for f in per_factor[st["factor"]]) / wsum
            self.assertAlmostEqual(st["avg_edge"], expected)
            self.assertEqual(st["min_edge"], min(edges))
            self.assertEqual(st["max_edge"], max(edges))

    def test_absent_factor_never_consistent(self):
        """Faktor yang absen di satu horizon tak boleh diklaim 'konsisten'."""
        import validation

        df = make_df(400)
        hs = (1, 5, 10)
        res = validation.accuracy_by_horizon(df, horizons=hs)
        seen = {st["factor"]: st for st in res["indicator_stability"]}
        for factor, st in seen.items():
            present = sum(
                1 for row in res["rows"]
                for f in row["factors"] + row["candidates"] if f["factor"] == factor
            )
            if present < len(hs):
                self.assertFalse(st["consistent"], factor)

    def test_reliability_schema_and_best_factor_gate(self):
        """W-0021: `reliability` punya skema/enum baku & `best_factor` digerbang signifikan."""
        import validation

        df = make_df(400)
        res = validation.accuracy_by_horizon(df, horizons=(1, 5, 10, 15))
        levels = set(validation.RELIABILITY_LEVELS)

        for row in res["rows"]:
            fwd, tr, rel = row["forward"], row["trade"], row["reliability"]
            for k in ("level", "has_significant", "forward_samples",
                      "trade_sufficient", "timeout_dominated"):
                self.assertIn(k, rel, k)
            self.assertIn(rel["level"], levels)
            # Skema harus konsisten dengan data row (bukan angka karangan).
            self.assertEqual(rel["forward_samples"], fwd["samples"])
            self.assertEqual(rel["trade_sufficient"], tr["sufficient"])
            sig = [x for x in row["factors"] + row["candidates"] if x["significant"]]
            self.assertEqual(rel["has_significant"], bool(sig))
            self.assertEqual(rel["timeout_dominated"],
                             tr["n_trades"] > 0 and tr["avg_bars"] >= row["horizon"] - 1e-9)
            # best_factor/best_edge HANYA dari faktor signifikan; None bila kosong.
            self.assertIn("best_factor", fwd)
            self.assertIn("best_edge", fwd)
            if sig:
                best = max(sig, key=lambda x: x["edge"])
                self.assertEqual(fwd["best_factor"], best["factor"])
                self.assertAlmostEqual(fwd["best_edge"], best["edge"])
            else:
                self.assertIsNone(fwd["best_factor"])
                self.assertIsNone(fwd["best_edge"])

    def test_reliability_enum_distinguishes_timeout_from_thin_sample(self):
        """W-0021: timeout-dominated ≠ sampel kurang; PF tak hingga ≠ sampel kurang."""
        import validation

        lvl = validation._reliability_level
        # Timeout-dominated (mis. h=1): jangan "terbukti", jangan "sampel_kurang".
        self.assertEqual(lvl(True, 500, True, True, 20), "belum_pasti")
        self.assertEqual(lvl(False, 500, True, True, 20), "belum_pasti")
        # Sampel forward tipis: "sampel_kurang".
        self.assertEqual(lvl(False, 5, False, False, 20), "sampel_kurang")
        # PF tak hingga (trade_sufficient False) walau sampel cukup: "belum_pasti".
        self.assertEqual(lvl(True, 500, False, False, 20), "belum_pasti")
        # Bukti lengkap: "terbukti"; sampel cukup tanpa signifikan: "tidak_ada_edge".
        self.assertEqual(lvl(True, 500, True, False, 20), "terbukti")
        self.assertEqual(lvl(False, 500, True, False, 20), "tidak_ada_edge")

    def test_horizon_one_reliability_never_terbukti(self):
        """h=1 timeout-dominated ⇒ tak pernah dilabeli 'terbukti'."""
        import validation

        res = validation.accuracy_by_horizon(make_df(400), horizons=(1,))
        rel = res["rows"][0]["reliability"]
        self.assertTrue(rel["timeout_dominated"])
        self.assertNotEqual(rel["level"], "terbukti")


class TestHorizonBandVerdict(unittest.TestCase):
    """W-0021 lanjutan: ringkasan satu band lintas-horizon dari reliabilitas."""

    @staticmethod
    def _rows(*levels):
        return [
            {"horizon": h, "reliability": {"level": lvl, "has_significant": lvl == "terbukti"}}
            for h, lvl in zip((1, 5, 10, 15), levels)
        ]

    def test_all_four_levels(self):
        import validation

        hbv = validation.horizon_band_verdict
        self.assertEqual(hbv(self._rows("terbukti", "terbukti", "terbukti", "terbukti"))["level"], "terbukti")
        self.assertEqual(hbv(self._rows("belum_pasti", "belum_pasti"))["level"], "belum_pasti")
        self.assertEqual(hbv(self._rows("sampel_kurang", "sampel_kurang"))["level"], "sampel_kurang")
        self.assertEqual(hbv(self._rows("tidak_ada_edge", "tidak_ada_edge"))["level"], "tidak_ada_edge")

    def test_tidak_ada_edge_vetoes_terbukti(self):
        import validation

        band = validation.horizon_band_verdict(
            self._rows("terbukti", "terbukti", "tidak_ada_edge", "belum_pasti")
        )
        self.assertEqual(band["level"], "tidak_ada_edge")

    def test_timeout_belum_pasti_does_not_veto_terbukti(self):
        """h=1 selalu timeout-dominated (belum_pasti) tak boleh mengunci band."""
        import validation

        band = validation.horizon_band_verdict(
            self._rows("belum_pasti", "terbukti", "belum_pasti", "belum_pasti")
        )
        self.assertEqual(band["level"], "terbukti")
        self.assertEqual(band["n_terbukti"], 1)

    def test_sampel_kurang_outranks_belum_pasti(self):
        import validation

        band = validation.horizon_band_verdict(self._rows("sampel_kurang", "belum_pasti"))
        self.assertEqual(band["level"], "sampel_kurang")

    def test_empty_and_single_horizon_safe(self):
        import validation

        hbv = validation.horizon_band_verdict
        self.assertIsNone(hbv([])["level"])
        self.assertIsNone(hbv(None)["level"])
        one = hbv(self._rows("terbukti"))
        self.assertEqual(one["level"], "terbukti")
        self.assertEqual(one["n_horizons"], 1)

    def test_balanced_counts(self):
        import validation

        band = validation.horizon_band_verdict(
            self._rows("terbukti", "belum_pasti", "terbukti", "tidak_ada_edge")
        )
        self.assertEqual(band["n_horizons"], 4)
        self.assertEqual(band["n_terbukti"], 2)
        self.assertEqual(band["n_significant_horizons"], 2)
        self.assertEqual(band["horizons"], [1, 5, 10, 15])

    def test_accuracy_payload_carries_band_verdict(self):
        import validation

        res = validation.accuracy_by_horizon(make_df(400), horizons=(1, 5, 10, 15))
        band = res["band_verdict"]
        self.assertEqual(band["level"], validation.horizon_band_verdict(res["rows"])["level"])
        self.assertEqual(band["n_horizons"], len(res["rows"]))
        self.assertEqual(band["horizons"], [1, 5, 10, 15])


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


class TestNewsCacheBound(unittest.TestCase):
    """Cache berita tidak boleh tumbuh tak terbatas oleh ticker arbitrer dari klien."""

    def test_news_cache_stays_bounded(self):
        from unittest.mock import patch

        import news

        news._cache.clear()
        total = news._CACHE_MAX + 300
        try:
            with patch("news._raw_items", return_value=[]):
                for i in range(total):
                    self.assertIsNotNone(news.get_news(f"T{i}"))
                # Key `m:` juga harus kena batas yang sama.
                self.assertIsNotNone(news.get_market_news(tickers=["BBCA"]))
            self.assertLessEqual(len(news._cache), news._CACHE_MAX)
            # Entri terbaru tetap tersedia (eviksi dari yang paling lama).
            self.assertIn("t:" + news.to_yahoo(f"T{total - 1}"), news._cache)
            self.assertIn("m:BBCA", news._cache)
        finally:
            news._cache.clear()


class TestFundamentalsCacheBound(unittest.TestCase):
    """Cache fundamental tidak boleh tumbuh tak terbatas oleh ticker arbitrer dari klien."""

    def test_fundamentals_cache_stays_bounded(self):
        from unittest.mock import patch

        import fundamentals

        fundamentals._cache.clear()
        total = fundamentals._CACHE_MAX + 300
        fake = {"longName": "PT Test", "sector": "Financials"}
        try:
            with patch("fundamentals.yf.Ticker") as mock_ticker, \
                 patch("data.get_quote", return_value=None), \
                 patch("data.get_ohlcv", return_value=None):
                mock_ticker.return_value.info = fake
                for i in range(total):
                    self.assertIsNotNone(fundamentals.get_fundamentals(f"T{i}"))
            self.assertLessEqual(len(fundamentals._cache), fundamentals._CACHE_MAX)
            # Entri terbaru tetap tersedia (eviksi dari yang paling lama).
            self.assertIn(fundamentals.to_yahoo(f"T{total - 1}"), fundamentals._cache)
        finally:
            fundamentals._cache.clear()

    def test_oversized_ticker_not_cached_nor_fetched(self):
        from unittest.mock import patch

        import fundamentals

        fundamentals._cache.clear()
        try:
            with patch("fundamentals.yf.Ticker") as mock_ticker:
                res = fundamentals.get_fundamentals("A" * 40)
                mock_ticker.assert_not_called()
            self.assertEqual(fundamentals._cache, {})
            self.assertIn("error", res)
        finally:
            fundamentals._cache.clear()


class TestFundamentalsSanitize(unittest.TestCase):
    """Sanitasi rasio + flag `available`/`suspect` (bukan truthiness `info` mentah)."""

    def setUp(self):
        import fundamentals

        self.fundamentals = fundamentals
        fundamentals._cache.clear()

    def tearDown(self):
        self.fundamentals._cache.clear()

    def test_clean_rejects_non_numeric_and_non_finite(self):
        c = self.fundamentals._clean
        self.assertIsNone(c("N/A"))
        self.assertIsNone(c(None))
        self.assertIsNone(c("abc"))
        self.assertIsNone(c(float("inf")))
        self.assertIsNone(c(float("-inf")))
        self.assertIsNone(c(float("nan")))
        self.assertEqual(c("12.5"), 12.5)

    def test_impossible_ratios_dropped_extreme_flagged(self):
        from unittest.mock import patch

        import fundamentals

        fake = {
            "currentPrice": 100.0,
            "trailingPE": -5.0,
            "priceToBook": 41.249,
            "debtToEquity": -3.0,
            "beta": float("inf"),
        }
        with patch("fundamentals.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.info = fake
            out = fundamentals.get_fundamentals("BUMI")
        self.assertIsNone(out["pe"])
        self.assertIsNone(out["der"])
        self.assertIsNone(out["beta"])
        # Nilai ekstrem tapi sah dipertahankan dan ditandai suspect.
        self.assertEqual(out["pb"], 41.249)
        self.assertIn("pb", out["suspect"])
        self.assertTrue(out["available"])

    def test_partial_info_not_available_and_short_ttl(self):
        from unittest.mock import patch

        import fundamentals

        fake = {"longName": "PT Test", "sector": "Financials"}
        with patch("fundamentals.yf.Ticker") as mock_ticker, \
             patch("data.get_quote", return_value=None), \
             patch("data.get_ohlcv", return_value=None):
            mock_ticker.return_value.info = fake
            out = fundamentals.get_fundamentals("MINOR")
        self.assertFalse(out["available"])
        self.assertFalse(out["has_financials"])
        entry = fundamentals._cache[fundamentals.to_yahoo("MINOR")]
        self.assertEqual(entry[2], fundamentals._NEGATIVE_TTL)

    def test_available_uses_key_fields_full_ttl(self):
        from unittest.mock import patch

        import fundamentals

        fake = {"currentPrice": 1234.0}
        with patch("fundamentals.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.info = fake
            out = fundamentals.get_fundamentals("BBCA")
        self.assertTrue(out["available"])
        entry = fundamentals._cache[fundamentals.to_yahoo("BBCA")]
        self.assertEqual(entry[2], fundamentals._TTL)

    def test_price_fallback_available_without_financials(self):
        from unittest.mock import patch

        import fundamentals

        fake = {"longName": "PT Rugi", "sector": "Industrials"}
        hist = pd.DataFrame({"Close": [100.0, 250.0]})
        with patch("fundamentals.yf.Ticker") as mock_ticker, \
             patch("data.get_quote", return_value={"last": 250.0}), \
             patch("data.get_ohlcv", return_value=hist):
            mock_ticker.return_value.info = fake
            out = fundamentals.get_fundamentals("RUGIX")
        self.assertTrue(out["available"])
        self.assertFalse(out["has_financials"])
        self.assertEqual(out["price"], 250.0)
        self.assertEqual(out["reason"], "ok")
        entry = fundamentals._cache[fundamentals.to_yahoo("RUGIX")]
        self.assertEqual(entry[2], fundamentals._TTL)

    def test_price_fallback_uses_history_when_quote_missing(self):
        from unittest.mock import patch

        import fundamentals

        fake = {"longName": "PT Rugi", "sector": "Industrials"}
        hist = pd.DataFrame({"Close": [100.0, 275.0]})
        with patch("fundamentals.yf.Ticker") as mock_ticker, \
             patch("data.get_quote", return_value=None), \
             patch("data.get_ohlcv", return_value=hist):
            mock_ticker.return_value.info = fake
            out = fundamentals.get_fundamentals("RUGIY")
        self.assertEqual(out["price"], 275.0)
        self.assertTrue(out["available"])
        self.assertFalse(out["has_financials"])

    def test_fetch_error_distinguished_from_empty(self):
        from unittest.mock import patch

        import fundamentals

        with patch("fundamentals.yf.Ticker", side_effect=RuntimeError("net")), \
             patch("data.get_quote", return_value=None), \
             patch("data.get_ohlcv", return_value=None):
            out = fundamentals.get_fundamentals("ERRX")
        self.assertFalse(out["available"])
        self.assertEqual(out["reason"], "error")
        entry = fundamentals._cache[fundamentals.to_yahoo("ERRX")]
        self.assertEqual(entry[2], fundamentals._NEGATIVE_TTL)

        with patch("fundamentals.yf.Ticker") as mock_ticker, \
             patch("data.get_quote", return_value=None), \
             patch("data.get_ohlcv", return_value=None):
            mock_ticker.return_value.info = {}
            out = fundamentals.get_fundamentals("EMPTYX")
        self.assertFalse(out["available"])
        self.assertEqual(out["reason"], "empty")

    def _fetch(self, fake):
        from unittest.mock import patch

        with patch("fundamentals.yf.Ticker") as mock_ticker, \
             patch("data.get_quote", return_value=None), \
             patch("data.get_ohlcv", return_value=None):
            mock_ticker.return_value.info = fake
            return self.fundamentals.get_fundamentals("CEK")

    def test_forward_pe_never_replaces_ttm(self):
        out = self._fetch({"currentPrice": 1000.0, "forwardPE": 8.0, "trailingEps": -20.0})
        self.assertIsNone(out["pe"])
        self.assertEqual(out["pe_forward"], 8.0)
        self.assertNotEqual(out["valuation_code"], "rendah")

    def test_pe_matches_price_over_eps(self):
        out = self._fetch({"currentPrice": 5175.0, "trailingEps": 472.0, "trailingPE": 99.0})
        self.assertAlmostEqual(out["pe"], 5175.0 / 472.0, places=4)
        self.assertIn("pe", out["suspect"])

    def test_pe_keeps_yahoo_when_close(self):
        out = self._fetch({"currentPrice": 5175.0, "trailingEps": 472.0, "trailingPE": 10.963983})
        self.assertAlmostEqual(out["pe"], 10.963983, places=4)
        self.assertNotIn("pe", out["suspect"])

    def test_absurd_book_value_is_dropped(self):
        out = self._fetch({
            "currentPrice": 2210.0,
            "bookValue": 0.16,
            "priceToBook": 13812.5,
            "trailingPE": 6.5,
            "trailingEps": 340.0,
        })
        self.assertIsNone(out["book_value"])
        self.assertIsNone(out["pb"])
        self.assertTrue(any("tidak masuk akal" in c for c in out["checks"]))

    def test_dividend_percent_and_fraction_and_cash(self):
        pct = self._fetch({"currentPrice": 5175.0, "dividendYield": 6.27})
        self.assertAlmostEqual(pct["dividend_yield"], 6.27, places=2)
        self.fundamentals._cache.clear()
        frac = self._fetch({"currentPrice": 5175.0, "dividendYield": 0.0627})
        self.assertAlmostEqual(frac["dividend_yield"], 6.27, places=2)
        self.fundamentals._cache.clear()
        cash = self._fetch({
            "currentPrice": 5175.0,
            "dividendYield": 99.0,
            "dividendRate": 324.4725,
        })
        self.assertAlmostEqual(cash["dividend_yield"], 6.27, places=2)
        self.assertIn("harga", cash["dividend_basis"])
        self.fundamentals._cache.clear()
        dust = self._fetch({
            "currentPrice": 2210.0,
            "dividendYield": 9.61,
            "trailingAnnualDividendRate": 0.007,
        })
        self.assertAlmostEqual(dust["dividend_yield"], 9.61, places=2)
        self.assertIn("dividend", dust["suspect"])

    def test_bank_pe_uses_sector_band_not_the_general_screen(self):
        import fundamentals
        bank = fundamentals.classify_ratios(10.96, 0.22, 20, sector="Perbankan")
        plain = fundamentals.classify_ratios(10.96, 0.22, 20)
        cheap_bank = fundamentals.classify_ratios(5.1, 0.22, 20, sector="Perbankan")
        coal = fundamentals.classify_ratios(6.5, 0.2, 30, sector="Energi")
        tech = fundamentals.classify_ratios(25.0, 0.1, 10, sector="Teknologi")
        self.assertEqual(bank["valuation_code"], "wajar")
        self.assertEqual(plain["valuation_code"], "rendah")
        self.assertEqual(cheap_bank["valuation_code"], "rendah")
        self.assertEqual(coal["valuation_code"], "wajar")
        self.assertEqual(tech["valuation_code"], "wajar")
        self.assertIn("Perbankan", bank["valuation_note"])
        self.assertIn("bukan median", bank["valuation_note"])

    def test_missing_der_is_not_healthy(self):
        labels = self.fundamentals.classify_ratios(10.0, 0.22, None)
        self.assertNotEqual(labels["quality_code"], "baik")
        self.assertIn("DER", labels["quality_note"])

    def test_rsi_flat_is_neutral_and_rising_is_high(self):
        import indicators

        flat = indicators.rsi(pd.Series([10.0] * 40))
        self.assertTrue(bool((flat == 50.0).all()))
        rising = indicators.rsi(pd.Series([float(i) for i in range(1, 41)]))
        self.assertGreater(float(rising.iloc[-1]), 90.0)


class TestFundTechAlignment(unittest.TestCase):
    """Konfluensi deterministik teknikal x fundamental bersifat additive.

    Output WAJIB hanya metadata (``status``/``note``) dan tidak boleh memuat
    bobot/delta numerik apa pun, agar penalti DIVERGEN tidak diam-diam masuk ke
    voting/konsensus tanpa bukti out-of-sample (W-0024).
    """

    def test_alignment_states(self):
        import musyawarah

        good = {"category": "Big Cap · Kualitas Baik", "valuation": "Valuasi Murah"}
        weak = {"category": "Small Cap · Rugi", "valuation": "Valuasi Mahal"}
        self.assertEqual(musyawarah._fund_tech_alignment("BULLISH", good, True)["status"], "SEARAH")
        self.assertEqual(musyawarah._fund_tech_alignment("BEARISH", weak, True)["status"], "SEARAH")
        self.assertEqual(musyawarah._fund_tech_alignment("BULLISH", weak, True)["status"], "DIVERGEN")
        self.assertEqual(musyawarah._fund_tech_alignment("BEARISH", good, True)["status"], "DIVERGEN")
        self.assertEqual(musyawarah._fund_tech_alignment("NETRAL", good, True)["status"], "NETRAL")
        self.assertEqual(musyawarah._fund_tech_alignment("BULLISH", {}, False)["status"], "n/a")

    def test_alignment_is_metadata_only(self):
        import musyawarah

        good = {"category": "Big Cap · Kualitas Baik", "valuation": "Valuasi Murah"}
        weak = {"category": "Small Cap · Rugi", "valuation": "Valuasi Mahal"}
        cases = (
            ("BULLISH", good, True), ("BULLISH", weak, True),
            ("BEARISH", good, True), ("BEARISH", weak, True),
            ("NETRAL", good, True), ("BULLISH", {}, False),
        )
        for bias, fund, avail in cases:
            out = musyawarah._fund_tech_alignment(bias, fund, avail)
            self.assertEqual(set(out), {"status", "note"})
            for value in out.values():
                self.assertIsInstance(value, str)
                self.assertNotIn("conviction", value.lower())
                self.assertNotIn("kurangi", value.lower())


class TestMusyawarahConsensusWeights(unittest.TestCase):
    """Konsensus Musyawarah tak boleh ter-dilusi saat rasio fundamental absen (W-0024).

    Pemicu WAJIB ``has_financials=False`` (data rasio benar-benar kosong),
    bukan ``available`` (harga selalu di-backfill sehingga hampir selalu True).
    Bobot agen fundamental dikeluarkan lalu sisa bobot direnormalisasi; agen
    fundamental dengan data ada (walau verdict netral) TIDAK dikeluarkan.
    """

    def test_agent_weights_full(self):
        import musyawarah

        w = musyawarah._agent_weights(True)
        self.assertEqual(w, {"technical": 0.40, "bandarmologi": 0.30,
                             "fundamental": 0.15, "sentiment": 0.15})

    def test_agent_weights_renormalized_when_absent(self):
        import musyawarah

        w = musyawarah._agent_weights(False)
        self.assertNotIn("fundamental", w)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
        self.assertAlmostEqual(w["technical"], 0.40 / 0.85, places=9)
        self.assertAlmostEqual(w["bandarmologi"], 0.30 / 0.85, places=9)
        self.assertAlmostEqual(w["sentiment"], 0.15 / 0.85, places=9)

    def _fake_analysis(self):
        class _A:
            pass

        a = _A()
        a.signal, a.price = "BUY", 1000.0
        a.trend = a.weekly_trend = a.monthly_trend = "uptrend"
        a.regime, a.rsi, a.adx, a.macd_hist = "normal", 55.0, 25.0, 0.5
        a.support, a.resistance = 950.0, 1100.0
        a.score, a.grade = 70, "B"
        a.entry_breakout, a.rr2 = 1000.0, 3.0
        a.buy_zone_high, a.entry, a.tp2, a.stop_loss = 1010.0, 1000.0, 1200.0, 950.0
        a.decision, a.market_regime = {}, "uptrend"
        return a

    def _run(self, fund, luar=None):
        from unittest.mock import patch

        import musyawarah

        if luar is None:
            luar = {
                "status": "netral", "label": "Netral", "intensity": 0,
                "summary": "Tidak ada tekanan luar yang teridentifikasi.",
                "drivers": [],
            }
        df = make_df()
        a = self._fake_analysis()
        with patch("musyawarah.data.get_ohlcv", return_value=df), \
             patch("musyawarah.data.get_quote", return_value={}), \
             patch("musyawarah.data.apply_live_quote", return_value=(df, None)), \
             patch("musyawarah.analyze", return_value=a), \
             patch("musyawarah.fundamentals.get_fundamentals", return_value=fund), \
             patch("musyawarah.news.get_news", return_value={"label": "Netral", "avg_sentiment": 0, "count": 0}), \
             patch("musyawarah.market.ihsg", return_value={}), \
             patch("musyawarah.external.for_stock", return_value=luar), \
             patch("musyawarah.ml.predict", side_effect=RuntimeError("no ml")):
            return musyawarah.musyawarah("TEST")

    def _full(self):
        return {"available": True, "has_financials": True, "name": "TEST",
                "pe": 10.0, "pb": 1.5, "roe": 0.20, "der": 50.0,
                "market_cap": 1e14, "dividend_yield": 0.02}

    def test_full_fundamental_keeps_original_weights(self):
        d = self._run(self._full())
        self.assertTrue(d["has_financials"])
        self.assertTrue(d["fundamental_available"])
        self.assertEqual(set(d["weights_used"]), {"technical", "bandarmologi",
                                                  "fundamental", "sentiment"})
        self.assertAlmostEqual(d["weights_used"]["fundamental"], 0.15, places=4)
        w = {"technical": 0.40, "bandarmologi": 0.30, "fundamental": 0.15, "sentiment": 0.15}
        exp = round(sum(w[k] * d["votes"][k] for k in w), 3)
        self.assertEqual(d["consensus"], exp)
        self.assertIn("fundamental", d["votes"])

    def test_price_only_excluded_and_not_diluted(self):
        fund = {"available": True, "has_financials": False, "name": "TEST",
                "pe": None, "pb": None, "roe": None, "der": None, "market_cap": None}
        d = self._run(fund)
        self.assertTrue(d["fundamental_available"])
        self.assertFalse(d["has_financials"])
        self.assertNotIn("fundamental", d["weights_used"])
        self.assertAlmostEqual(sum(d["weights_used"].values()), 1.0, places=3)

    def test_unavailable_and_price_only_share_weights(self):
        unavailable = {"available": False, "has_financials": False, "name": "TEST",
                       "pe": None, "pb": None, "roe": None, "der": None, "market_cap": None}
        price_only = {"available": True, "has_financials": False, "name": "TEST",
                      "pe": None, "pb": None, "roe": None, "der": None, "market_cap": None}
        d1 = self._run(unavailable)
        d2 = self._run(price_only)
        self.assertFalse(d1["fundamental_available"])
        self.assertTrue(d2["fundamental_available"])
        self.assertEqual(d1["weights_used"], d2["weights_used"])
        self.assertEqual(d1["consensus"], d2["consensus"])

    def test_neutral_fundamental_not_excluded(self):
        fund = {"available": True, "has_financials": True, "name": "TEST",
                "pe": 15.0, "pb": 1.0, "roe": 0.10, "der": 50.0, "market_cap": 1e13}
        d = self._run(fund)
        self.assertIn("fundamental", d["weights_used"])
        w = {"technical": 0.40, "bandarmologi": 0.30, "fundamental": 0.15, "sentiment": 0.15}
        exp = round(sum(w[k] * d["votes"][k] for k in w), 3)
        self.assertEqual(d["consensus"], exp)

    def test_tekanan_luar_cuts_sentiment_and_holds_buy(self):
        """Tekanan luar terkonfirmasi memotong sentimen 0,4 dan menahan BUY."""
        luar = {
            "status": "tekanan_luar",
            "label": "Tekanan luar",
            "intensity": 70,
            "summary": "IHSG melemah bersama tekanan luar: Rebalancing indeks (MSCI/FTSE).",
            "drivers": [],
        }
        calm = self._run(self._full())
        hot = self._run(self._full(), luar=luar)
        w = {"technical": 0.40, "bandarmologi": 0.30, "fundamental": 0.15, "sentiment": 0.15}
        self.assertEqual(hot["consensus"], round(sum(w[k] * hot["votes"][k] for k in w), 3))
        self.assertEqual(hot["weights_used"], calm["weights_used"])
        self.assertAlmostEqual(
            hot["votes"]["sentiment"],
            round(max(-1.0, calm["votes"]["sentiment"] - 0.4), 2),
        )
        self.assertLess(hot["consensus"], calm["consensus"])
        self.assertIn("Tekanan luar terkonfirmasi", " ".join(hot["vetoes"]))
        self.assertEqual(hot["decision"], "WAIT")
        self.assertIn("MSCI", hot["text"])


class TestExternalPressure(unittest.TestCase):
    """Tekanan di luar teknikal/fundamental: disebut hanya bila ada bukti."""

    def test_msci_plus_ihsg_down_is_external_pressure(self):
        import external
        result = external.assess(
            macro_items=[{
                "title": "IHSG anjlok tertekan rebalancing MSCI, investor asing jual",
                "summary": None,
            }],
            ihsg={"ret_1d": -2.2, "ret_5d": -3.4, "regime": "Bearish"},
            news_ok=True,
            stock_ret_1d=-1.1,
        )
        self.assertEqual(result["status"], "tekanan_luar")
        self.assertTrue(any(d["id"] == "indeks_pasif" for d in result["drivers"]))
        self.assertIn("MSCI", result["summary"])
        self.assertIn("luar teknikal", result["summary"])
        self.assertIn("lebih tahan", result["coupling"])

    def test_fx_stress_does_not_invent_msci(self):
        import external
        result = external.assess(
            macro_items=[],
            ihsg={"ret_1d": -2.0, "ret_5d": -1.2, "regime": "Bearish"},
            usdidr_ret_5d=1.4,
            usdidr_ok=True,
            news_ok=True,
        )
        self.assertEqual(result["status"], "tekanan_luar")
        ids = {d["id"] for d in result["drivers"]}
        self.assertIn("kurs", ids)
        self.assertNotIn("indeks_pasif", ids)
        self.assertNotIn("MSCI", result["summary"])

    def test_broad_drop_without_cause_stays_unnamed(self):
        import external
        result = external.assess(
            macro_items=[],
            ihsg={"ret_1d": -1.8, "ret_5d": -0.4, "regime": "Netral"},
            usdidr_ok=True,
            usdidr_ret_5d=0.2,
            global_ok=True,
            global_ret_5d=-0.4,
            news_ok=True,
        )
        self.assertEqual(result["status"], "pelemahan_pasar")
        self.assertEqual(result["drivers"], [])
        self.assertIn("belum terbaca", result["summary"])

    def test_msci_mention_without_shock_is_watch(self):
        import external
        result = external.assess(
            macro_items=[{"title": "MSCI keluarkan beberapa saham dari indeks", "summary": ""}],
            ihsg={"ret_1d": -0.2, "ret_5d": 0.3, "regime": "Netral"},
            news_ok=True,
        )
        self.assertEqual(result["status"], "waspada_luar")
        self.assertEqual(result["drivers"][0]["id"], "indeks_pasif")
        self.assertEqual(result["drivers"][0]["direction"], "turun")

    def test_unnamed_rebalance_follows_the_index_shock(self):
        import external
        result = external.assess(
            macro_items=[{"title": "MSCI umumkan rebalancing indeks", "summary": ""}],
            ihsg={"ret_1d": -1.6, "ret_5d": -0.5},
            news_ok=True,
        )
        self.assertEqual(result["status"], "tekanan_luar")
        self.assertEqual(result["drivers"][0]["direction"], "netral")

    def test_stock_specific_drop_is_not_market_pressure(self):
        import external
        result = external.assess(
            ihsg={"ret_1d": 0.2, "ret_5d": 0.4, "regime": "Bullish"},
            stock_ret_1d=-2.5,
            news_ok=True,
        )
        self.assertEqual(result["status"], "tekanan_emiten")
        self.assertEqual(result["drivers"], [])

    def test_ticker_commodity_headline_is_not_macro(self):
        import external
        result = external.assess(
            ticker_items=[{"title": "Harga batu bara anjlok, emiten tambang tertekan", "summary": ""}],
            ihsg={"ret_1d": 0.1, "ret_5d": 0.2},
            news_ok=True,
        )
        self.assertFalse(any(d["id"] == "komoditas" for d in result["drivers"]))
        self.assertEqual(result["status"], "netral")

    def test_macro_commodity_shock_is_external(self):
        import external
        result = external.assess(
            macro_items=[{"title": "Harga batu bara anjlok dan menekan bursa", "summary": ""}],
            ihsg={"ret_1d": 0.1, "ret_5d": 0.2},
            news_ok=True,
        )
        self.assertEqual(result["status"], "waspada_luar")
        self.assertEqual(result["drivers"][0]["id"], "komoditas")

    def test_rate_hike_pressures_and_cut_supports(self):
        import external
        hike = external.assess(
            macro_items=[{"title": "The Fed menaikkan suku bunga acuan", "summary": ""}],
            ihsg={"ret_1d": -1.3, "ret_5d": -0.2},
            news_ok=True,
        )
        cut = external.assess(
            macro_items=[{"title": "Bank Indonesia pangkas suku bunga", "summary": ""}],
            ihsg={"ret_1d": 1.2, "ret_5d": 0.4},
            news_ok=True,
        )
        self.assertEqual(hike["status"], "tekanan_luar")
        self.assertEqual(hike["drivers"][0]["direction"], "turun")
        self.assertEqual(cut["status"], "dukungan_luar")
        self.assertEqual(cut["drivers"][0]["direction"], "naik")

    def test_nothing_observed_is_unavailable(self):
        import external
        result = external.assess(news_ok=False)
        self.assertEqual(result["status"], "tidak_tersedia")
        self.assertEqual(result["intensity"], 0)

    def test_summary_only_mention_does_not_create_driver(self):
        import external
        result = external.assess(
            macro_items=[{
                "title": "Analisis teknikal IHSG hari ini",
                "summary": "Di dalam ringkasan disebut MSCI dan Wall Street secara sampingan.",
            }],
            ihsg={"ret_1d": -1.5, "ret_5d": -0.2},
            news_ok=True,
        )
        self.assertEqual(result["drivers"], [])
        self.assertEqual(result["status"], "pelemahan_pasar")

    def test_x_posts_keep_market_talk_from_anyone(self):
        import xsource
        rows = xsource.keep_market_posts([
            {"title": "IHSG anjlok 8% gara-gara MSCI, asing ikut jual - X",
             "link": "https://news.google.com/rss/articles/a"},
            {"title": "Extra Time Indonesia mencetak gol - X",
             "link": "https://news.google.com/rss/articles/b"},
            {"title": "Rupiah", "link": "https://news.google.com/rss/articles/c"},
        ])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["title"].startswith("Pos X:"))
        self.assertIn("MSCI", rows[0]["title"])
        self.assertEqual(rows[0]["stance"], "jual")
        cmp = xsource.compare_signal("BUY", rows)
        self.assertEqual(cmp["ours"], "beli")
        self.assertEqual(cmp["theirs"], "jual")
        self.assertEqual(cmp["alignment"], "berlawanan")
        empty = xsource.compare_signal("HOLD", [])
        self.assertEqual(empty["alignment"], "belum cukup")

    def test_macro_query_rejects_unsafe_text_offline(self):
        import news
        items, ok = news.headlines_for_query("IHSG <msci>")
        self.assertEqual(items, [])
        self.assertTrue(ok)


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


class TestStateBounds(unittest.TestCase):
    """Cache runtime dibatasi agar input tak-terbatas tak menumbuhkan memori."""

    def setUp(self):
        import os

        import state

        self._state = state
        self._old_env = os.environ.get("RATE_LIMIT_PER_MIN")

    def tearDown(self):
        import os

        if self._old_env is None:
            os.environ.pop("RATE_LIMIT_PER_MIN", None)
        else:
            os.environ["RATE_LIMIT_PER_MIN"] = self._old_env
        self._state._rl.clear()
        with self._state._metrics_lock:
            self._state._metrics["by_path"].clear()

    def test_rl_cache_is_bounded(self):
        import os

        os.environ["RATE_LIMIT_PER_MIN"] = "1"
        old = self._state._RL_MAX_IPS
        try:
            self._state._RL_MAX_IPS = 64
            self._state._rl.clear()
            for i in range(200):
                self._state.rate_limited(f"10.1.{i // 256}.{i % 256}")
            self.assertLessEqual(len(self._state._rl), 64)
        finally:
            self._state._RL_MAX_IPS = old

    def test_active_ip_still_rate_limited_at_bound(self):
        import os

        os.environ["RATE_LIMIT_PER_MIN"] = "1"
        old = self._state._RL_MAX_IPS
        try:
            self._state._RL_MAX_IPS = 64
            self._state._rl.clear()
            for i in range(200):
                self._state.rate_limited(f"10.2.{i // 256}.{i % 256}")
            self._state.rate_limited("10.9.9.9")
            self.assertTrue(self._state.rate_limited("10.9.9.9"))
        finally:
            self._state._RL_MAX_IPS = old

    def test_long_lived_active_ip_survives_lru_eviction(self):
        import os

        os.environ["RATE_LIMIT_PER_MIN"] = "1"
        old = self._state._RL_MAX_IPS
        try:
            self._state._RL_MAX_IPS = 4
            self._state._rl.clear()
            # IP lama yang terus aktif: hit pertama, lalu sudah kena limit.
            self.assertFalse(self._state.rate_limited("10.0.0.1"))
            self.assertTrue(self._state.rate_limited("10.0.0.1"))
            # Banjiri dengan IP unik (memicu eviksi) sambil IP lama tetap
            # mengakses, seperti penyerang yang mencoba me-reset window.
            for i in range(2, 40):
                # Wajib tetap limit TIAP iterasi: eviksi FIFO urutan-sisip
                # membuang IP lama ini lalu me-reset window-nya -> False.
                self.assertTrue(self._state.rate_limited("10.0.0.1"))
                self._state.rate_limited(f"10.0.{i}.1")
            self.assertIn("10.0.0.1", self._state._rl)
            self.assertLessEqual(len(self._state._rl), 4)
        finally:
            self._state._RL_MAX_IPS = old

    def test_metrics_by_path_is_bounded(self):
        old = self._state._METRICS_PATH_MAX
        try:
            self._state._METRICS_PATH_MAX = 64
            with self._state._metrics_lock:
                self._state._metrics["by_path"].clear()
            for i in range(200):
                self._state.tick_metrics(f"/xxx{i}", 200)
            with self._state._metrics_lock:
                self.assertLessEqual(len(self._state._metrics["by_path"]), 64)
        finally:
            self._state._METRICS_PATH_MAX = old


class TestScanJobBounds(unittest.TestCase):
    """Kuota job scan dibatasi; job nyangkut dieviksi via TTL agar tak self-DoS."""

    def setUp(self):
        import state

        self._state = state
        self._saved_jobs = dict(state._scan_jobs)
        self._saved_max = state.SCAN_JOBS_MAX
        self._saved_ttl = state.SCAN_JOB_TTL
        with state._scan_lock:
            state._scan_jobs.clear()

    def tearDown(self):
        state = self._state
        state.SCAN_JOBS_MAX = self._saved_max
        state.SCAN_JOB_TTL = self._saved_ttl
        with state._scan_lock:
            state._scan_jobs.clear()
            state._scan_jobs.update(self._saved_jobs)

    def test_create_returns_none_when_full(self):
        state = self._state
        state.SCAN_JOBS_MAX = 3
        state.SCAN_JOB_TTL = 600
        for _ in range(3):
            self.assertIsNotNone(state.create_scan_job({}))
        self.assertIsNone(state.create_scan_job({}))
        self.assertLessEqual(len(state._scan_jobs), 3)

    def test_terminal_job_is_evicted(self):
        state = self._state
        state.SCAN_JOBS_MAX = 1
        state.SCAN_JOB_TTL = 600
        old = state.create_scan_job({})
        state.update_scan_job(old, state="done")
        self.assertIsNotNone(state.create_scan_job({}))
        self.assertLessEqual(len(state._scan_jobs), 1)

    def test_stuck_job_evicted_by_ttl(self):
        state = self._state
        state.SCAN_JOBS_MAX = 1
        state.SCAN_JOB_TTL = 1
        old = state.create_scan_job({})
        self.assertIsNotNone(old)
        with state._scan_lock:
            state._scan_jobs[old]["created"] -= 10  # job 'running' nyangkut
        self.assertIsNotNone(state.create_scan_job({}))

    def test_expired_job_marked_terminal_not_evicted(self):
        state = self._state
        state.SCAN_JOBS_MAX = 1
        state.SCAN_JOB_TTL = 1
        old = state.create_scan_job({})
        with state._scan_lock:
            state._scan_jobs[old]["created"] -= 10  # job 'running' nyangkut
        self.assertIsNotNone(state.create_scan_job({}))  # kuota bebas
        payload = state.get_scan_job(old)
        self.assertIsNotNone(payload)  # bukan 404
        self.assertEqual(payload["state"], "error")
        self.assertEqual(payload["error"], "kedaluwarsa")
        self.assertTrue(state.cancel_scan_job(old))

    def test_terminal_job_not_resurrected_by_update(self):
        state = self._state
        state.SCAN_JOBS_MAX = 2
        state.SCAN_JOB_TTL = 600
        jid = state.create_scan_job({})
        state.update_scan_job(jid, state="cancelled")
        state.update_scan_job(jid, state="running", scanned=5)  # TOCTOU write
        payload = state.get_scan_job(jid)
        self.assertEqual(payload["state"], "cancelled")
        self.assertEqual(payload["scanned"], 0)

    def test_nonpositive_ttl_does_not_break_cap(self):
        state = self._state
        state.SCAN_JOBS_MAX = 2
        state.SCAN_JOB_TTL = 0
        for _ in range(2):
            self.assertIsNotNone(state.create_scan_job({}))
        self.assertIsNone(state.create_scan_job({}))

    def test_api_scan_start_returns_429_when_full(self):
        import time

        import webapp

        state = self._state
        state.SCAN_JOBS_MAX = 1
        state.SCAN_JOB_TTL = 600
        with state._scan_lock:
            state._scan_jobs["busy"] = {
                "state": "running", "scanned": 0, "total": 0, "rows": [],
                "created": time.time(), "cancel": False, "error": None,
            }
        r = webapp.app.test_client().post("/api/scan/start", json={"list": "lq45"})
        self.assertEqual(r.status_code, 429)
        self.assertIn("Terlalu banyak scan aktif", r.get_json().get("error", ""))
        with state._scan_lock:
            self.assertLessEqual(len(state._scan_jobs), 1)


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


class TestNewsStoreEviction(unittest.TestCase):
    """Invarian statik penyimpanan kartu berita (W-0010 iterasi #4).

    Bug lama: ``views.js`` menyapu SELURUH ``_newsStore`` tiap render begitu
    ``_newsSeq > 1000``, sehingga kartu lama mati diklik. Kunci perilaku baru:
    tak ada wipe global, store berupa ``Map``, eviksi berbutir setelah insert
    penuh, dan batas penyimpanan > jumlah maksimum kartu satu render (24).
    """

    VIEWS = Path(__file__).resolve().parent.parent / "static" / "js" / "views.js"

    def _source(self) -> str:
        return self.VIEWS.read_text(encoding="utf-8")

    def test_store_is_map_not_object(self):
        src = self._source()
        self.assertIn("const _newsStore = new Map();", src)
        self.assertNotIn("const _newsStore = {};", src)

    def test_no_global_wipe_each_render(self):
        src = self._source()
        self.assertNotIn("for(const k in _newsStore)", src)
        self.assertNotIn("delete _newsStore[k]", src)

    def test_eviction_runs_after_full_batch_insert(self):
        src = self._source()
        self.assertIn("_newsEvict(list.length);", src)
        self.assertIn("_newsStore.set(id, it || {});", src)

    def test_store_cap_not_less_than_max_single_render(self):
        import re

        src = self._source()
        match = re.search(r"const NEWS_STORE_CAP = (\d+);", src)
        self.assertIsNotNone(match, "NEWS_STORE_CAP tidak ditemukan")
        cap = int(match.group(1))
        # Maksimum kartu satu render: 8 (`views.js`) / 15 / 24 (`news.py`).
        self.assertGreaterEqual(cap, 24)

    def test_click_reads_store_via_get(self):
        src = self._source()
        self.assertIn("_newsStore.get(card.getAttribute(\"data-news-id\"))", src)
        self.assertNotIn("_newsStore[card.getAttribute", src)


class TestTrustedProxyHops(unittest.TestCase):
    """W-0022: ProxyFix di-gate `TRUSTED_PROXY_HOPS`; IP klien asli dipulihkan."""

    def setUp(self):
        import os

        self._old = os.environ.get("TRUSTED_PROXY_HOPS")

    def tearDown(self):
        import os

        if self._old is None:
            os.environ.pop("TRUSTED_PROXY_HOPS", None)
        else:
            os.environ["TRUSTED_PROXY_HOPS"] = self._old

    def _hops_for(self, raw):
        import os

        import webapp

        if raw is None:
            os.environ.pop("TRUSTED_PROXY_HOPS", None)
        else:
            os.environ["TRUSTED_PROXY_HOPS"] = raw
        return webapp._trusted_proxy_hops()

    def test_invalid_blank_and_non_positive_fall_back_to_zero(self):
        for raw in ("abc", "", "-1", "0", "0.5", None):
            self.assertEqual(self._hops_for(raw), 0, f"raw={raw!r}")

    def test_value_within_range_is_honored(self):
        self.assertEqual(self._hops_for("1"), 1)
        self.assertEqual(self._hops_for("3"), 3)

    def test_value_above_max_is_clamped(self):
        import webapp

        self.assertEqual(self._hops_for("99"), webapp._TRUSTED_PROXY_HOPS_MAX)

    def test_hops_zero_keeps_remote_addr_and_hops_one_uses_xff(self):
        from werkzeug.test import Client

        import webapp

        captured = []

        def raw_app(environ, start_response):
            captured.append(environ.get("REMOTE_ADDR"))
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b""]

        def call(hops, xff):
            captured.clear()
            client = Client(webapp._apply_proxy_fix(raw_app, hops))
            client.get(
                "/",
                headers={"X-Forwarded-For": xff},
                environ_base={"REMOTE_ADDR": "10.0.0.1"},
            )
            return captured[-1]

        self.assertEqual(call(0, "203.0.113.7"), "10.0.0.1")
        self.assertEqual(call(1, "203.0.113.7"), "203.0.113.7")
        self.assertEqual(
            call(1, "198.51.100.9, 203.0.113.7"), "203.0.113.7"
        )


class TestMaxBodyBytes(unittest.TestCase):
    """W-0022: ukuran body request dibatasi `MAX_CONTENT_LENGTH` (fail-closed)."""

    def setUp(self):
        import os

        import webapp

        self._os = os
        self._webapp = webapp
        self._old_env = os.environ.get("LAUM_MAX_BODY_BYTES")
        # `app.config` level modul: simpan agar tidak bocor ke test lain.
        self._old_cfg = webapp.app.config.get("MAX_CONTENT_LENGTH")

    def tearDown(self):
        if self._old_env is None:
            self._os.environ.pop("LAUM_MAX_BODY_BYTES", None)
        else:
            self._os.environ["LAUM_MAX_BODY_BYTES"] = self._old_env
        if self._old_cfg is None:
            self._webapp.app.config.pop("MAX_CONTENT_LENGTH", None)
        else:
            self._webapp.app.config["MAX_CONTENT_LENGTH"] = self._old_cfg

    def _limit_for(self, raw):
        if raw is None:
            self._os.environ.pop("LAUM_MAX_BODY_BYTES", None)
        else:
            self._os.environ["LAUM_MAX_BODY_BYTES"] = raw
        return self._webapp._max_body_bytes()

    def test_invalid_and_non_positive_fall_back_to_default(self):
        import webapp

        for raw in ("abc", "", "0", "-1", "0.5", None):
            self.assertEqual(self._limit_for(raw), webapp._BODY_BYTES_DEFAULT,
                             f"raw={raw!r}")

    def test_value_is_clamped_to_safe_range(self):
        import webapp

        self.assertEqual(self._limit_for("1024"), webapp._BODY_BYTES_MIN)
        self.assertEqual(self._limit_for("999999999"), webapp._BODY_BYTES_MAX)
        self.assertEqual(self._limit_for("2097152"), 2097152)

    def test_boot_app_has_positive_limit(self):
        import webapp

        limit = webapp.app.config.get("MAX_CONTENT_LENGTH")
        self.assertIsInstance(limit, int)
        self.assertGreater(limit, 0)

    def test_oversize_post_returns_413_json_and_handler_not_run(self):
        from unittest.mock import patch

        webapp = self._webapp
        webapp.app.config["MAX_CONTENT_LENGTH"] = 1024
        client = webapp.app.test_client()
        with patch("routes.screener.state.create_scan_job") as create:
            r = client.post("/api/scan/start", data=b"x" * 5000,
                            content_type="application/json")
            create.assert_not_called()
        self.assertEqual(r.status_code, 413)
        self.assertTrue(r.content_type.startswith("application/json"),
                        r.content_type)
        self.assertIn("error", r.get_json())

    def test_normal_post_handler_still_runs(self):
        from unittest.mock import patch

        webapp = self._webapp
        webapp.app.config["MAX_CONTENT_LENGTH"] = webapp._BODY_BYTES_DEFAULT
        client = webapp.app.test_client()
        with patch("routes.screener.state.create_scan_job", return_value="job1"), \
                patch("routes.screener.threading.Thread"):
            r = client.post("/api/scan/start", json={"list": "lq45"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json().get("job"), "job1")


if __name__ == "__main__":
    unittest.main()
