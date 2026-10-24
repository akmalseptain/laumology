"""Tes observabilitas payloads: benchmark IHSG di chart gagal tidak lagi senyap.

CI-only: payloads butuh pandas. data/_enriched/analyze diganti fake agar
panggilan ohlc_payload murni lokal tanpa jaringan.
Overlay benchmark hilang tetap jujur (list kosong) - hanya jejak log baru.
"""
import types
import unittest
from unittest import mock

try:
    import pandas as pd
    import payloads
    _OK = True
except Exception:
    _OK = False


def _frame(base=100.0, n=40):
    idx = pd.date_range(end=pd.Timestamp("2026-10-23"), periods=n, freq="D")
    close = [base + i for i in range(n)]
    return pd.DataFrame(
        {"Open": close, "High": [c + 1.0 for c in close], "Low": [c - 1.0 for c in close],
         "Close": close, "Volume": [1000.0] * n},
        index=idx,
    )


@unittest.skipUnless(_OK, "payloads/pandas tidak tersedia (CI-only)")
class PayloadsSilentTest(unittest.TestCase):
    def _fake_a(self, *a, **k):
        ticker = a[1] if len(a) > 1 else "BBCA"
        return types.SimpleNamespace(
            ticker=ticker, price=140.0, change_1d=1.2,
            entry=135.0, stop_loss=130.0, tp1=150.0, tp2=160.0, tp3=170.0,
            vp={"poc": 137.0, "vah": 142.0, "val": 133.0},
            signal="BUY", action="BELI", score=6.5, confidence=70, grade="A",
        )

    def _fake_data(self, jkse_fail):
        def get_ohlcv(sym, *a, **k):
            if sym == "^JKSE":
                if jkse_fail:
                    raise RuntimeError("net down")
                return _frame(base=7000.0)
            return _frame()
        return types.SimpleNamespace(
            get_ohlcv=get_ohlcv,
            get_quote=lambda *a, **k: None,
            apply_live_quote=lambda df, quote, interval="1d": (df, None),
        )

    def _run(self, jkse_fail):
        with mock.patch.object(payloads, "data", self._fake_data(jkse_fail)), \
             mock.patch.object(payloads, "_enriched", lambda *a, **k: _frame()), \
             mock.patch.object(payloads, "analyze", self._fake_a):
            return payloads.ohlc_payload("BBCA", "1d", 30, refresh=False)

    def test_benchmark_gagal_warning_dan_payload_tetap_jujur(self):
        with self.assertLogs("laumology.payloads", level="WARNING") as ctx:
            out = self._run(jkse_fail=True)
        self.assertEqual(out["benchmark"], [])
        self.assertTrue(out["candles"])
        self.assertTrue(any("benchmark" in m and "BBCA" in m for m in ctx.output))

    def test_benchmark_sehat_tanpa_warning(self):
        with self.assertNoLogs("laumology.payloads", level="WARNING"):
            out = self._run(jkse_fail=False)
        self.assertTrue(out["benchmark"])


if __name__ == "__main__":
    unittest.main()
