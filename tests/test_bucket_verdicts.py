"""Tes vonis × kelompok (store.outcome_bucket_verdicts).

Gabungan atribusi (bucket skor/confidence/grade/sinyal) dengan vonis
sadar-arah. Semua data sintetis via SQLite sementara — tanpa jaringan,
tanpa pandas. Yang dijaga:
- Distribusi vonis dihitung benar per kelompok (dan letak kesalahan hanya
  dari sinyal salah pada kelompok itu).
- Sadar-arah di dalam bucket: SELL/AVOID yang keliru tetap terhitung salah.
- Jujur: kelompok n < min_n tidak dilaporkan; DB kosong n_total=0;
  payload /api/trackrecord memuat bucket_verdicts dari store.
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest

from flask import Flask

import routes
import store


def _insert_signal(conn, ticker, score, conf, grade, signal, action="BELI"):
    cur = conn.execute(
        "INSERT INTO signals(ts,ticker,signal,action,score,confidence,grade,"
        "price,entry,stop_loss,tp1,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2026-09-01 10:00:00", ticker, signal, action, score, conf, grade,
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


class BucketVerdictTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-bucketverdict-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

    def tearDown(self):
        self.conn.close()
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def _seed(self, rows, horizon=5):
        """rows: list of (score, conf, grade, signal, fwd, excess, outcome[, action])."""
        for row in rows:
            score, conf, grade, signal, fwd, excess, outcome = row[:7]
            action = row[7] if len(row) > 7 else "BELI"
            sid = _insert_signal(self.conn, "TST", score, conf, grade, signal, action)
            _insert_outcome(self.conn, sid, horizon, fwd, excess, outcome)
        self.conn.commit()


class TestOutcomeBucketVerdicts(BucketVerdictTestBase):
    def test_db_kosong_jujur(self):
        rep = store.outcome_bucket_verdicts(5)
        self.assertEqual(rep["n_total"], 0)
        self.assertTrue(all(rep["buckets"][d] == [] for d in ("skor", "confidence", "grade", "sinyal")))

    def test_distribusi_vonis_dan_letak_kesalahan_per_bucket(self):
        # skor 80-100: 4 benar nyata + 1 salah (SL duluan, kalah IHSG)
        # skor 60-69: 1 benar nyata + 4 salah (SL duluan + kalah IHSG)
        high = [(85, 80, "A", "BUY", 2.0, 1.0, "TP1")] * 4 + \
               [(85, 80, "A", "BUY", -2.0, -1.0, "SL")]
        low = [(65, 60, "C", "BUY", 2.0, 1.0, "TP1")] + \
              [(65, 60, "C", "BUY", -1.0, -0.5, "SL")] * 4
        self._seed(high + low)
        rep = store.outcome_bucket_verdicts(5, min_n=5)
        skor = {e["bucket"]: e for e in rep["buckets"]["skor"]}
        self.assertEqual(skor["80-100"]["n"], 5)
        self.assertAlmostEqual(skor["80-100"]["verdict_pct"]["benar_nyata"], 80.0)
        self.assertAlmostEqual(skor["80-100"]["verdict_pct"]["salah"], 20.0)
        self.assertEqual(skor["80-100"]["wrong_n"], 1)
        self.assertAlmostEqual(skor["80-100"]["wrong_where_pct"]["sl_duluan"], 100.0)
        self.assertAlmostEqual(skor["80-100"]["wrong_where_pct"]["kalah_dari_ihsg"], 100.0)
        self.assertEqual(skor["60-69"]["n"], 5)
        self.assertAlmostEqual(skor["60-69"]["verdict_pct"]["salah"], 80.0)
        self.assertAlmostEqual(skor["60-69"]["wrong_where_pct"]["sl_duluan"], 100.0)

    def test_sadar_arah_di_dalam_bucket(self):
        # Kelompok skor sama, dua sinyal SELL: harga naik -> salah + naik_padahal_turun.
        self._seed([
            (40, 40, "D", "SELL", 2.0, 1.0, "NONE", "SELL"),
            (40, 40, "D", "SELL", 3.0, 0.5, "NONE", "SELL"),
            (40, 40, "D", "SELL", -2.0, -1.0, "NONE", "SELL"),
            (40, 40, "D", "SELL", -1.0, -0.5, "NONE", "SELL"),
            (40, 40, "D", "SELL", -3.0, -2.0, "NONE", "SELL"),
        ])
        rep = store.outcome_bucket_verdicts(5, min_n=5)
        e = rep["buckets"]["skor"][0]
        self.assertEqual(e["bucket"], "0-59")
        self.assertEqual(e["n"], 5)
        self.assertAlmostEqual(e["verdict_pct"]["salah"], 40.0)
        self.assertAlmostEqual(e["verdict_pct"]["benar_nyata"], 60.0)
        self.assertEqual(e["wrong_n"], 2)
        self.assertAlmostEqual(e["wrong_where_pct"]["naik_padahal_turun"], 100.0)
        self.assertAlmostEqual(e["wrong_where_pct"]["sl_duluan"], 0.0)

    def test_kelompok_kecil_tidak_dilaporkan(self):
        self._seed([(85, 80, "A", "BUY", 2.0, 1.0, "TP1")])  # n=1 < min_n=5
        rep = store.outcome_bucket_verdicts(5, min_n=5)
        self.assertEqual(rep["n_total"], 1)
        self.assertTrue(all(rep["buckets"][d] == [] for d in rep["buckets"]))

    def test_kelompok_benar_semua_tanpa_wrong(self):
        self._seed([(85, 80, "A", "BUY", 2.0, 1.0, "TP1")] * 6)
        rep = store.outcome_bucket_verdicts(5, min_n=5)
        e = rep["buckets"]["skor"][0]
        self.assertEqual(e["wrong_n"], 0)
        self.assertEqual(e["wrong_where_pct"], {})
        self.assertAlmostEqual(e["verdict_pct"]["benar_nyata"], 100.0)

    def test_horizon_terpisah(self):
        self._seed([(85, 80, "A", "BUY", 2.0, 1.0, "TP1")] * 6, horizon=10)
        self.assertEqual(store.outcome_bucket_verdicts(5, min_n=5)["n_total"], 0)
        self.assertEqual(store.outcome_bucket_verdicts(10, min_n=5)["n_total"], 6)


class TestBucketVerdictsApi(BucketVerdictTestBase):
    def setUp(self):
        super().setUp()
        app = Flask(__name__)
        routes.register(app)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_api_trackrecord_memuat_bucket_verdicts(self):
        self._seed([(85, 80, "A", "BUY", 2.0, 1.0, "TP1")] * 4
                   + [(82, 80, "A", "BUY", -1.0, -0.5, "SL")] * 2)
        js = self.client.get("/api/trackrecord").get_json()
        self.assertIn("bucket_verdicts", js)
        bv = js["bucket_verdicts"]
        self.assertEqual(bv["horizon"], 5)
        self.assertEqual(bv["min_n"], 5)
        skor = {e["bucket"]: e for e in bv["buckets"]["skor"]}
        self.assertEqual(skor["80-100"]["n"], 6)
        self.assertAlmostEqual(skor["80-100"]["verdict_pct"]["benar_nyata"], 66.67, delta=0.05)

    def test_api_db_kosong_jujur(self):
        js = self.client.get("/api/trackrecord").get_json()
        self.assertEqual(js["bucket_verdicts"]["n_total"], 0)


if __name__ == "__main__":
    unittest.main()
