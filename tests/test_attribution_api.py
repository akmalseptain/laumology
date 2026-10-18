"""Tes endpoint /api/attribution dan /api/verdicts (JSON bukti win rate).

Tanpa jaringan & tanpa pandas: DB SQLite sementara berisi sinyal + hasil
sintetis. Yang dijaga: payload murni dari feedback loop (tanpa proyeksi),
parameter di-clamp, parameter non-angka ditolak 400, DB kosong jujur (n=0),
dan vonis tetap sadar-arah lewat endpoint.
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


class AttributionApiTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-attrapi-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        app = Flask(__name__)
        routes.register(app)
        app.config["TESTING"] = True
        self.client = app.test_client()
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


class TestAttributionApi(AttributionApiTestBase):
    def test_payload_dari_store_dengan_bucket_benar(self):
        # 6 sinyal skor 80-100: 4 naik (TP1), 2 turun (SL) -> win rate 66.67%
        self._seed([(85, 80, "A", "STRONG BUY", 2.0, 1.0, "TP1")] * 4
                   + [(82, 80, "A", "STRONG BUY", -1.0, -2.0, "SL")] * 2)
        resp = self.client.get("/api/attribution?horizon=5&min_n=1")
        self.assertEqual(resp.status_code, 200)
        js = resp.get_json()
        self.assertEqual(js["horizon"], 5)
        self.assertEqual(js["min_n"], 1)
        skor = [e for e in js["buckets"]["skor"] if e["bucket"] == "80-100"]
        self.assertEqual(len(skor), 1)
        self.assertEqual(skor[0]["n"], 6)
        self.assertAlmostEqual(skor[0]["win_rate"], 66.67, delta=0.05)

    def test_min_n_menyembunyikan_kelompok_kecil(self):
        # 1 sinyal di bucket 80-100, min_n=5 -> kelompok tidak dilaporkan
        self._seed([(85, 80, "A", "STRONG BUY", 2.0, 1.0, "TP1")])
        js = self.client.get("/api/attribution?horizon=5&min_n=5").get_json()
        self.assertEqual(js["buckets"]["skor"], [])
        self.assertEqual(js["n_total"], 1)

    def test_param_di_clamp(self):
        js = self.client.get("/api/attribution?horizon=9999&min_n=0").get_json()
        self.assertEqual(js["horizon"], 60)
        self.assertEqual(js["min_n"], 1)

    def test_param_non_angka_400(self):
        resp = self.client.get("/api/attribution?horizon=abc")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_db_kosong_jujur(self):
        js = self.client.get("/api/attribution").get_json()
        self.assertEqual(js["n_total"], 0)
        self.assertEqual(js["buckets"],
                         {"skor": [], "confidence": [], "grade": [], "sinyal": []})


class TestVerdictsApi(AttributionApiTestBase):
    def test_verdict_sadar_arah(self):
        # BELI & naik & excess positif -> benar_nyata;
        # SELL & harga naik -> salah (naik padahal sinyal menurunkan)
        sid1 = _insert_signal(self.conn, "A", 85, 80, "A", "STRONG BUY")
        _insert_outcome(self.conn, sid1, 5, 2.0, 1.0, "TP1")
        sid2 = _insert_signal(self.conn, "B", 40, 40, "D", "SELL", action="SELL")
        _insert_outcome(self.conn, sid2, 5, 3.0, 0.5, "NONE")
        self.conn.commit()
        js = self.client.get("/api/verdicts?horizon=5&limit=10").get_json()
        self.assertEqual(js["horizon"], 5)
        self.assertEqual(js["n"], 2)
        self.assertAlmostEqual(js["verdict_pct"]["benar_nyata"], 50.0, delta=0.05)
        self.assertAlmostEqual(js["verdict_pct"]["salah"], 50.0, delta=0.05)
        self.assertAlmostEqual(js["wrong_where_pct"].get("naik_padahal_turun", 0),
                                100.0, delta=0.05)

    def test_limit_diterima_db_kosong(self):
        js = self.client.get("/api/verdicts?horizon=5&limit=99999").get_json()
        self.assertEqual(js["n"], 0)

    def test_param_non_angka_400(self):
        resp = self.client.get("/api/verdicts?limit=x")
        self.assertEqual(resp.status_code, 400)

    def test_db_kosong_jujur(self):
        js = self.client.get("/api/verdicts").get_json()
        self.assertEqual(js["n"], 0)
        self.assertEqual(js["verdict_pct"], {})
        self.assertEqual(js["recent"], [])


class TestTrackRecordCount(AttributionApiTestBase):
    def test_n_signals_count_asli_bukan_cap_tampilan(self):
        # 205 sinyal > limit tampilan 200 -> n_signals HARUS 205 (bukan 200).
        for i in range(205):
            _insert_signal(self.conn, f"TK{i:03d}", 85, 80, "A", "STRONG BUY")
        self.conn.commit()
        js = self.client.get("/api/trackrecord").get_json()
        self.assertEqual(js["n_signals"], 205)


if __name__ == "__main__":
    unittest.main()
