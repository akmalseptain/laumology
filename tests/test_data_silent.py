"""Tes observabilitas lapisan data / hulu (batch-44) - degradasi tidak senyap.

TEMUAN UTAMA: get_ohlcv saat fetch gagal dan cache basi tersedia DULU
melakukan fallback SENYAP - sinyal bisa dihitung dari data berhari-hari
tua tanpa jejak bila upstream down. Batch-44 menambahkan warning
laumology.data di semua jalur fallback data: cache basi dilayani, cache
rusak dihapus, chunk prefetch gagal, normalisasi prefetch gagal, get_many
gagal, dan quote gagal dari semua sumber. Perilaku fallback TIDAK berubah.

Butuh pandas/yfinance (CI). Repro lokal: py_compile saja (jalur lama).
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

import pandas as pd

import data


def _csv_df(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-10-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": [10.0] * n, "High": [11.0] * n, "Low": [9.0] * n,
         "Close": [10.5] * n, "Volume": [1000.0] * n},
        index=idx)


class DataSilentTest(unittest.TestCase):
    def setUp(self):
        self._restore = []
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-data-silent-")
        data._quote_cache.clear()

    def tearDown(self):
        for obj, name, orig in reversed(self._restore):
            setattr(obj, name, orig)
        data._quote_cache.clear()
        self.tmp.cleanup()

    def _patch(self, obj, name, value):
        self._restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    @staticmethod
    def _boom(*args, **kwargs):
        raise RuntimeError("hulu mati")

    def test_fetch_gagal_fallback_cache_basi_tidak_senyap(self):
        # Cache basi tetap DILAYANI (best-effort by design), tapi warning
        # tercatat dengan umur cache + bar terakhirnya.
        p = pathlib.Path(self.tmp.name) / "AAA_1y_1d.csv"
        _csv_df().to_csv(p)
        self._patch(data, "_cache_path", lambda *a, **k: p)
        self._patch(data.yf, "download", self._boom)
        with self.assertLogs("laumology.data", level="WARNING") as lg:
            df = data.get_ohlcv("AAA", use_cache=False)
        self.assertEqual(len(df), 5)
        self.assertTrue(
            any("AAA" in str(x) and "cache basi" in str(x) for x in lg.output),
            lg.output)

    def test_fetch_gagal_tanpa_cache_error_asli_diteruskan(self):
        # Tanpa cache: error asli RAISE (tidak ditelan) - jalur ini sudah
        # jujur sejak lama dan TIDAK boleh berubah.
        self._patch(data, "_cache_path",
                    lambda *a, **k: pathlib.Path(self.tmp.name) / "kosong.csv")
        self._patch(data.yf, "download", self._boom)
        with self.assertRaises(RuntimeError):
            data.get_ohlcv("AAA", use_cache=False)

    def test_read_cache_rusak_dihapus_dan_tidak_senyap(self):
        p = pathlib.Path(self.tmp.name) / "rusak.csv"
        p.write_text("", encoding="utf-8")  # EmptyDataError -> dihapus
        with self.assertLogs("laumology.data", level="WARNING") as lg:
            out = data._read_cache(p)
        self.assertIsNone(out)
        self.assertFalse(p.exists())
        self.assertTrue(any("cache rusak" in str(x) for x in lg.output), lg.output)

    def test_prefetch_chunk_gagal_tidak_senyap(self):
        # Satu chunk = hingga 60 ticker; kegagalan chunk tidak boleh
        # menghilang (warmup jadi "seolah sehat").
        self._patch(data.yf, "download", self._boom)
        with self.assertLogs("laumology.data", level="WARNING") as lg:
            n = data.prefetch(["AAA", "BBB"])
        self.assertEqual(n, 0)
        self.assertTrue(any("prefetch chunk" in str(x) for x in lg.output), lg.output)

    def test_prefetch_normalisasi_gagal_tidak_senyap(self):
        raw = pd.DataFrame({"Close": [10.0, 11.0, 12.0]})
        self._patch(data.yf, "download", lambda *a, **k: raw)
        self._patch(data, "_normalize", self._boom)
        with self.assertLogs("laumology.data", level="WARNING") as lg:
            n = data.prefetch(["AAA"])
        self.assertEqual(n, 0)
        self.assertTrue(
            any("AAA" in str(x) and "dinormalisasi" in str(x) for x in lg.output),
            lg.output)

    def test_get_many_gagal_tidak_senyap(self):
        # Dulu print tanpa traceback (pola batch-42/43) - kini warning.
        self._patch(data, "get_ohlcv", self._boom)
        with self.assertLogs("laumology.data", level="WARNING") as lg:
            out = data.get_many(["AAA"])
        self.assertEqual(out, {})
        self.assertTrue(any("get_many AAA" in str(x) for x in lg.output), lg.output)

    def test_get_quote_semua_sumber_gagal_tidak_senyap(self):
        # realtime sah mengembalikan None (fallback chain by design);
        # warning hanya bila SEMUA sumber gagal (hasil akhir None).
        import realtime

        self._patch(realtime, "fetch_quote", self._boom)
        self._patch(data, "_yf_quote", lambda yt, now: None)
        with self.assertLogs("laumology.data", level="WARNING") as lg:
            q = data.get_quote("AAA")
        self.assertIsNone(q)
        self.assertTrue(
            any("quote AAA.JK" in str(x) for x in lg.output), lg.output)


if __name__ == "__main__":
    unittest.main()
