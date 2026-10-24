"""Tes observabilitas xsource: fallback gagal tidak lagi senyap.

xsource murni stdlib, jadi tes ini bisa direpro lokal tanpa pandas.
Jalur sukses tetap TANPA log (by design) - dijaga oleh tes juga.
Cache internal di-reset setUp/tearDown supaya tes tidak saling bocor.
"""
import unittest
from unittest import mock

import xsource


class _Resp:
    """Pengganti hasil urlopen: context manager dengan read()."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, _n: int = -1) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class XsourceSilentTest(unittest.TestCase):
    def setUp(self):
        xsource._cache.update({"ts": 0.0, "items": None, "ok": None})
        xsource._ticker_cache.clear()

    def tearDown(self):
        self.setUp()

    def test_fetch_query_gagal_warning_dan_jujur(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("net down")):
            with self.assertLogs("laumology.xsource", level="WARNING") as ctx:
                items, ok = xsource._fetch_query("IHSG site:x.com")
        self.assertEqual(items, [])
        self.assertFalse(ok)
        self.assertTrue(any("gagal" in m for m in ctx.output))

    def test_fetch_query_sukses_tanpa_warning(self):
        rss = (
            b"<rss><channel><item>"
            b"<title>IHSG dan MSCI naik pagi ini</title><link>u1</link>"
            b"</item></channel></rss>"
        )
        with mock.patch("urllib.request.urlopen", return_value=_Resp(rss)):
            with self.assertNoLogs("laumology.xsource", level="WARNING"):
                items, ok = xsource._fetch_query("IHSG site:x.com")
        self.assertTrue(ok)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "IHSG dan MSCI naik pagi ini")

    def test_headlines_gagal_total_warning(self):
        with mock.patch.object(xsource, "ThreadPoolExecutor", side_effect=RuntimeError("boom")):
            with self.assertLogs("laumology.xsource", level="WARNING") as ctx:
                items, ok = xsource.headlines()
        self.assertEqual(items, [])
        self.assertFalse(ok)
        self.assertTrue(any("pasar gagal total" in m for m in ctx.output))

    def test_headlines_for_gagal_total_warning(self):
        with mock.patch.object(xsource, "ThreadPoolExecutor", side_effect=RuntimeError("boom")):
            with self.assertLogs("laumology.xsource", level="WARNING") as ctx:
                items, ok = xsource.headlines_for("BBCA")
        self.assertEqual(items, [])
        self.assertFalse(ok)
        self.assertTrue(any("BBCA" in m and "gagal total" in m for m in ctx.output))


if __name__ == "__main__":
    unittest.main()
