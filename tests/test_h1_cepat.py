"""Tes horizon H+1 (puls cepat arah) pada feedback loop track record.

H+1 bersifat ADITIF: patokan resmi tetap H+5 (outcomes). Yang dijaga:
- /api/trackrecord memuat outcomes_h1 (horizon=1) TERPISAH dari outcomes
  (H+5) - tidak saling mencampur.
- Halaman /track-record memuat seksi H+1 (dengan data maupun kosong jujur).
- scheduler mengevaluasi horizon 1 via EVAL_HORIZONS.
- DB kosong: outcomes_h1 = {"horizon": 1, "n": 0} - tidak mengarang.

Tanpa jaringan: DB sqlite sementara (swap store.DB_PATH) + Flask test
client, pola yang sama dengan tests/test_pdf.py.
"""
import pathlib
import sqlite3
import tempfile
import unittest

import store
import webapp


def _insert_outcome(conn, signal_id: int, horizon: int, fwd: float) -> None:
    conn.execute(
        "INSERT INTO signal_outcomes(signal_id,horizon,evaluated_at,n_bars,fwd_return_pct,"
        "bench_fwd_pct,excess_pct,tp1_hit,sl_hit,outcome) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (signal_id, horizon, "2026-10-01 10:00:00", horizon, fwd,
         0.0, 0.0, 0, 0, "NONE"),
    )


class H1CepatTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = store.DB_PATH
        store.DB_PATH = pathlib.Path(self._tmp.name) / "test.db"
        store.init()
        self.client = webapp.app.test_client()

    def tearDown(self):
        store.DB_PATH = self._old_db
        self._tmp.cleanup()

    def _seed(self) -> None:
        """1 sinyal dengan hasil H+1 (naik) dan H+5 (turun) - harus terpisah."""
        ok = store.add_signal({
            "ticker": "BBCA", "signal": "BUY", "action": "BELI",
            "score": 82, "confidence": 75, "price": 9500.0,
            "entry": 9450.0, "stop_loss": 9100.0, "tp1": 9900.0,
        }, source="test")
        self.assertTrue(ok)
        sid = store.recent_signals(limit=1)[0]["id"]
        conn = sqlite3.connect(store.DB_PATH)
        try:
            _insert_outcome(conn, sid, 1, 2.0)   # H+1: naik -> benar
            _insert_outcome(conn, sid, 5, -1.0)  # H+5: turun -> salah
            conn.commit()
        finally:
            conn.close()

    def test_api_outcomes_h1_terpisah_dari_patokan(self):
        self._seed()
        js = self.client.get("/api/trackrecord").get_json()
        # puls cepat H+1
        self.assertEqual(js["outcomes_h1"]["horizon"], 1)
        self.assertEqual(js["outcomes_h1"]["n"], 1)
        self.assertEqual(js["outcomes_h1"]["win_rate"], 100.0)
        # patokan resmi H+5 tidak tersentuh
        self.assertEqual(js["outcomes"]["horizon"], 5)
        self.assertEqual(js["outcomes"]["n"], 1)
        self.assertEqual(js["outcomes"]["win_rate"], 0.0)

    def test_h1_kosong_jujur(self):
        js = self.client.get("/api/trackrecord").get_json()
        self.assertEqual(js["outcomes_h1"], {"horizon": 1, "n": 0})

    def test_halaman_memuat_seksi_h1(self):
        page = self.client.get("/track-record").get_data()
        self.assertIn(b"H+1", page)

    def test_scheduler_horizon_h1_termasuk(self):
        import scheduler
        self.assertIn(1, scheduler.EVAL_HORIZONS)
        self.assertIn(5, scheduler.EVAL_HORIZONS)  # patokan resmi tetap

    def test_evaluate_endpoint_tanpa_sinyal_baru(self):
        """POST /api/outcomes/evaluate menjalankan evaluasi feedback loop
        untuk semua EVAL_HORIZONS TANPA menulis sinyal baru (aman di akhir
        pekan: beda dengan scan, tidak ada duplikasi stempel hari ini)."""
        import outcomes
        calls = []
        orig = outcomes.evaluate_signals

        def _fake(horizon=5, limit=500, **kw):
            calls.append((horizon, limit))
            return {"horizon": horizon, "eligible": 0, "evaluated": 0,
                    "still_pending": 0, "failed": 0}

        outcomes.evaluate_signals = _fake
        try:
            r = self.client.post("/api/outcomes/evaluate?limit=123")
        finally:
            outcomes.evaluate_signals = orig
        self.assertEqual(r.status_code, 200)
        js = r.get_json()
        self.assertTrue(js["ok"])
        self.assertEqual(sorted(h for h, _ in calls), [1, 5, 10])
        self.assertTrue(all(l == 123 for _, l in calls))
        self.assertEqual(store.count_signals(), 0)  # tidak menulis sinyal baru


if __name__ == "__main__":
    unittest.main()
