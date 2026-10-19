"""Tes alur scheduler.run_once end-to-end (jalur nyata pencatatan sinyal).

Tanpa jaringan: screener/data/signals.analyze/notify di-mock; DB SQLite
temporer (pola sama test_signal_dedup). Yang dijaga:
- Dedup hulu bekerja lewat jalur run_once NYATA: scan ulang di hari kalender
  sama tidak menggandakan baris sinyal, dan alert hanya dikirim untuk sinyal
  BELI baru (transisi), bukan tiap scan.
- Alert best-effort: satu alert yang error tidak memutus sisa alert; sinyal
  tetap tercatat penuh.
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

import scheduler as sched
import store


def _analyze_fn(signal="BUY", score=80):
    def _analyze(df, t):
        return SimpleNamespace(
            ticker=t, signal=signal, action="BELI", score=score,
            confidence=70, grade="A", price=1000.0, entry=1000.0,
            stop_loss=950.0, tp1=1080.0,
        )
    return _analyze


class SchedulerFlowTest(unittest.TestCase):
    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-sched-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)
        self.alerts = []
        self._restore = []
        self._patch(sched.screener, "resolve_watchlist", lambda universe: ["AAA", "BBB"])
        self._patch(sched.data, "prefetch", lambda tickers: 0)
        self._patch(sched.data, "get_ohlcv", lambda t: list(range(120)))
        self._patch(sched, "analyze", _analyze_fn("BUY"))
        self._patch(sched.notify, "signal_alert", self.alerts.append)

    def tearDown(self):
        for obj, name, orig in reversed(self._restore):
            setattr(obj, name, orig)
        self.conn.close()
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def _patch(self, obj, name, value):
        self._restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def _count(self, sql="SELECT COUNT(*) FROM signals", args=()):
        return self.conn.execute(sql, args).fetchone()[0]

    def test_scan_ulang_tidak_menggandakan_baris_dan_alert(self):
        n1 = sched.run_once("lq45")
        n2 = sched.run_once("lq45")
        # 2 ticker, sinyal sama, hari kalender sama -> tetap 2 baris (dedup hulu).
        self.assertEqual(self._count(), 2)
        # Alert hanya untuk sinyal BELI baru (transisi), bukan tiap scan.
        self.assertEqual(len(self.alerts), 2)
        self.assertEqual(n1, 2)
        self.assertEqual(n2, 0)

    def test_perubahan_sinyal_tercatat_sebagai_observasi_baru(self):
        sched.run_once("lq45")
        self._patch(sched, "analyze", _analyze_fn("SELL"))
        sched.run_once("lq45")
        # BUY (2) + SELL (2): sinyal BERUBAH = observasi baru, dedup tidak memblokir.
        self.assertEqual(self._count(), 4)
        # SELL bukan sinyal BELI -> tidak ada alert baru.
        self.assertEqual(len(self.alerts), 2)

    def test_alert_error_tidak_memutus_loop(self):
        calls = []

        def flaky(row):
            calls.append(row["ticker"])
            if len(calls) == 1:
                raise RuntimeError("webhook mati")

        self._patch(sched.notify, "signal_alert", flaky)
        # Tidak boleh melempar: satu alert gagal, ticker kedua tetap dicoba.
        sched.run_once("lq45")
        self.assertEqual(calls, ["AAA", "BBB"])
        # Sinyal tetap tercatat penuh walau alert bermasalah.
        self.assertEqual(self._count(), 2)

    def test_scan_tercatat_di_riwayat_scan(self):
        sched.run_once("lq45")
        self.assertEqual(self._count("SELECT COUNT(*) FROM scans"), 1)


if __name__ == "__main__":
    unittest.main()
