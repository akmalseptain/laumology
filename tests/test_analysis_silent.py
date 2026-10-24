"""Tes observabilitas routes/analysis: degradasi reliability/oos tidak senyap.

CI-only: routes.analysis butuh flask & modul data (pandas/yfinance).
/api/accuracy mode tunggal saat reliability/oos gagal dihitung tetap
membalas payload jujur (reliability/oos = None) tanpa 502 - hanya jejak
log baru (pola batch-49).
"""
import unittest
from unittest import mock

try:
    import pandas as pd
    from flask import Flask
    import routes
    import routes.analysis as analysis_mod
    _OK = True
except Exception:
    _OK = False


def _frame(n=10):
    idx = pd.date_range(end=pd.Timestamp("2026-10-23"), periods=n, freq="D")
    close = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {"Open": close, "High": [c + 1.0 for c in close], "Low": [c - 1.0 for c in close],
         "Close": close, "Volume": [1000.0] * n},
        index=idx,
    )


@unittest.skipUnless(_OK, "flask/pandas/routes tidak tersedia (CI-only)")
class AnalysisSilentTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        routes.register(app)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_accuracy_reliability_dan_oos_gagal_dua_warning_payload_jujur(self):
        with mock.patch.object(analysis_mod.data, "get_ohlcv", return_value=_frame()), \
             mock.patch.object(analysis_mod.validation, "add_indicators",
                               side_effect=lambda df: df), \
             mock.patch.object(analysis_mod.validation, "analyze_accuracy",
                               return_value={"swing": "naik"}), \
             mock.patch.object(analysis_mod.validation, "accuracy_by_horizon",
                               side_effect=RuntimeError("backtest meledak")), \
             mock.patch.object(analysis_mod.validation, "candidate_out_of_sample",
                               side_effect=RuntimeError("kfold kurang data")):
            with self.assertLogs("laumology.routes.analysis", level="WARNING") as ctx:
                resp = self.client.get("/api/accuracy?ticker=BBCA")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["ticker"], "BBCA")
        self.assertEqual(body["swing"], "naik")
        self.assertIsNone(body["reliability"])
        self.assertIsNone(body["oos"])
        self.assertEqual(len(ctx.output), 2)
        joined = "\n".join(ctx.output)
        self.assertIn("BBCA", joined)
        self.assertIn("reliability", joined)
        self.assertIn("out-of-sample", joined)
        self.assertIn("backtest meledak", joined)

    def test_accuracy_sehat_tanpa_warning(self):
        with mock.patch.object(analysis_mod.data, "get_ohlcv", return_value=_frame()), \
             mock.patch.object(analysis_mod.validation, "add_indicators",
                               side_effect=lambda df: df), \
             mock.patch.object(analysis_mod.validation, "analyze_accuracy",
                               return_value={"swing": "naik"}), \
             mock.patch.object(analysis_mod.validation, "accuracy_by_horizon",
                               return_value={"rows": [{"reliability": "OK"}]}), \
             mock.patch.object(analysis_mod.validation, "candidate_out_of_sample",
                               return_value={"auc": 0.61}):
            with self.assertNoLogs("laumology.routes.analysis", level="WARNING"):
                resp = self.client.get("/api/accuracy?ticker=BBCA")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["reliability"], "OK")
        self.assertEqual(body["oos"], {"auc": 0.61})


if __name__ == "__main__":
    unittest.main()
