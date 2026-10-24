"""Tes pembersih posisi paper uji (batch-37): purge HANYA untuk posisi
yang ticker-nya tidak punya sinyal engine - posisi otomatis adalah jejak
KPI track record dan tidak boleh terhapus. Route terdaftar di
state.PROTECTED (proteksi API key) dan skema endpoint.

Tanpa jaringan: DB sqlite sementara (swap store.DB_PATH), pola
tests/test_paper_auto.py.
"""
import pathlib
import tempfile
import unittest

import state
import store


class PaperPurgeStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = store.DB_PATH
        store.DB_PATH = pathlib.Path(self._tmp.name) / "test.db"
        store.init()

    def tearDown(self):
        store.DB_PATH = self._old_db
        self._tmp.cleanup()

    def test_purge_hapus_posisi_uji_tanpa_sinyal(self):
        pid = store.paper_open("TEST", "BUY", 100.0, 1, 0.0, 0.0, "test audit")
        self.assertTrue(store.paper_purge(pid))
        self.assertEqual([r for r in store.paper_rows() if r["id"] == pid], [])

    def test_purge_tolak_ticker_dengan_sinyal_engine(self):
        pid = store.paper_open("BBCA", "BUY", 5000.0, 1, 0.0, 0.0, "auto: sinyal BUY")
        self.assertTrue(store.add_signal({
            "ticker": "BBCA", "signal": "BUY", "score": 50,
            "confidence": 50, "grade": "C", "price": 5000.0,
        }, source="test"))
        self.assertFalse(store.paper_purge(pid))  # jejak KPI tidak boleh dihapus
        self.assertEqual(
            [r for r in store.paper_rows() if r["id"] == pid][0]["status"], "OPEN"
        )

    def test_purge_id_tidak_ada(self):
        self.assertFalse(store.paper_purge(999999))


class PaperPurgeProtectionTest(unittest.TestCase):
    def test_purge_dilindungi_api_key(self):
        # pembersih ledger adalah operasi destruktif: harus dalam PROTECTED
        self.assertIn("/api/paper/purge", state.PROTECTED)


if __name__ == "__main__":
    unittest.main()
