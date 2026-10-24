"""Tes observabilitas risk: saham gagal masuk korelasi tidak lagi senyap.

CI-only: risk butuh numpy/pandas. data.get_ohlcv diganti fake.
Matriks hasil tetap jujur (ticker gagal tidak ikut) - hanya jejak log baru.
"""
import types
import unittest
from unittest import mock

try:
    import pandas as pd
    import risk
    _OK = True
except Exception:
    _OK = False


def _frame():
    return pd.DataFrame({"Close": [100.0, 101.0, 99.5, 102.0, 103.0]})

@unittest.skipUnless(_OK, "risk/pandas tidak tersedia (CI-only)")
class RiskSilentTest(unittest.TestCase):
    def _fake_data(self):
        def get_ohlcv(t, *_a, **_k):
            if t == "TLKM":
                raise RuntimeError("no data")
            return _frame()
        return types.SimpleNamespace(get_ohlcv=get_ohlcv)

    def test_korelasi_satu_saham_gagal_warning_dan_dilewati(self):
        with mock.patch.object(risk, "data", self._fake_data()):
            with self.assertLogs("laumology.risk", level="WARNING") as ctx:
                res = risk.correlation(["BBCA", "TLKM", "BBRI"])
        self.assertTrue(any("TLKM" in m and "korelasi" in m for m in ctx.output))
        self.assertIn("BBCA", res["tickers"])
        self.assertIn("BBRI", res["tickers"])
        self.assertNotIn("TLKM", res["tickers"])

    def test_korelasi_sehat_tanpa_warning(self):
        with mock.patch.object(risk, "data", self._fake_data()):
            with self.assertNoLogs("laumology.risk", level="WARNING"):
                res = risk.correlation(["BBCA", "BBRI", "MEDC"])
        self.assertEqual(sorted(res["tickers"]), ["BBCA", "BBRI", "MEDC"])


if __name__ == "__main__":
    unittest.main()
