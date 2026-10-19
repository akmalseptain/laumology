"""/health memuat status litestream dari marker render-start.sh.

Tanpa jaringan: DB sqlite sementara (swap store.DB_PATH). Marker
ditulis bootstrap Render; tes ini memastikan field terbaca & terisi.
"""
import tempfile
import unittest
from pathlib import Path

import store
import webapp


class HealthLitestreamTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = store.DB_PATH
        store.DB_PATH = Path(self._tmp.name) / "test.db"
        store.init()
        self.client = webapp.app.test_client()

    def tearDown(self):
        store.DB_PATH = self._old_db
        self._tmp.cleanup()

    def _marker(self):
        return store.DB_PATH.parent / "litestream.status"

    def test_health_memuat_field_litestream(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("litestream", data)
        self.assertTrue(isinstance(data["litestream"], str) and data["litestream"])

    def test_marker_aktif_dibaca(self):
        self._marker().write_text("aktif\n")
        r = self.client.get("/health")
        self.assertEqual(r.get_json()["litestream"], "aktif")

    def test_marker_nonaktif_binary_dibaca(self):
        self._marker().write_text("nonaktif:binary\n")
        r = self.client.get("/health")
        self.assertEqual(r.get_json()["litestream"], "nonaktif:binary")

    def test_tanpa_marker_jujur(self):
        r = self.client.get("/health")
        self.assertEqual(r.get_json()["litestream"], "nonaktif:tanpa-marker")


if __name__ == "__main__":
    unittest.main()
