"""Tes stempel waktu DB eksplisit UTC (gmtime).

Sebelumnya stempel waktu memakai zona waktu SERVER (lokal). Di Render TZ=UTC
jadi aman, tapi bila env TZ diubah suatu saat, hari dedup sinyal dan ambang
usia pending diam-diam bergeser -> data campur dua zona. Semua stempel
sekarang eksplisit UTC; tes ini mengunci perilaku itu.
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

import store


def _fixed(day_offset: int = 0) -> time.struct_time:
    # 2026-10-19 03:00:00 UTC (+ day_offset hari)
    return time.struct_time((2026, 10, 19 + day_offset, 3, 0, 0, 0, 0, 0))


class UtcStampsTest(unittest.TestCase):
    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-utc-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

    def tearDown(self):
        self.conn.close()
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def test_now_pakai_gmtime(self):
        with mock.patch.object(store.time, "gmtime", return_value=_fixed()):
            self.assertEqual(store._now(), "2026-10-19 03:00:00")

    def test_dedup_hari_ikut_kalender_utc(self):
        payload = {"ticker": "AAA", "signal": "BUY", "score": 80, "confidence": 70,
                   "grade": "A", "price": 1000.0, "entry": 1000.0,
                   "stop_loss": 950.0, "tp1": 1080.0}
        with mock.patch.object(store.time, "gmtime", return_value=_fixed()):
            self.assertTrue(store.add_signal(payload, source="scan"))
            # hari UTC sama: duplikat -> skip
            self.assertFalse(store.add_signal(payload, source="scan"))
        with mock.patch.object(store.time, "gmtime", return_value=_fixed(1)):
            # hari UTC berikutnya: observasi BARU
            self.assertTrue(store.add_signal(payload, source="scan"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
