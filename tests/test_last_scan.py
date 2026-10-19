"""Tes last_scan — alat diagnosis "scheduler jalan atau tidak".

Semua data sintetis via SQLite sementara — tanpa jaringan, tanpa pandas.
Yang dijaga:
- Jujur: DB kosong → last_scan() = None (belum pernah ada scan).
- Benar: last_scan() mengembalikan scan TERAKHIR (id terbesar), bukan
  yang pertama; summary track record mengekspos "last_scan" apa adanya
  (None bila belum ada scan).
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest

import store


class LastScanTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-lscan-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

    def tearDown(self):
        self.conn.close()
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()


class TestLastScan(LastScanTestBase):
    def test_db_kosong_jujur(self):
        self.assertIsNone(store.last_scan())

    def test_scan_terakhir_yang_dikembalikan(self):
        store.add_scan("LQ45", 10, 2, note="lama")
        store.add_scan("LQ45", 12, 3, note="baru")
        row = store.last_scan()
        self.assertIsNotNone(row)
        self.assertEqual(row["note"], "baru")
        self.assertEqual(row["n"], 12)
        self.assertEqual(row["buys"], 3)
        self.assertEqual(row["universe"], "LQ45")

    def test_summary_mengekspos_last_scan(self):
        from routes import trackrecord
        store.add_scan("LQ45", 7, 1, note="x")
        s = trackrecord.summary()
        self.assertIsNotNone(s["last_scan"])
        self.assertEqual(s["last_scan"]["note"], "x")

    def test_summary_db_kosong_last_scan_none(self):
        from routes import trackrecord
        s = trackrecord.summary()
        self.assertIsNone(s["last_scan"])


if __name__ == "__main__":
    unittest.main()
