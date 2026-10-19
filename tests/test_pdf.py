"""Laporan PDF track record - endpoint /track-record.pdf.

Tanpa jaringan: DB sqlite sementara (swap store.DB_PATH) + Flask test
client. Memastikan: 200 + magic %PDF + nama file + tombol unduh di
halaman + DB kosong tetap jujur (laporan kosong, bukan error).
"""
import tempfile
import unittest
from pathlib import Path

import store
import webapp


class TrackRecordPdfTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = store.DB_PATH
        store.DB_PATH = Path(self._tmp.name) / "test.db"
        store.init()
        self.client = webapp.app.test_client()

    def tearDown(self):
        store.DB_PATH = self._old_db
        self._tmp.cleanup()

    def test_pdf_db_kosong_200_dan_magic(self):
        r = self.client.get("/track-record.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.data[:4] == b"%PDF")
        self.assertGreater(len(r.data), 1500)

    def test_pdf_dengan_sinyal(self):
        ok = store.add_signal({
            "ticker": "BBCA", "signal": "BUY", "action": "BUY",
            "score": 82, "confidence": 75, "price": 9500.0,
            "entry": 9450.0, "stop_loss": 9100.0, "tp1": 9900.0,
        }, source="scan")
        self.assertTrue(ok)
        r = self.client.get("/track-record.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data[:4] == b"%PDF")
        self.assertGreater(len(r.data), 1500)

    def test_disposisi_filename(self):
        """Nama file bertanggal (YYYYMMDD-HHMM) supaya unduhan baru
        tidak tertukar dengan salinan lama di perangkat pengguna."""
        import re
        r = self.client.get("/track-record.pdf")
        cd = r.headers.get("Content-Disposition", "")
        self.assertTrue(
            re.search(r"laumology-track-record-\d{8}-\d{4}\.pdf", cd),
            "filename tidak bertanggal: " + cd)

    def test_pdf_memiliki_objek_halaman(self):
        """Regresi: PDF 0-halaman pernah lolos di produksi (resep NumberedCanvas
        rapuh antar versi reportlab; CI & produksi memakai versi berbeda)."""
        import re as _re
        r = self.client.get("/track-record.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_re.search(rb"/Type\s*/Page\b", r.data),
                        "PDF tanpa objek halaman (0 halaman)")
        self.assertGreaterEqual(len(_re.findall(rb"/Type\s*/Page\b", r.data)), 1)

    def test_tombol_unduh_di_halaman(self):
        r = self.client.get("/track-record")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"/track-record.pdf", r.data)


if __name__ == "__main__":
    unittest.main()
