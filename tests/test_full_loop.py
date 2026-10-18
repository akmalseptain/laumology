"""Tes integrasi hulu->hilir: sinyal lewat jalur NYATA add_signal ->
evaluate_signals -> verdicts -> attribution.

Semua sintetis, tanpa jaringan (fetcher OHLCV di-suntik, benchmark disuntik).
Yang dijaga:
- Skema DB kompatibel ujung-ke-ujung: baris yang ditulis add_signal
  benar-benar bisa dievaluasi, divonis, dan diatribusi — jalur yang sama
  yang dipakai scheduler Senin nanti.
- Sinyal muda tetap pending (tidak dievaluasi spekulatif).
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

import outcomes
import store


def _mk_ohlcv(closes):
    import pandas as pd

    n = len(closes)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": list(closes),
            "High": list(closes),
            "Low": list(closes),
            "Close": list(closes),
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


class FullLoopTest(unittest.TestCase):
    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-loop-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

    def tearDown(self):
        self.conn.close()
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def _payload(self, ticker):
        return {
            "ticker": ticker, "signal": "BUY", "action": "BELI", "score": 80,
            "confidence": 70, "grade": "A", "price": 1000.0, "entry": 1000.0,
            "stop_loss": 950.0, "tp1": 1100.0,
        }

    def test_loop_hulu_ke_hilir(self):
        # HULU: dua sinyal 13 hari lalu lewat jalur add_signal NYATA
        # (stempel _now dipatch ke 2026-10-05 UTC; usia > horizon*2+2=12 hari).
        lama = time.struct_time((2026, 10, 5, 3, 0, 0, 0, 0, 0))
        with mock.patch.object(store.time, "gmtime", return_value=lama):
            self.assertTrue(store.add_signal(self._payload("TST1"), source="scan"))
            self.assertTrue(store.add_signal(self._payload("TST2"), source="scan"))
        # Sinyal muda (hari ini) — tidak boleh dievaluasi spekulatif.
        self.assertTrue(store.add_signal(self._payload("TST3"), source="scan"))

        df = _mk_ohlcv([1000.0] * 40)
        r = outcomes.evaluate_signals(
            horizon=5, lookback_days=90, limit=10,
            fetch_ohlcv=lambda t: df, bench_df=df,
        )
        self.assertEqual(r["evaluated"], 2)

        # HILIR: ringkasan outcomes terisi untuk 2 sinyal tua saja.
        s = store.outcomes_summary(horizon=5)
        self.assertEqual(s["n"], 2)

        # Vonis sadar-arah: harga datar & IHSG datar -> 0% fwd -> salah 100%.
        rep = store.outcome_verdicts(5)
        self.assertEqual(rep["n"], 2)
        self.assertAlmostEqual(rep["verdict_pct"]["salah"], 100.0, delta=0.05)

        # Atribusi per kelompok: dua sinyal skor 80 masuk bucket "80-100".
        rep_b = store.outcomes_by_bucket(5, min_n=1)
        self.assertEqual(rep_b["n_total"], 2)
        self.assertEqual(len(rep_b["buckets"]["skor"]), 1)
        self.assertEqual(rep_b["buckets"]["skor"][0]["bucket"], "80-100")

    def test_sinyal_muda_tetap_pending(self):
        # Sinyal hari ini: tidak masuk pending_signals untuk horizon=5
        # (butuh usia >= 12 hari) -> tidak dievaluasi, ringkasan tetap jujur.
        self.assertTrue(store.add_signal(self._payload("TSTM"), source="scan"))
        df = _mk_ohlcv([1000.0] * 40)
        r = outcomes.evaluate_signals(
            horizon=5, lookback_days=90, limit=10,
            fetch_ohlcv=lambda t: df, bench_df=df,
        )
        self.assertEqual(r["evaluated"], 0)
        self.assertEqual(store.outcomes_summary(horizon=5)["n"], 0)


if __name__ == "__main__":
    unittest.main()
