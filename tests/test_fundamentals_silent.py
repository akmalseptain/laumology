"""Tes observabilitas fundamentals: arsip snap gagal disimpan tidak senyap.

CI-only: fundamentals butuh yfinance & pandas (via data).
save_fund_snap gagal -> payload tetap utuh TANPA snap_*, kini dengan jejak
log baru: arsip fundamental yang berhenti bertumbuh harus terlihat
(pola batch-39: persistensi tidak boleh senyap).
"""
import sys
import types
import unittest
from unittest import mock

try:
    import fundamentals as fund_mod
    _OK = True
except Exception:
    _OK = False


# Konsisten secara internal: PER = harga/EPS = 250/50 = 5.0 == trailingPE,
# agar cek kejujuran PER (harga/EPS) tidak menimpa nilai laporan.
_INFO = {
    "longName": "PT Uji Sehat",
    "trailingPE": 5.0,
    "priceToBook": 1.2,
    "returnOnEquity": 0.1,
    "trailingEps": 50.0,
    "currentPrice": 250.0,
}


def _fake_yf():
    def ticker(yt):
        return types.SimpleNamespace(
            info=dict(_INFO),
            get_info=lambda: dict(_INFO),
            quarterly_income_stmt=None, income_stmt=None,
            quarterly_balance_sheet=None, balance_sheet=None,
        )
    return types.SimpleNamespace(Ticker=ticker)


def _fake_store(raise_save):
    def save_fund_snap(ticker, payload):
        if raise_save:
            raise RuntimeError("db terkunci")
        return {"days": 10, "first": "2026-10-01", "last": "2026-10-24"}
    return types.SimpleNamespace(
        save_fund_snap=save_fund_snap,
        fund_snap_history=lambda ticker: [],
    )


@unittest.skipUnless(_OK, "fundamentals/yfinance tidak tersedia (CI-only)")
class FundamentalsSilentTest(unittest.TestCase):
    def test_snap_gagal_warning_payload_tanpa_snap(self):
        with mock.patch.object(fund_mod, "yf", _fake_yf()), \
             mock.patch.dict(sys.modules, {"store": _fake_store(True)}):
            with self.assertLogs("laumology.fundamentals", level="WARNING") as ctx:
                out = fund_mod.get_fundamentals("SNPF1")
        self.assertEqual(out["ticker"], "SNPF1")
        self.assertEqual(out["pe"], 5.0)
        self.assertTrue(out["available"])
        self.assertNotIn("snap_days", out)
        self.assertNotIn("snap_first", out)
        self.assertNotIn("snap_history", out)
        self.assertEqual(len(ctx.output), 1)
        self.assertIn("SNPF1", ctx.output[0])
        self.assertIn("db terkunci", "\n".join(ctx.output))

    def test_snap_sehat_tanpa_warning_payload_lengkap(self):
        with mock.patch.object(fund_mod, "yf", _fake_yf()), \
             mock.patch.dict(sys.modules, {"store": _fake_store(False)}):
            with self.assertNoLogs("laumology.fundamentals", level="WARNING"):
                out = fund_mod.get_fundamentals("SNPF2")
        self.assertEqual(out["ticker"], "SNPF2")
        self.assertEqual(out["snap_days"], 10)
        self.assertEqual(out["snap_first"], "2026-10-01")
        self.assertEqual(out["snap_last"], "2026-10-24")
        self.assertEqual(out["snap_history"], [])
        self.assertTrue(out["available"])


if __name__ == "__main__":
    unittest.main()
