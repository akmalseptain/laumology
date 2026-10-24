"""Tes observabilitas news: sumber berita makro gagal tidak lagi senyap.

CI-only: news butuh pandas/yfinance. _http_xml dan parser diganti fake.
Cache modul disimpan dan dipulihkan penuh setUp/tearDown.
Jalur sehat TETAP tanpa log (by design).
"""
import unittest
from unittest import mock

try:
    import news
    _OK = True
except Exception:
    _OK = False

@unittest.skipUnless(_OK, "news/pandas tidak tersedia (CI-only)")
class NewsSilentTest(unittest.TestCase):
    def setUp(self):
        self._orig_cache = dict(news._cache)

    def tearDown(self):
        news._cache.clear()
        news._cache.update(self._orig_cache)

    def test_semua_sumber_gagal_dua_warning_dan_ok_false(self):
        with mock.patch.object(news, "_http_xml", side_effect=OSError("net down")):
            with self.assertLogs("laumology.news", level="WARNING") as ctx:
                items, ok = news.headlines_for_query("IHSG MSCI", limit=5)
        self.assertEqual(items, [])
        self.assertFalse(ok)
        self.assertEqual(len(ctx.output), 2)
        joined = " | ".join(ctx.output)
        self.assertIn("bing.com", joined)
        self.assertIn("news.google.com", joined)

    def test_sumber_pertama_sukses_tanpa_warning(self):
        parsed = [{"title": "IHSG dan MSCI menguat pagi ini", "url": "https://x.id/a"}]
        with mock.patch.object(news, "_http_xml", return_value=b"<rss/>"), \
             mock.patch.object(news, "_parse_bing_rss", return_value=parsed):
            with self.assertNoLogs("laumology.news", level="WARNING"):
                items, ok = news.headlines_for_query("IHSG MSCI", limit=5)
        self.assertTrue(ok)
        self.assertEqual(len(items), 1)
        self.assertIn("MSCI", items[0]["title"])


if __name__ == "__main__":
    unittest.main()
