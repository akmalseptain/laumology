"""Tes observabilitas routes/screener: chunk gagal tidak lagi senyap.

CI-only: routes.screener butuh flask & screener (pandas/yfinance).
Chunk yang gagal tetap dilewati (job/stream tetap utuh) - hanya jejak log baru.
Catatan: respons SSE dari test client bersifat lazy - stream WAJIB dikonsumsi
(buffered=True + get_data) di DALAM blok assertLogs/mock agar generator
benar-benar berjalan di sana.
"""
import unittest
from unittest import mock

try:
    from flask import Flask
    import routes
    import routes.screener as rs
    _OK = True
except Exception:
    _OK = False


@unittest.skipUnless(_OK, "flask/routes tidak tersedia (CI-only)")
class ScreenerSilentTest(unittest.TestCase):
    def test_scan_worker_chunk_gagal_warning_job_tetap_done(self):
        updates = []

        def fake_update(job_id, state=None, **kw):
            updates.append(state)

        with mock.patch.object(rs.screener, "resolve_watchlist", return_value=["BBCA", "BBRI"]), \
             mock.patch.object(rs.screener, "screen", side_effect=RuntimeError("boom")), \
             mock.patch.object(rs.state, "scan_cancelled", return_value=False), \
             mock.patch.object(rs.state, "update_scan_job", side_effect=fake_update):
            with self.assertLogs("laumology.routes.screener", level="WARNING") as ctx:
                rs._scan_worker("job-1", {"list": "lq45"})
        self.assertIn("running", updates)
        self.assertIn("done", updates)
        self.assertTrue(any("chunk scan latar 2 saham" in m for m in ctx.output))

    def test_stream_chunk_gagal_warning_stream_tetap_utuh(self):
        app = Flask(__name__)
        routes.register(app)
        app.config["TESTING"] = True
        client = app.test_client()
        with mock.patch.object(rs.screener, "resolve_watchlist", return_value=["BBCA", "BBRI"]), \
             mock.patch.object(rs.screener, "screen", side_effect=RuntimeError("boom")):
            with self.assertLogs("laumology.routes.screener", level="WARNING") as ctx:
                resp = client.get("/api/screen/stream?list=lq45", buffered=True)
                body = resp.get_data(as_text=True)
        self.assertIn("event: done", body)
        self.assertIn("event: progress", body)
        self.assertTrue(any("gagal di stream" in m for m in ctx.output))


if __name__ == "__main__":
    unittest.main()
