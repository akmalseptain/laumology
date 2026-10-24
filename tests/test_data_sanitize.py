"""Tes sanitasi konsistensi High/Low di data._normalize (batch-38).

Kasus nyata produksi: BBCA 10 Nov 2025 memiliki High==Open dan Low==Close
plus noise floating-point (~1e-9) dari harga ter-adjust - validate.check_df
menandainya "High/Low tidak konsisten pada 1 bar" (hard error, ok=False)
padahal nilai bar valid. _normalize kini melebarkan High/Low agar selalu
mengapit Open/Close: bar valid tak berubah, bar inkonsisten diperbaiki.

Butuh pandas/numpy (CI). _normalize adalah choke point tunggal semua fetch
(get_ohlcv maupun prefetch) sehingga cache yang ditulis juga sudah bersih.
"""
import unittest

import pandas as pd

import data
import validate


def _raw(rows, dates):
    return pd.DataFrame(rows, index=pd.to_datetime(dates))


class NormalizeSanitizeTest(unittest.TestCase):
    def test_bar_noise_float_diperbaiki(self):
        # Replika persis kasus BBCA 10 Nov 2025: High==Open, Low==Close+1e-9
        raw = _raw(
            [{"Open": 8198.494445266946, "High": 8198.494445266946,
              "Low": 8103.987304687501, "Close": 8103.9873046875,
              "Volume": 0.0}],
            ["2025-11-10"],
        )
        out = data._normalize(raw)
        self.assertEqual(len(out), 1)
        self.assertGreaterEqual(
            float(out["High"].iloc[0]),
            max(float(out["Open"].iloc[0]), float(out["Close"].iloc[0])),
        )
        self.assertLessEqual(
            float(out["Low"].iloc[0]),
            min(float(out["Open"].iloc[0]), float(out["Close"].iloc[0])),
        )
        r = validate.check_df(out)
        self.assertNotIn("High/Low tidak konsisten pada 1 bar", r["errors"])

    def test_bar_valid_tidak_berubah(self):
        raw = _raw(
            [
                {"Open": 100.0, "High": 110.0, "Low": 95.0, "Close": 105.0,
                 "Volume": 1000.0},
                {"Open": 105.0, "High": 107.0, "Low": 98.0, "Close": 99.0,
                 "Volume": 900.0},
            ],
            ["2025-11-10", "2025-11-11"],
        )
        out = data._normalize(raw)
        self.assertEqual(list(out["High"]), [110.0, 107.0])
        self.assertEqual(list(out["Low"]), [95.0, 98.0])

    def test_bar_high_rendah_dilebarkan(self):
        # Sumber mengirim High < max(O,C) (High intraday hilang): dilebarkan
        # konservatif ke max(H, O, C) - bar kini konsisten.
        raw = _raw(
            [{"Open": 100.0, "High": 100.0, "Low": 90.0, "Close": 103.0,
              "Volume": 500.0}],
            ["2025-11-10"],
        )
        out = data._normalize(raw)
        self.assertEqual(float(out["High"].iloc[0]), 103.0)
        self.assertEqual(float(out["Low"].iloc[0]), 90.0)


if __name__ == "__main__":
    unittest.main()
