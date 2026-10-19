"""Jaring pengaman cache data.py — kunci hasil audit batch-13. Tanpa jaringan.

_read_cache: berkas kosong/CSV korup dihapus lalu None (jujur gagal, pemanggil
unduh ulang); _write_cache: atomik (os.replace) tanpa sisa .tmp; _cache_path:
ticker dari klien disanitasi sehingga tidak bisa keluar dari cache_dir.
Skor 0-100 tidak diubah.
"""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import data
from config import settings


class DataCacheGuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cache_dir = settings.cache_dir
        settings.cache_dir = self._tmp.name

    def tearDown(self):
        settings.cache_dir = self._old_cache_dir
        self._tmp.cleanup()

    def test_read_cache_berkas_kosong(self):
        p = Path(self._tmp.name) / "kosong.csv"
        p.write_text("", encoding="utf-8")
        self.assertIsNone(data._read_cache(p))
        # berkas rusak DIHAPUS supaya tidak membandel sampai TTL habis
        self.assertFalse(p.exists())

    def test_read_cache_csv_korup(self):
        p = Path(self._tmp.name) / "korup.csv"
        p.write_text('Date,Close\n2026-01-01,"tak-tertutup', encoding="utf-8")
        self.assertIsNone(data._read_cache(p))
        self.assertFalse(p.exists())

    def test_read_cache_valid(self):
        p = Path(self._tmp.name) / "valid.csv"
        pd.DataFrame({"Close": [1.0, 2.0]}).to_csv(p)
        df = data._read_cache(p)
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 2)
        self.assertTrue(p.exists())  # berkas valid tidak disentuh

    def test_write_cache_atomik_tanpa_sisa_tmp(self):
        p = Path(self._tmp.name) / "sub" / "atomik.csv"
        data._write_cache(pd.DataFrame({"Close": [1.0, 2.0, 3.0]}), p)
        self.assertTrue(p.exists())
        self.assertEqual(len(data._read_cache(p)), 3)
        self.assertEqual(list(p.parent.glob("*.tmp")), [])
        # tulis ulang harus MENIMPA, bukan menumpuk
        data._write_cache(pd.DataFrame({"Close": [9.0]}), p)
        self.assertEqual(len(data._read_cache(p)), 1)

    def test_cache_path_anti_traversal(self):
        p = data._cache_path("../../etc/passwd", "1y", "1d")
        # nama berkas hasil sanitasi tetap DI DALAM cache_dir
        self.assertEqual(p.parent, Path(settings.cache_dir))
        self.assertNotIn("/", p.name)
        self.assertNotIn("..", p.name)


if __name__ == "__main__":
    unittest.main()
