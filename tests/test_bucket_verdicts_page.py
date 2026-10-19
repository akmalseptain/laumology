"""Tes halaman /track-record — seksi diagnosa per kelompok (bucket × vonis).

Me-render halaman NYATA via webapp.app (pola TestTrackRecordSeo) dengan DB
sintetis sementara (swap store.DB_PATH) — tanpa jaringan, tanpa pandas.
Yang dijaga:
- Seksi "Diagnosa per kelompok" muncul di HTML dan memuat bucket skor
  beserta distribusi vonis dan letak kesalahan.
- Letak kesalahan hanya berasal dari sinyal salah pada kelompok itu.
- DB kosong → empty state jujur, tanpa angka fabrikasi.
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest


class TrackRecordBucketPageTest(unittest.TestCase):
    def setUp(self):
        import store

        self._store = store
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-bvpage-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

        import webapp

        self.client = webapp.app.test_client()

    def tearDown(self):
        self.conn.close()
        self._store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def _seed(self, rows, horizon=5):
        """rows: list of (score, fwd, excess, outcome)."""
        for score, fwd, excess, outcome in rows:
            cur = self.conn.execute(
                "INSERT INTO signals(ts,ticker,signal,action,score,confidence,grade,"
                "price,entry,stop_loss,tp1,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("2026-09-01 10:00:00", "TST", "BUY", "BELI", score, 80, "A",
                 100.0, 100.0, 95.0, 110.0, "test"),
            )
            self.conn.execute(
                "INSERT INTO signal_outcomes(signal_id,horizon,evaluated_at,n_bars,fwd_return_pct,"
                "bench_fwd_pct,excess_pct,tp1_hit,sl_hit,outcome) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (cur.lastrowid, horizon, "2026-10-01 10:00:00", horizon, fwd,
                 0.5, excess, 1 if outcome == "TP1" else 0,
                 1 if outcome == "SL" else 0, outcome),
            )
        self.conn.commit()

    def test_halaman_memuat_seksi_diagnosa_kelompok(self):
        self._seed([(85, 2.0, 1.0, "TP1")] * 4 + [(85, -2.0, -1.0, "SL")] * 2)
        html = self.client.get("/track-record").get_data(as_text=True)
        self.assertIn("Diagnosa per kelompok", html)
        self.assertIn("<strong>80-100</strong>", html)
        # Distribusi vonis: 4/6 benar nyata = 66.7%, 2/6 salah = 33.3%.
        self.assertIn("66.7%", html)
        self.assertIn("33.3%", html)
        # Letak kesalahan dari 2 sinyal salah (SL duluan, kalah IHSG).
        self.assertIn("SL duluan", html)
        self.assertIn("kalah dari IHSG", html)

    def test_kelompok_benar_semua_tampil_tanpa_letak_salah(self):
        self._seed([(90, 2.0, 1.0, "TP1")] * 6)
        html = self.client.get("/track-record").get_data(as_text=True)
        self.assertIn("<strong>80-100</strong>", html)
        self.assertIn("100.0%", html)
        # Tidak ada sinyal salah -> tidak boleh ada "SL duluan" di seksi ini.
        self.assertNotIn("SL duluan", html)

    def test_render_dengan_data_tidak_500(self):
        """Regresi batch-15: loop sinyal + paper dengan data NYATA tidak boleh 500.

        Bug: ekspresi badge 'X|upper.startswith(\'SELL\')' meledak saat loop
        dijalankan — halaman ini sebelumnya selalu dirender dengan DB kosong
        di CI sehingga loop tak pernah tereksekusi.
        """
        self._seed([(85, 2.0, 1.0, "TP1")] * 4 + [(85, -2.0, -1.0, "SL")] * 2)
        self.conn.execute(
            "INSERT INTO signals(ts,ticker,signal,action,score,confidence,grade,"
            "price,entry,stop_loss,tp1,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("2026-09-01 10:00:00", "TSTS", "SELL", "SELL", 40, 40, "D",
             100.0, 100.0, 95.0, 110.0, "test"),
        )
        self.conn.execute(
            "INSERT INTO paper(ticker,side,entry,lots,stop,tp,opened,closed,exit,pnl,status,note)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("TST", "SELL", 100.0, 1, 95.0, 110.0, "2026-09-01 10:00:00",
             "2026-09-05 10:00:00", 90.0, 100000.0, "CLOSED", "test"),
        )
        self.conn.execute(
            "INSERT INTO paper(ticker,side,entry,lots,stop,tp,opened,status,note)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            ("TST", "BUY", 100.0, 1, 95.0, 110.0, "2026-09-01 10:00:00", "OPEN", "test"),
        )
        self.conn.commit()
        resp = self.client.get("/track-record")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[-1500:])
        html = resp.get_data(as_text=True)
        self.assertIn("b-sell", html)
        self.assertIn("TSTS", html)

    def test_db_kosong_empty_state_jujur(self):
        html = self.client.get("/track-record").get_data(as_text=True)
        self.assertIn("Diagnosa per kelompok", html)
        self.assertIn("Belum ada hasil evaluasi untuk didiagnosa", html)
        self.assertNotIn("<strong>80-100</strong>", html)


if __name__ == "__main__":
    unittest.main()
