"""Batas jendela scan scheduler (SCAN_WINDOW) — kunci hasil audit batch-11.

webapp.in_market_window murni (deterministik dari argumen): mode 'market'
= Senin-Jumat 08:45-16:20 WIB (UTC+7) inklusif, Sabtu/Minggu idle;
mode '24h'/'all'/'always' = selalu aktif. Skor 0-100 tidak diubah.
"""
import datetime as dt
import unittest

import webapp


def _utc(tahun, bulan, hari, jam, menit):
    return dt.datetime(tahun, bulan, hari, jam, menit, tzinfo=dt.timezone.utc)


class InMarketWindowTest(unittest.TestCase):
    def test_batas_buka_dan_tutup_wib(self):
        # Senin 19 Okt 2026. 01:44 UTC = 08:44 WIB -> belum buka.
        self.assertFalse(webapp.in_market_window(_utc(2026, 10, 19, 1, 44)))
        # 01:45 UTC = 08:45 WIB -> batas bawah inklusif.
        self.assertTrue(webapp.in_market_window(_utc(2026, 10, 19, 1, 45)))
        # 09:20 UTC = 16:20 WIB -> batas atas inklusif.
        self.assertTrue(webapp.in_market_window(_utc(2026, 10, 19, 9, 20)))
        # 09:21 UTC = 16:21 WIB -> sudah tutup.
        self.assertFalse(webapp.in_market_window(_utc(2026, 10, 19, 9, 21)))

    def test_weekend_idle(self):
        # Sabtu 17 Okt & Minggu 18 Okt 2026, di tengah jam bursa WIB.
        self.assertFalse(webapp.in_market_window(_utc(2026, 10, 17, 1, 45)))
        self.assertFalse(webapp.in_market_window(_utc(2026, 10, 18, 5, 0)))

    def test_luar_jam_bursa_hari_kerja(self):
        # Senin 07:00 WIB (00:00 UTC) dan 22:00 WIB (15:00 UTC) -> idle.
        self.assertFalse(webapp.in_market_window(_utc(2026, 10, 19, 0, 0)))
        self.assertFalse(webapp.in_market_window(_utc(2026, 10, 19, 15, 0)))

    def test_mode_24h_selalu_aktif(self):
        self.assertTrue(webapp.in_market_window(_utc(2026, 10, 18, 20, 0), "24h"))
        self.assertTrue(webapp.in_market_window(_utc(2026, 10, 17, 1, 45), "always"))
        self.assertTrue(webapp.in_market_window(_utc(2026, 10, 18, 23, 59), "all"))


if __name__ == "__main__":
    unittest.main()
