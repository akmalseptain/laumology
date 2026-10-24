"""Tes paper trading otomatis (batch-34) - murni pencatatan sinyal engine.

Yang dijaga:
- _side_of: SELL -> short; BUY/STRONG BUY/ACCUMULATE -> long; AVOID/HOLD ->
  None (tidak ada posisi - sinyal tidak actionable).
- open_from_signals: hanya sinyal TERBARU per ticker; satu posisi terbuka
  per ticker; sinyal basi (ts <= posisi terakhir) tidak didaur ulang.
- settle_open_positions: bar SETELAH hari sinyal saja (kausal), SL duluan
  bila satu bar (konservatif), arah short dibalik, exit tepat di harga
  TP/SL.
- POST /api/paper/sync: pola batch-32 (monkeypatch, tanpa jaringan).

Tanpa jaringan: DB sqlite sementara (swap store.DB_PATH) + OHLC palsu,
pola tests/test_h1_cepat.py. store stdlib murni; paper_auto.data di-patch.
"""
import datetime as _dt
import pathlib
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


if __name__ == "__main__":
    unittest.main()
