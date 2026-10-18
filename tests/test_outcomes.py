"""Tes loop umpan balik akurasi (outcomes.py + store.signal_outcomes).

Semua data sintetis; tidak ada jaringan, tidak ada kredensial. Yang dijaga:
- Kausal: hanya bar SETELAH hari sinyal yang dievaluasi (_window_after).
- Jujur: sinyal muda tetap "pending" (tidak dievaluasi spekulatif), ringkasan
  kosong melaporkan n=0 apa adanya (tanpa win rate yang difabrikasi).
- Final: evaluasi pertama bersifat DO NOTHING (tidak pernah ditimpa ulang).
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import time
import unittest

import pandas as pd

import outcomes
import store


def _ts_days_ago(days: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days * 86400))


def _mk_ohlcv(closes, highs=None, lows=None):
    n = len(closes)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="D")
    highs = list(highs) if highs is not None else list(closes)
    lows = list(lows) if lows is not None else list(closes)
    return pd.DataFrame(
        {"Open": list(closes), "High": highs, "Low": lows, "Close": list(closes),
         "Volume": [1_000_000] * n},
        index=idx,
    )


def _insert_signal(conn, ts, ticker, price, sl, tp1):
    cur = conn.execute(
        "INSERT INTO signals(ts,ticker,signal,action,score,confidence,grade,"
        "price,entry,stop_loss,tp1,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, ticker, "BUY", "BELI", 80, 70, "A", price, price, sl, tp1, "test"),
    )
    return cur.lastrowid


class TestEvaluateWindow(unittest.TestCase):
    def test_none(self):
        w = _mk_ohlcv([100, 101, 102, 103, 104])
        r = outcomes.evaluate_window(100.0, w, tp1=106.0, sl=94.0, horizon=5)
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["outcome"], "NONE")
        self.assertAlmostEqual(r["fwd_return_pct"], 4.0)

    def test_tp1_first(self):
        w = _mk_ohlcv([100, 101, 102, 103, 104])
        r = outcomes.evaluate_window(100.0, w, tp1=103.0, sl=94.0, horizon=5)
        self.assertEqual(r["outcome"], "TP1")
        self.assertTrue(r["tp1_hit"])
        self.assertFalse(r["sl_hit"])

    def test_sl(self):
        w = _mk_ohlcv([100, 101, 102, 103, 104], lows=[99, 99, 94, 94, 94])
        r = outcomes.evaluate_window(100.0, w, tp1=106.0, sl=95.0, horizon=5)
        self.assertEqual(r["outcome"], "SL")

    def test_same_bar_conservative_sl(self):
        w = _mk_ohlcv([100], highs=[110.0], lows=[90.0])
        r = outcomes.evaluate_window(100.0, w, tp1=105.0, sl=95.0, horizon=1)
        self.assertEqual(r["outcome"], "SL")  # TP1 & SL di bar sama -> SL (konservatif)

    def test_pending_when_window_short(self):
        w = _mk_ohlcv([100, 101, 102])
        r = outcomes.evaluate_window(100.0, w, None, None, horizon=5)
        self.assertEqual(r["status"], "pending")

    def test_pending_when_no_price(self):
        w = _mk_ohlcv([100, 101, 102])
        self.assertEqual(outcomes.evaluate_window(0.0, w, None, None)["status"], "pending")


class TestWindowAfter(unittest.TestCase):
    def test_excludes_signal_day(self):
        df = _mk_ohlcv([100] * 12)
        signal_day = str(df.index[2].date())
        win = outcomes._window_after(df, signal_day, 5)
        self.assertEqual(len(win), 5)
        self.assertEqual(str(win.index[0].date()), str((df.index[2] + pd.Timedelta(days=1)).date()))

    def test_none_when_no_future_bars(self):
        df = _mk_ohlcv([100] * 5)
        last_day = str(df.index[-1].date())
        self.assertIsNone(outcomes._window_after(df, last_day, 5))


class TestEndToEnd(unittest.TestCase):
    """Uji penuh: DB sementara + fetch_ohlcv/bench_df disuntik (tanpa jaringan)."""

    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-outcomes-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()

    def tearDown(self):
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def _conn(self):
        return sqlite3.connect(store.DB_PATH)

    def _insert(self, days_ago, ticker, price, sl, tp1):
        with self._conn() as c:
            return _insert_signal(c, _ts_days_ago(days_ago), ticker, price, sl, tp1)

    def test_evaluate_and_summary(self):
        self._insert(10, "TSTA", 100.0, 95.0, 110.0)
        # Sinyal 10 hari lalu; bar pertama SETELAH hari sinyal = 9 hari lalu
        # (posisi 12 dari 22, karena index harian berakhir hari ini).
        closes = [100.0] * 22
        highs = [100.0] * 22
        highs[12] = 112.0
        closes[12] = 105.0
        df = _mk_ohlcv(closes, highs=highs)
        bench = _mk_ohlcv([1000.0] * 22)
        r = outcomes.evaluate_signals(horizon=1, lookback_days=90, limit=10,
                                      fetch_ohlcv=lambda t: df, bench_df=bench)
        self.assertEqual(r["eligible"], 1)
        self.assertEqual(r["evaluated"], 1)
        s = store.outcomes_summary(horizon=1)
        self.assertEqual(s["n"], 1)
        self.assertEqual(s["n_tp1"], 1)
        self.assertEqual(s["n_sl"], 0)
        self.assertAlmostEqual(s["win_rate"], 100.0)
        self.assertAlmostEqual(s["avg_fwd_pct"], 5.0)
        self.assertAlmostEqual(s["avg_excess_pct"], 5.0)  # benchmark datar -> excess = fwd

    def test_first_evaluation_is_final(self):
        self._insert(10, "TSTB", 100.0, 95.0, 110.0)
        df_up = _mk_ohlcv([100.0] * 22, highs=[100.0] * 12 + [112.0] + [100.0] * 9)
        df_down = _mk_ohlcv([100.0] * 22, lows=[100.0] * 12 + [90.0] + [100.0] * 9)
        outcomes.evaluate_signals(horizon=1, lookback_days=90, limit=10,
                                   fetch_ohlcv=lambda t: df_up, bench_df=df_up)
        # Evaluasi kedua dengan data berbeda TIDAK boleh menimpa hasil pertama.
        r2 = outcomes.evaluate_signals(horizon=1, lookback_days=90, limit=10,
                                       fetch_ohlcv=lambda t: df_down, bench_df=df_down)
        self.assertEqual(r2["evaluated"], 0)
        s = store.outcomes_summary(horizon=1)
        self.assertEqual(s["n"], 1)
        self.assertEqual(s["n_tp1"], 1)

    def test_young_signal_not_eligible(self):
        # Sinyal 3 hari lalu: untuk horizon=5 butuh usia >= 12 hari -> pending, jujur.
        self._insert(3, "TSTM", 100.0, 95.0, 105.0)
        r = outcomes.evaluate_signals(horizon=5, lookback_days=90, limit=10,
                                      fetch_ohlcv=lambda t: _mk_ohlcv([100.0] * 30),
                                      bench_df=_mk_ohlcv([1000.0] * 30))
        self.assertEqual(r["eligible"], 0)
        self.assertEqual(r["evaluated"], 0)
        self.assertEqual(store.outcomes_summary(horizon=5)["n"], 0)

    def test_summary_empty_is_honest(self):
        s = store.outcomes_summary(horizon=5)
        self.assertEqual(s["n"], 0)
        self.assertNotIn("win_rate", s)  # jangan fabrikasi win rate saat belum ada data


if __name__ == "__main__":
    unittest.main()
