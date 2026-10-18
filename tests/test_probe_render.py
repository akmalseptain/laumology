"""Probe: render /track-record dengan sinyal TANPA outcomes."""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest


class ProbeRenderTest(unittest.TestCase):
    def setUp(self):
        import store

        self._store = store
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-probe-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

        import webapp

        self.client = webapp.app.test_client()

    def tearDown(self):
        self.conn.close()
        self._store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def test_render_status(self):
        for score in (85, 90, 65, 40, 72, 55):
            self.conn.execute(
                "INSERT INTO signals(ts,ticker,signal,action,score,confidence,grade,"
                "price,entry,stop_loss,tp1,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("2026-09-01 10:00:00", "TST", "BUY", "BELI", score, 80, "A",
                 100.0, 100.0, 95.0, 110.0, "test"),
            )
        self.conn.commit()
        resp = self.client.get("/track-record")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[-2000:])


if __name__ == "__main__":
    unittest.main()
