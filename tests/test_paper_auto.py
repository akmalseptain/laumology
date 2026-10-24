"""Tes paper trading otomatis (batch-34) - murni pencatatan sinyal engine.

Yang dijaga:
- _side_of: SELL -> short; BUY/STRONG BUY/ACCUMULATE -> long; AVOID/HOLD ->
  None (tidak ada posisi - sinyal tidak actionable).
- open_from_signals: hanya sinyal TERBARU per ticker; satu posisi terbuka
  per ticker; sinyal basi (ts <= posisi terakhir) tidak didaur ulang.
- settle_open_positions: bar SETELAH hari sinyal saja (kausal), SL duluan
  bila satu bar (konservatif), arah short dibalik, exit tepat di harga
  TP/SL.
- close_flipped_positions: posisi ditutup bila sinyal TERBARU ticker
  berbalik arah (long -> SELL, short -> BUY/STRONG BUY/ACCUMULATE), di
  harga sinyal pembalik; HOLD/AVOID dan sinyal searah tidak menutup;
  sinyal pembuka tidak menutup posisinya sendiri (harus lebih baru).
- POST /api/paper/sync: pola batch-32 (monkeypatch, tanpa jaringan).

Tanpa jaringan: DB sqlite sementara (swap store.DB_PATH) + OHLC palsu,
pola tests/test_h1_cepat.py. store stdlib murni; paper_auto.data di-patch.
"""
import datetime as _dt
import pathlib
import sqlite3
import tempfile
import unittest

import paper_auto
import store
import webapp


class _FakeSeries:
    """Cukup mirip pandas.Series untuk paper_auto (akses .iloc[i])."""

    def __init__(self, vals):
        self._vals = list(vals)
        self.iloc = self

    def __getitem__(self, i):
        return self._vals[i]


class _FakeDF:
    def __init__(self, days, high, low):
        self.index = list(days)
        self._cols = {"High": _FakeSeries(high), "Low": _FakeSeries(low)}

    def __len__(self):
        return len(self.index)

    def __getitem__(self, key):
        return self._cols[key]


def _future_days(n):
    """Hari kalender SETELAH hari ini (bar sintetis setelah stempel posisi)."""
    base = _dt.date.today()
    return [(base + _dt.timedelta(days=i + 1)).isoformat() for i in range(n)]


class PaperAutoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = store.DB_PATH
        store.DB_PATH = pathlib.Path(self._tmp.name) / "test.db"
        store.init()
        self._OHLC = {}
        self._old_get_ohlcv = paper_auto.data.get_ohlcv
        paper_auto.data.get_ohlcv = self._fake_ohlcv
        self._client = webapp.app.test_client()

    def tearDown(self):
        paper_auto.data.get_ohlcv = self._old_get_ohlcv
        store.DB_PATH = self._old_db
        self._tmp.cleanup()

    def _fake_ohlcv(self, ticker, *args, **kwargs):
        return self._OHLC.get(str(ticker).upper())

    def _seed_signal(self, ticker, signal, price, stop=0.0, tp=0.0, action=""):
        ok = store.add_signal({
            "ticker": ticker, "signal": signal, "action": action,
            "score": 50, "confidence": 50, "grade": "C",
            "price": price, "entry": price, "stop_loss": stop, "tp1": tp,
        }, source="test")
        self.assertTrue(ok)

    def _set_ts(self, ticker, signal, ts):
        """Geser stempel sinyal TERBARU (id maks) ticker+jenis - urutan pasti.

        add_signal memakai resolusi DETIK; beberapa seed dalam detik yang
        sama menghasilkan ts yang SAMA sehingga urutan sinyal vs posisi tidak
        teruji. Ts eksplisit membuat urutan deterministik (kausalitas flip).
        """
        conn = sqlite3.connect(store.DB_PATH)
        try:
            conn.execute(
                "UPDATE signals SET ts=? WHERE id=(SELECT MAX(id) FROM signals"
                " WHERE ticker=? AND signal=?)",
                (ts, ticker, signal),
            )
            conn.commit()
        finally:
            conn.close()

    def test_side_mapping(self):
        self.assertEqual(paper_auto._side_of("SELL"), "SELL")
        self.assertEqual(paper_auto._side_of("BUY"), "BUY")
        self.assertEqual(paper_auto._side_of("STRONG BUY"), "BUY")
        self.assertEqual(paper_auto._side_of("ACCUMULATE"), "BUY")
        self.assertIsNone(paper_auto._side_of("AVOID"))
        self.assertIsNone(paper_auto._side_of("HOLD"))
        self.assertIsNone(paper_auto._side_of(None))

    def test_lots_menukar_nilai_target(self):
        self.assertEqual(paper_auto._lots_for(5000.0), 20)
        self.assertEqual(paper_auto._lots_for(9000.0), 11)
        self.assertEqual(paper_auto._lots_for(200000.0), 1)  # minimal 1 lot
        self.assertEqual(paper_auto._lots_for(0.0), 0)

    def test_buka_dari_sinyal_terbaru_per_ticker(self):
        self._seed_signal("TLKM", "AVOID", 3200.0)  # tidak actionable
        self._seed_signal("BBCA", "SELL", 5100.0, stop=5400.0, tp=4600.0)  # versi lama BBCA
        self._seed_signal("BBCA", "BUY", 5000.0, stop=4500.0, tp=5500.0)  # terbaru BBCA
        self._seed_signal("UNTR", "SELL", 24000.0, stop=25000.0, tp=22000.0)
        self.assertEqual(paper_auto.open_from_signals(), 2)
        rows = {r["ticker"]: r for r in store.paper_rows(status="OPEN")}
        self.assertEqual(set(rows), {"BBCA", "UNTR"})  # TLKM (AVOID) dilewati
        self.assertEqual(rows["BBCA"]["side"], "BUY")  # pakai sinyal TERBARU, bukan SELL lama
        self.assertEqual(rows["BBCA"]["entry"], 5000.0)
        self.assertEqual(rows["BBCA"]["lots"], 20)
        self.assertEqual(rows["BBCA"]["stop"], 4500.0)
        self.assertEqual(rows["BBCA"]["tp"], 5500.0)
        self.assertEqual(rows["UNTR"]["side"], "SELL")

    def test_dedup_satu_posisi_dan_sinyal_basi(self):
        self._seed_signal("BBCA", "BUY", 5000.0, stop=4500.0, tp=5500.0)
        self.assertEqual(paper_auto.open_from_signals(), 1)
        # sync kedua: sinyal sama (ts tidak lebih baru dari posisi) -> tidak menumpuk
        self.assertEqual(paper_auto.open_from_signals(), 0)
        self.assertEqual(len(store.paper_rows(status="OPEN")), 1)

    def test_settle_long_sl_duluan_bila_satu_bar(self):
        pid = store.paper_open("BBCA", "BUY", 5000.0, 20, 4500.0, 5500.0, "test",
                               opened=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self._OHLC["BBCA"] = _FakeDF(days=_future_days(1),
                                     high=[5600.0], low=[4400.0])  # TP & SL sama bar
        self.assertEqual(paper_auto.settle_open_positions(), 1)
        row = [r for r in store.paper_rows() if r["id"] == pid][0]
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["exit"], 4500.0)  # SL duluan (konservatif)
        self.assertEqual(row["pnl"], round((4500.0 - 5000.0) * 20 * 100, 0))
        self.assertIn("SL", row["note"] or "")

    def test_settle_long_tp(self):
        pid = store.paper_open("UNTR", "BUY", 24000.0, 4, 22000.0, 26000.0, "test",
                               opened=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self._OHLC["UNTR"] = _FakeDF(days=_future_days(2),
                                     high=[25500.0, 26100.0], low=[23800.0, 24500.0])
        self.assertEqual(paper_auto.settle_open_positions(), 1)
        row = [r for r in store.paper_rows() if r["id"] == pid][0]
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["exit"], 26000.0)
        self.assertGreater(row["pnl"], 0)
        self.assertIn("TP", row["note"] or "")

    def test_settle_short_sl(self):
        pid = store.paper_open("TLKM", "SELL", 3200.0, 30, 3400.0, 3000.0, "test",
                               opened=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self._OHLC["TLKM"] = _FakeDF(days=_future_days(1),
                                     high=[3450.0], low=[3100.0])  # High >= stop
        self.assertEqual(paper_auto.settle_open_positions(), 1)
        row = [r for r in store.paper_rows() if r["id"] == pid][0]
        self.assertEqual(row["exit"], 3400.0)
        # short rugi bila harga naik: (exit-entry) * lots * 100 * -1
        self.assertEqual(row["pnl"], round((3400.0 - 3200.0) * 30 * 100 * -1.0, 0))
        self.assertLess(row["pnl"], 0)

    def test_settle_bar_hari_sinyal_tidak_ikut(self):
        # bar hari yang SAMA dengan stempel posisi tidak boleh menutup (kausal)
        pid = store.paper_open("BBCA", "BUY", 5000.0, 20, 4500.0, 5500.0, "test",
                               opened=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        today = _dt.date.today().isoformat()
        self._OHLC["BBCA"] = _FakeDF(days=[today], high=[6000.0], low=[4000.0])
        self.assertEqual(paper_auto.settle_open_positions(), 0)
        row = [r for r in store.paper_rows() if r["id"] == pid][0]
        self.assertEqual(row["status"], "OPEN")

    def test_endpoint_sync_tanpa_jaringan(self):
        orig = paper_auto.sync_paper
        calls = []

        def fake_sync(limit=400, target_value=paper_auto.TARGET_VALUE):
            calls.append(limit)
            return {"settled": 3, "opened": 5}

        paper_auto.sync_paper = fake_sync
        try:
            resp = self._client.post("/api/paper/sync")
        finally:
            paper_auto.sync_paper = orig
        self.assertEqual(resp.status_code, 200)
        d = resp.get_json()
        self.assertTrue(d.get("ok"))
        self.assertEqual(d.get("settled"), 3)
        self.assertEqual(d.get("opened"), 5)
        self.assertEqual(calls, [400])


    def test_sync_loop_sampai_mutakhir(self):
        # Sinyal LAMA (3 hari lalu) yang SL-nya sudah tersentuh pada bar
        # setelahnya: satu putaran settle-then-open TIDAK cukup (posisi baru
        # dibuka di putaran 1, baru bisa ditutup di putaran 2) -> loop harus
        # jalan sampai stabil dan hasil akhirnya mutakhir (0 posisi terbuka).
        self._seed_signal("BBCA", "BUY", 5000.0, stop=4500.0, tp=5500.0)
        old = (_dt.date.today() - _dt.timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(store.DB_PATH)
        try:
            conn.execute("UPDATE signals SET ts=? WHERE ticker='BBCA'", (old,))
            conn.commit()
        finally:
            conn.close()
        d1 = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
        self._OHLC["BBCA"] = _FakeDF(days=[d1], high=[5200.0], low=[4400.0])  # SL kena
        res = paper_auto.sync_paper()
        self.assertEqual(res["opened"], 1)
        self.assertEqual(res["settled"], 1)
        self.assertGreaterEqual(res["rounds"], 2)
        self.assertEqual(len(store.paper_rows(status="OPEN")), 0)  # mutakhir
        closed = store.paper_rows(status="CLOSED")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["exit"], 4500.0)

    def test_flip_tutup_long_saat_engine_jadi_sell(self):
        self._seed_signal("BBCA", "BUY", 5000.0, stop=4500.0, tp=5500.0)
        self._set_ts("BBCA", "BUY", "2026-01-01 08:00:00")
        self.assertEqual(paper_auto.open_from_signals(), 1)  # posisi stempel 08:00
        # engine berbalik arah: sinyal SELL lebih baru
        self._seed_signal("BBCA", "SELL", 4900.0, stop=5100.0, tp=4600.0)
        self._set_ts("BBCA", "SELL", "2026-01-01 09:00:00")
        self.assertEqual(paper_auto.close_flipped_positions(), 1)
        rows = store.paper_rows(status="CLOSED")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exit"], 4900.0)  # exit di harga sinyal pembalik
        self.assertEqual(rows[0]["pnl"], round((4900.0 - 5000.0) * 20 * 100, 0))
        self.assertIn("FLIP", rows[0]["note"] or "")

    def test_flip_tutup_short_saat_engine_jadi_accumulate(self):
        self._seed_signal("TLKM", "SELL", 3200.0, stop=3400.0, tp=3000.0)
        self._set_ts("TLKM", "SELL", "2026-01-01 08:00:00")
        self.assertEqual(paper_auto.open_from_signals(), 1)  # 31 lot short
        self._seed_signal("TLKM", "ACCUMULATE", 3350.0, stop=3100.0, tp=3600.0)
        self._set_ts("TLKM", "ACCUMULATE", "2026-01-01 09:00:00")
        self.assertEqual(paper_auto.close_flipped_positions(), 1)
        rows = store.paper_rows(status="CLOSED")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exit"], 3350.0)
        # short rugi bila harga naik: (exit-entry) * lots * 100 * -1
        self.assertEqual(rows[0]["pnl"], round((3350.0 - 3200.0) * 31 * 100 * -1.0, 0))

    def test_flip_hanya_sinyal_baru_yang_membalik(self):
        self._seed_signal("BBCA", "BUY", 5000.0, stop=4500.0, tp=5500.0)
        self._set_ts("BBCA", "BUY", "2026-01-01 08:00:00")
        self.assertEqual(paper_auto.open_from_signals(), 1)
        pid = store.paper_rows(status="OPEN")[0]["id"]
        # (a) HOLD lebih baru: tidak actionable, bukan pembalikan
        self._seed_signal("BBCA", "HOLD", 4950.0)
        self._set_ts("BBCA", "HOLD", "2026-01-01 09:00:00")
        self.assertEqual(paper_auto.close_flipped_positions(), 0)
        # (b) sinyal searah (BUY) lebih baru: bukan pembalikan
        conn = sqlite3.connect(store.DB_PATH)
        try:
            conn.execute("UPDATE signals SET signal='BUY' WHERE ticker='BBCA' AND signal='HOLD'")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(paper_auto.close_flipped_positions(), 0)
        self.assertEqual(len(store.paper_rows(status="OPEN")), 1)
        # (c) SELL lebih baru: pembalikan -> tutup di harga sinyal pembalik
        self._seed_signal("BBCA", "SELL", 4850.0, stop=5050.0, tp=4550.0)
        self._set_ts("BBCA", "SELL", "2026-01-01 10:00:00")
        self.assertEqual(paper_auto.close_flipped_positions(), 1)
        row = [r for r in store.paper_rows() if r["id"] == pid][0]
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["exit"], 4850.0)

    def test_sync_flip_membalik_posisi_paper(self):
        # End-to-end: engine berbalik arah -> posisi lama ditutup (FLIP),
        # posisi baru dibuka SEARAH sinyal baru - paper mengikuti engine.
        self._seed_signal("BBCA", "BUY", 5000.0, stop=4500.0, tp=5500.0)
        self._set_ts("BBCA", "BUY", "2026-01-01 08:00:00")
        res1 = paper_auto.sync_paper()
        self.assertEqual(res1["opened"], 1)
        self.assertEqual(res1["flipped"], 0)
        self._seed_signal("BBCA", "SELL", 4900.0, stop=5100.0, tp=4600.0)
        self._set_ts("BBCA", "SELL", "2026-01-01 09:00:00")
        res2 = paper_auto.sync_paper()
        self.assertEqual(res2["flipped"], 1)
        self.assertEqual(res2["settled"], 0)
        self.assertEqual(res2["opened"], 1)  # posisi baru searah sinyal baru
        opens = store.paper_rows(status="OPEN")
        self.assertEqual(len(opens), 1)
        self.assertEqual(opens[0]["side"], "SELL")
        self.assertEqual(opens[0]["entry"], 4900.0)
        closed = store.paper_rows(status="CLOSED")
        self.assertEqual(len(closed), 1)
        self.assertIn("FLIP", closed[0]["note"] or "")
        self.assertEqual(closed[0]["pnl"], round((4900.0 - 5000.0) * 20 * 100, 0))

    def test_settle_short_tp(self):
        # Celah batch-40: exit TP untuk posisi SHORT belum pernah dites
        # (long TP, long SL, short SL sudah; temuan drill Senin lokal).
        pid = store.paper_open("GOTO", "SELL", 60.0, 16, 64.0, 55.0, "test",
                               opened=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self._OHLC["GOTO"] = _FakeDF(days=_future_days(1),
                                     high=[61.0], low=[54.5])  # Low <= tp, High < stop
        self.assertEqual(paper_auto.settle_open_positions(), 1)
        row = [r for r in store.paper_rows() if r["id"] == pid][0]
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["exit"], 55.0)
        # short untung bila harga turun: (exit-entry) * lots * 100 * -1
        self.assertEqual(row["pnl"], round((55.0 - 60.0) * 16 * 100 * -1.0, 0))
        self.assertGreater(row["pnl"], 0)
        self.assertIn("TP", row["note"] or "")

    def test_settle_batch_banyak_posisi_satu_sync(self):
        # Replika skenario Senin: banyak posisi OPEN, sebagian kena exit
        # dalam SATU pass settle; sisanya tetap OPEN.
        for tk, entry, stop, tp, high, low in [
            ("ADRO", 100.0, 110.0, 85.0, 111.5, 105.0),  # short SL
            ("ASII", 101.0, 111.0, 86.0, 108.0, 86.0),   # short TP
            ("BBRI", 102.0, 112.0, 87.0, 105.0, 99.0),   # tanpa exit
        ]:
            store.paper_open(tk, "SELL", entry, 10, stop, tp, "test",
                             opened=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self._OHLC[tk] = _FakeDF(days=_future_days(1), high=[high], low=[low])
        self.assertEqual(paper_auto.settle_open_positions(), 2)
        rows = {r["ticker"]: r for r in store.paper_rows()}
        self.assertEqual(rows["ADRO"]["status"], "CLOSED")
        self.assertIn("SL", rows["ADRO"]["note"] or "")
        self.assertEqual(rows["ASII"]["status"], "CLOSED")
        self.assertIn("TP", rows["ASII"]["note"] or "")
        self.assertEqual(rows["BBRI"]["status"], "OPEN")

    def test_sync_kedua_idempoten(self):
        # Sync ulang tanpa kejadian baru: semua nol, satu putaran saja -
        # tidak ada settle/flip/open ganda (amankan KPI n_closed).
        self._seed_signal("BBCA", "BUY", 5000.0, stop=4500.0, tp=5500.0)
        self._OHLC["BBCA"] = _FakeDF(days=_future_days(1),
                                     high=[5200.0], low=[4400.0])  # SL kena
        r1 = paper_auto.sync_paper()
        self.assertEqual(r1["opened"], 1)
        self.assertEqual(r1["settled"], 1)
        r2 = paper_auto.sync_paper()
        self.assertEqual(r2, {"settled": 0, "flipped": 0, "opened": 0, "rounds": 1})

    def test_settle_gagal_data_tidak_senyap(self):
        # Observability (batch-40): gagal fetch/baca bar tidak boleh
        # meledakkan sync, posisi dibiarkan OPEN, DAN kegagalan TERCATAT
        # di log - ditemukan dari drill Senin: penelanan exception senyap
        # membuat settle no-op tanpa jejak (tak teraudit).
        pid = store.paper_open("EMTK", "BUY", 100.0, 1, 90.0, 120.0, "test",
                               opened=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        # (a) fetch OHLCV meledak
        def boom(ticker, *args, **kwargs):
            raise RuntimeError("sumber data bermasalah")
        orig = paper_auto.data.get_ohlcv
        paper_auto.data.get_ohlcv = boom
        try:
            with self.assertLogs("laumology.paper_auto", level="WARNING") as lg:
                n = paper_auto.settle_open_positions()
        finally:
            paper_auto.data.get_ohlcv = orig
        self.assertEqual(n, 0)
        row = [r for r in store.paper_rows() if r["id"] == pid][0]
        self.assertEqual(row["status"], "OPEN")
        self.assertTrue(any("EMTK" in str(x) for x in lg.output), lg.output)
        # (b) bar ada tapi bentuk salah (kolom High hilang)
        class _BrokenDF:
            index = _future_days(1)
            def __len__(self):
                return 1
            def __getitem__(self, key):
                raise KeyError(key)
        self._OHLC["EMTK"] = _BrokenDF()
        with self.assertLogs("laumology.paper_auto", level="WARNING") as lg2:
            n2 = paper_auto.settle_open_positions()
        self.assertEqual(n2, 0)
        self.assertTrue(any("gagal membaca bar" in str(x) for x in lg2.output), lg2.output)
        row = [r for r in store.paper_rows() if r["id"] == pid][0]
        self.assertEqual(row["status"], "OPEN")

    def test_purge_endpoint_ci_flask(self):
        # POST /api/paper/purge: 400 tanpa reason, 404 untuk posisi engine,
        # 200 untuk posisi uji (ticker tanpa sinyal) dan hilang dari ledger.
        if type(webapp.app).__name__ != "Flask":
            self.skipTest("butuh Flask asli (CI); stub lokal tidak merutekan")
        pid = store.paper_open("TEST", "BUY", 100.0, 1, 0.0, 0.0, "test audit")
        self.assertTrue(store.add_signal({
            "ticker": "BBCA", "signal": "BUY", "score": 50,
            "confidence": 50, "grade": "C", "price": 5000.0,
        }, source="test"))
        auto_pid = store.paper_open("BBCA", "BUY", 5000.0, 1, 0.0, 0.0, "auto")
        r0 = self._client.post("/api/paper/purge", json={"id": pid})
        self.assertEqual(r0.status_code, 400)  # reason wajib
        r1 = self._client.post("/api/paper/purge",
                               json={"id": auto_pid, "reason": "bersih-bersih"})
        self.assertEqual(r1.status_code, 404)  # ticker punya sinyal engine
        r2 = self._client.post("/api/paper/purge",
                               json={"id": pid, "reason": "bersih-bersih"})
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.get_json().get("ok"))
        self.assertEqual([r for r in store.paper_rows() if r["id"] == pid], [])
        self.assertEqual(
            [r for r in store.paper_rows() if r["id"] == auto_pid][0]["status"], "OPEN"
        )


if __name__ == "__main__":
    unittest.main()
