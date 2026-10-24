"""Tes gerbang IHSG transparan (batch-33): tidak mengubah sinyal, hanya
memperjelas ALASAN analisa supaya mudah dibaca.

Yang dijaga:
- _apply_regime_gate: BUY/STRONG BUY + IHSG downtrend -> HOLD (perilaku lama),
  dan sekarang mengembalikan sinyal asli yang tertahan (transparansi).
- _recovery_flag: pemulihan awal = belum uptrend, harga > MA20, MA20 naik.
- market_recovery() membaca cache hasil market_regime() (tanpa fetch baru).
- Analysis memuat regime_gate/market_recovery (default jujur: kosong/False).

Tanpa jaringan: cache dipasang langsung; tearDown mengembalikan default.
"""
import time
import unittest

import signals
from signals import Analysis, _apply_regime_gate, _recovery_flag, market_recovery


class RegimeGateTest(unittest.TestCase):
    def tearDown(self):
        signals._MKT_CACHE.update(ts=0.0, regime="unknown", recovery=False)

    def test_buy_ditahan_saat_downtrend_dan_sinyal_asli_tercatat(self):
        sig, act, blocked = _apply_regime_gate("BUY", "BELI SEKARANG", "downtrend")
        self.assertEqual((sig, act, blocked), ("HOLD", "TAHAN (IHSG downtrend)", "BUY"))
        sig, act, blocked = _apply_regime_gate("STRONG BUY", "BELI SEKARANG / BREAKOUT", "downtrend")
        self.assertEqual((sig, act, blocked), ("HOLD", "TAHAN (IHSG downtrend)", "STRONG BUY"))

    def test_sinyal_tak_berubah_di_luar_kondisi_gate(self):
        for regime in ("uptrend", "ranging", "unknown"):
            sig, act, blocked = _apply_regime_gate("BUY", "BELI SEKARANG", regime)
            self.assertEqual((sig, act, blocked), ("BUY", "BELI SEKARANG", ""))
        sig, act, blocked = _apply_regime_gate("AVOID", "HINDARI / TUNGGU", "downtrend")
        self.assertEqual((sig, act, blocked), ("AVOID", "HINDARI / TUNGGU", ""))
        sig, act, blocked = _apply_regime_gate("SELL", "REDUCE / JUAL", "downtrend")
        self.assertEqual((sig, act, blocked), ("SELL", "REDUCE / JUAL", ""))

    def test_recovery_flag_hanya_benar_saat_ma20_naik_dan_harga_di_atasnya(self):
        self.assertTrue(_recovery_flag("downtrend", 5500.0, 5400.0, 5350.0))
        self.assertTrue(_recovery_flag("ranging", 5500.0, 5400.0, 5350.0))
        self.assertFalse(_recovery_flag("uptrend", 5500.0, 5400.0, 5350.0))
        self.assertFalse(_recovery_flag("downtrend", 5300.0, 5400.0, 5350.0))
        self.assertFalse(_recovery_flag("downtrend", 5500.0, 5400.0, 5450.0))

    def test_market_recovery_baca_cache_tanpa_fetch(self):
        signals._MKT_CACHE.update(ts=time.time(), regime="downtrend", recovery=True)
        self.assertTrue(market_recovery())
        signals._MKT_CACHE.update(ts=time.time(), regime="downtrend", recovery=False)
        self.assertFalse(market_recovery())

    def test_analysis_field_transparansi_default_jujur(self):
        fields = Analysis.__dataclass_fields__
        self.assertIn("regime_gate", fields)
        self.assertIn("market_recovery", fields)
        self.assertEqual(fields["regime_gate"].default, "")
        self.assertIs(fields["market_recovery"].default, False)


if __name__ == "__main__":
    unittest.main()
