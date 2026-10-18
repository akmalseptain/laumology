"""Tes atribusi win rate per kelompok (store.outcomes_by_bucket).

Semua data sintetis via SQLite sementara — tanpa jaringan, tanpa pandas.
Yang dijaga:
- Jujur: kelompok dengan n < min_n TIDAK dilaporkan (noise bukan bukti);
  DB kosong melaporkan n_total=0 apa adanya.
- Benar: win rate/TP1/SL dihitung dari return/outcome yang benar-benar
  tercatat di signal_outcomes, dikelompokkan per skor/confidence/grade/sinyal.
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest

import store


def _insert_signal(conn, ticker, score, conf, grade, signal):
    cur = conn.execute(
        "INSERT INTO signals(ts,ticker,signal,action,score,confidence,grade,"
        "price,entry,stop_loss,tp1,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2026-09-01 10:00:00", ticker, signal, "BELI", score, conf, grade,
         100.0, 100.0, 95.0, 110.0, "test"),
    )
    return cur.lastrowid


def _insert_outcome(conn, signal_id, horizon, fwd, excess, outcome):
    conn.execute(
        "INSERT INTO signal_outcomes(signal_id,horizon,evaluated_at,n_bars,fwd_return_pct,"
        "bench_fwd_pct,excess_pct,tp1_hit,sl_hit,outcome) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (signal_id, horizon, "2026-10-01 10:00:00", horizon, fwd,
         None if excess is None else 0.5, excess,
         1 if outcome == "TP1" else 0, 1 if outcome == "SL" else 0, outcome),
    )


class AttributionTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-attr-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

    def tearDown(self):
        self.conn.close()
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def _seed(self, rows, horizon=5):
        """rows: list of (score, conf, grade, signal, fwd, excess, outcome)."""
        for (score, conf, grade, signal, fwd, excess, outcome) in rows:
            sid = _insert_signal(self.conn, "TST", score, conf, grade, signal)
            _insert_outcome(self.conn, sid, horizon, fwd, excess, outcome)
        self.conn.commit()


class TestOutcomesByBucket(AttributionTestBase):
    def test_db_kosong_jujur(self):
        rep = store.outcomes_by_bucket(5)
        self.assertEqual(rep["n_total"], 0)
        self.assertEqual(rep["buckets"]["skor"], [])

    def test_kelompok_kecil_tidak_dilaporkan(self):
        self._seed([(85, 70, "A", "STRONG BUY", 1.0, 0.5, "TP1")])  # cuma 1 sampel
        rep = store.outcomes_by_bucket(5, min_n=5)
        self.assertEqual(rep["n_total"], 1)
        for dim, entries in rep["buckets"].items():
            self.assertEqual(entries, [], f"{dim} tidak boleh melaporkan n=1")

    def test_bucket_skor_dan_win_rate(self):
        # skor 80-100: 4 menang 1 kalah; skor 60-69: 1 menang 4 kalah
        rows = [(85, 70, "A", "BUY", 1.0, 0.5, "TP1")] * 4 + \
               [(85, 70, "A", "BUY", -1.0, -0.5, "SL")] + \
               [(65, 60, "C", "BUY", 2.0, 1.0, "TP1")] + \
               [(65, 60, "C", "BUY", -1.0, -0.5, "SL")] * 4
        self._seed(rows)
        rep = store.outcomes_by_bucket(5, min_n=5)
        skor = {e["bucket"]: e for e in rep["buckets"]["skor"]}
        self.assertIn("80-100", skor)
        self.assertIn("60-69", skor)
        self.assertEqual(skor["80-100"]["n"], 5)
        self.assertAlmostEqual(skor["80-100"]["win_rate"], 80.0)
        self.assertEqual(skor["60-69"]["n"], 5)
        self.assertAlmostEqual(skor["60-69"]["win_rate"], 20.0)
        self.assertAlmostEqual(skor["80-100"]["tp1_rate"], 80.0)
        self.assertAlmostEqual(skor["80-100"]["sl_rate"], 20.0)

    def test_dimensi_lain_terisi(self):
        rows = [(75, 65, "B", "BUY", 1.0, 0.5, "TP1")] * 6
        self._seed(rows)
        rep = store.outcomes_by_bucket(5, min_n=5)
        self.assertTrue(all(rep["buckets"][d] for d in ("skor", "confidence", "grade", "sinyal")))
        self.assertEqual({e["bucket"] for e in rep["buckets"]["confidence"]}, {"60-74"})
        self.assertEqual({e["bucket"] for e in rep["buckets"]["grade"]}, {"B"})
        self.assertEqual({e["bucket"] for e in rep["buckets"]["sinyal"]}, {"BUY"})

    def test_excess_none_dijaga(self):
        rows = [(85, 70, "A", "BUY", 1.0, None, "NONE")] * 6
        self._seed(rows)
        rep = store.outcomes_by_bucket(5, min_n=5)
        e = rep["buckets"]["skor"][0]
        self.assertIsNone(e["avg_excess_pct"])
        self.assertAlmostEqual(e["win_rate"], 100.0)

    def test_horizon_terpisah(self):
        self._seed([(85, 70, "A", "BUY", 1.0, 0.5, "TP1")] * 6, horizon=10)
        rep5 = store.outcomes_by_bucket(5, min_n=5)
        rep10 = store.outcomes_by_bucket(10, min_n=5)
        self.assertEqual(rep5["n_total"], 0)
        self.assertEqual(rep10["n_total"], 6)


if __name__ == "__main__":
    unittest.main()
