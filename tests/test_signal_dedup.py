"""Tes dedup sinyal di hulu (store.add_signal) — anti pseudo-replikasi.

Scheduler memindai tiap SCAN_INTERVAL; tanpa dedup per (ticker, signal,
hari), satu keadaan sinyal tercatat puluhan kali per hari dan feedback
loop mengevaluasi salinan duplikat — win rate/vonis jadi bias oleh
"berapa lama sinyal bertahan", bukan kejadian sinyal independen.
Yang dijaga:
- ticker+sinyal sama pada hari sama -> TIDAK dicatat ulang (False);
- sinyal BERUBAH di hari sama -> tetap dicatat (perubahan = informasi);
- sinyal sama pada HARI BERBEDA -> dicatat (observasi baru);
- ticker berbeda tidak saling membatasi; payload tanpa ticker/sinyal
  tidak crash dan tidak dianggap duplikat.
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest

import store


def _payload(ticker="TST", signal="BUY", **kw):
    p = {
        "ticker": ticker, "signal": signal, "action": signal, "score": 75,
        "confidence": 70, "grade": "B", "price": 100.0, "entry": 100.0,
        "stop_loss": 95.0, "tp1": 110.0,
    }
    p.update(kw)
    return p


class SignalDedupTest(unittest.TestCase):
    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-dedup-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

    def tearDown(self):
        self.conn.close()
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def _count(self):
        (n,) = self.conn.execute("SELECT COUNT(*) FROM signals").fetchone()
        return n

    def test_duplikat_hari_sama_tidak_dicatat_ulang(self):
        self.assertTrue(store.add_signal(_payload(), source="scan"))
        self.assertFalse(store.add_signal(_payload(), source="scan"))
        self.assertFalse(store.add_signal(_payload(score=80), source="scan"))
        self.assertEqual(self._count(), 1)

    def test_sinyal_berubah_di_hari_sama_dicatat(self):
        store.add_signal(_payload(signal="BUY"), source="scan")
        self.assertTrue(store.add_signal(_payload(signal="SELL"), source="scan"))
        self.assertEqual(self._count(), 2)

    def test_sinyal_sama_hari_berbeda_dicatat(self):
        # Baris "kemarin" disuntik langsung (bypass _now); add_signal hari
        # ini harus mencatat karena beda hari.
        self.conn.execute(
            "INSERT INTO signals(ts,ticker,signal,action,score,confidence,grade,price,entry,stop_loss,tp1,source)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("2026-01-01 10:00:00", "TST", "BUY", "BUY", 75, 70, "B",
             100.0, 100.0, 95.0, 110.0, "scan"),
        )
        self.conn.commit()
        self.assertTrue(store.add_signal(_payload(), source="scan"))
        self.assertEqual(self._count(), 2)

    def test_ticker_berbeda_bebas(self):
        store.add_signal(_payload(ticker="AAA"), source="scan")
        self.assertTrue(store.add_signal(_payload(ticker="BBB"), source="scan"))
        self.assertEqual(self._count(), 2)

    def test_payload_tanpa_ticker_sinyal_tidak_crash(self):
        self.assertTrue(store.add_signal({"ticker": None, "signal": None}, source="manual"))
        self.assertEqual(self._count(), 1)


class CountSignalsTest(unittest.TestCase):
    """count_signals = COUNT asli, bukan panjang daftar tampilan."""

    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-count-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

    def tearDown(self):
        self.conn.close()
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def test_count_asli_tanpa_batas_tampilan(self):
        for i in range(7):
            self.assertTrue(store.add_signal(_payload(ticker=f"TK{i}"), source="scan"))
        self.assertEqual(store.count_signals(), 7)

    def test_duplikat_tidak_menggelembungkan_count(self):
        store.add_signal(_payload(ticker="AAA"), source="scan")
        store.add_signal(_payload(ticker="AAA"), source="scan")  # dup hari sama -> skip
        self.assertEqual(store.count_signals(), 1)


if __name__ == "__main__":
    unittest.main()
