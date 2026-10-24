"""Tes observabilitas routes/research: ringkasan degradasi tidak lagi senyap.

CI-only: routes.research butuh flask & modul data (pandas/yfinance).
/api/summary saat ihsg/sinyal/scan gagal tetap membalas payload jujur kosong
TANPA memutus endpoint - hanya jejak log baru.
"""
import unittest
from unittest import mock

try:
    from flask import Flask
    import routes
    import routes.research as research_mod
    _OK = True
except Exception:
    _OK = False


@unittest.skipUnless(_OK, "flask/routes tidak tersedia (CI-only)")
class ResearchSilentTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        routes.register(app)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_summary_tiga_sumber_gagal_tiga_warning_payload_tetap(self):
        with mock.patch.object(research_mod.market, "ihsg", side_effect=RuntimeError("net")), \
             mock.patch.object(research_mod.store, "recent_signals", side_effect=RuntimeError("db")), \
             mock.patch.object(research_mod.store, "recent_scans", side_effect=RuntimeError("db")):
            with self.assertLogs("laumology.routes.research", level="WARNING") as ctx:
                resp = self.client.get("/api/summary")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["ihsg"], {})
        self.assertEqual(body["signals_today"], 0)
        self.assertEqual(body["latest_signals"], [])
        self.assertEqual(body["scans"], [])
        self.assertEqual(len(ctx.output), 3)

    def test_summary_sehat_tanpa_warning(self):
        with mock.patch.object(research_mod.market, "ihsg", return_value={"close": 7000.0}), \
             mock.patch.object(research_mod.store, "recent_signals", return_value=[]), \
             mock.patch.object(research_mod.store, "recent_scans", return_value=[]):
            with self.assertNoLogs("laumology.routes.research", level="WARNING"):
                resp = self.client.get("/api/summary")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["ihsg"], {"close": 7000.0})
        self.assertEqual(body["signals_today"], 0)


if __name__ == "__main__":
    unittest.main()
