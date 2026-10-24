"""Tes observabilitas external (tekanan_luar): degradasi tidak lagi senyap.

Modul data/market/news di-stub via sys.modules bila dependensinya
tidak tersedia (repro lokal stdlib murni); di CI modul asli dipakai
dan atribut dipatch lalu dipulihkan otomatis oleh mock.
Perilaku fallback identik - hanya jejak log yang ditambah.
"""
import sys
import types
import unittest
from unittest import mock


def _load_external():
    try:
        import external  # noqa: F401
        return sys.modules["external"]
    except Exception:
        pass
    stubs = {}
    for name in ("data", "market", "news"):
        if name not in sys.modules:
            stubs[name] = sys.modules[name] = types.ModuleType(name)
    try:
        sys.modules.pop("external", None)
        import external
        return external
    except Exception:
        return None
    finally:
        for name, mod in stubs.items():
            if sys.modules.get(name) is mod:
                sys.modules.pop(name, None)


external = _load_external()


def _fake_xsource(headlines=None, headlines_for=None, compare=None):
    mod = types.ModuleType("xsource")
    mod.headlines = headlines or (lambda: ([], False))
    mod.headlines_for = headlines_for or (lambda code: ([], False))
    mod.compare_signal = compare or (lambda our, posts, subject="": {"alignment": "belum ada"})
    return mod


class _FakeClose:
    """Cukup seperti Series.Close untuk _proxy: astype, len, iloc[-n]."""

    def __init__(self, vals):
        self._vals = list(vals)

    def astype(self, _t):
        return self

    def __len__(self):
        return len(self._vals)

    @property
    def iloc(self):
        return self

    def __getitem__(self, i):
        return self._vals[i]


def _bundle_minimal():
    return {
        "headlines": [],
        "news_ok": False,
        "x_ok": False,
        "x_items": [],
        "ihsg": {},
        "usdidr": {"ret_5d": None, "ok": False},
        "global": {"ret_5d": None, "ok": False},
    }


@unittest.skipUnless(external is not None, "modul external tidak bisa diimpor")
class ExternalSilentTest(unittest.TestCase):
    def test_proxy_gagal_warning_dan_ok_false(self):
        with mock.patch.object(external.data, "get_ohlcv", side_effect=RuntimeError("no data"), create=True):
            with self.assertLogs("laumology.external", level="WARNING") as ctx:
                res = external._proxy("USDIDR=X")
        self.assertFalse(res["ok"])
        self.assertIsNone(res["ret_1d"])
        self.assertTrue(any("USDIDR=X" in m and "gagal" in m for m in ctx.output))

    def test_proxy_sukses_tanpa_warning(self):
        frame = {"Close": _FakeClose([100.0, 101.0, 105.0, 110.0, 108.0, 120.0, 126.0])}
        with mock.patch.object(external.data, "get_ohlcv", return_value=frame, create=True):
            with self.assertNoLogs("laumology.external", level="WARNING"):
                res = external._proxy("^GSPC")
        self.assertTrue(res["ok"])
        self.assertIsNotNone(res["ret_1d"])

    def test_kueri_berita_makro_gagal_warning(self):
        with mock.patch.object(external.news, "headlines_for_query", side_effect=RuntimeError("news down"), create=True):
            with self.assertLogs("laumology.external", level="WARNING") as ctx:
                items, any_ok = external._macro_headlines()
        self.assertEqual(items, [])
        self.assertFalse(any_ok)
        self.assertTrue(any("kueri berita makro" in m and "gagal" in m for m in ctx.output))

    def test_bundle_headlines_gagal_total_warning(self):
        with mock.patch.object(external, "_macro_headlines", side_effect=RuntimeError("total down")):
            with mock.patch.object(external, "_proxy", return_value={"ret_1d": None, "ret_5d": None, "ok": False}):
                with mock.patch.object(external.market, "ihsg", return_value={}, create=True):
                    with mock.patch.dict(sys.modules, {"xsource": _fake_xsource()}):
                        with self.assertLogs("laumology.external", level="WARNING") as ctx:
                            bundle = external._build_bundle()
        self.assertEqual(bundle["headlines"], [])
        self.assertFalse(bundle["news_ok"])
        self.assertTrue(any("berita makro" in m and "gagal total" in m for m in ctx.output))

    def test_bundle_xsource_gagal_warning(self):
        fake = _fake_xsource(headlines=mock.Mock(side_effect=RuntimeError("x down")))
        with mock.patch.object(external, "_macro_headlines", return_value=([], False)):
            with mock.patch.object(external, "_proxy", return_value={"ret_1d": None, "ret_5d": None, "ok": False}):
                with mock.patch.object(external.market, "ihsg", return_value={}, create=True):
                    with mock.patch.dict(sys.modules, {"xsource": fake}):
                        with self.assertLogs("laumology.external", level="WARNING") as ctx:
                            bundle = external._build_bundle()
        self.assertFalse(bundle["x_ok"])
        self.assertEqual(bundle["x_items"], [])
        self.assertTrue(any("sumber X gagal" in m for m in ctx.output))

    def test_bundle_ihsg_gagal_warning_dan_stub_error(self):
        with mock.patch.object(external, "_macro_headlines", return_value=([], False)):
            with mock.patch.object(external, "_proxy", return_value={"ret_1d": None, "ret_5d": None, "ok": False}):
                with mock.patch.object(external.market, "ihsg", side_effect=RuntimeError("ihsg down"), create=True):
                    with mock.patch.dict(sys.modules, {"xsource": _fake_xsource()}):
                        with self.assertLogs("laumology.external", level="WARNING") as ctx:
                            bundle = external._build_bundle()
        self.assertEqual(bundle["ihsg"], {"error": "RuntimeError"})
        self.assertTrue(any("ihsg gagal" in m for m in ctx.output))

    def test_for_stock_berita_emiten_gagal_warning(self):
        with mock.patch.object(external, "_bundle", return_value=_bundle_minimal()):
            with mock.patch.object(external.news, "get_news", side_effect=RuntimeError("emiten down"), create=True):
                with mock.patch.dict(sys.modules, {"xsource": _fake_xsource()}):
                    with self.assertLogs("laumology.external", level="WARNING") as ctx:
                        res = external.for_stock(ticker="BBCA")
        self.assertIn("X", res["missing"])
        self.assertTrue(any("BBCA" in m and "berita emiten" in m for m in ctx.output))

    def test_for_stock_gagal_total_warning_dan_status_jujur(self):
        with mock.patch.object(external, "_bundle", side_effect=RuntimeError("bundle down")):
            with self.assertLogs("laumology.external", level="WARNING") as ctx:
                res = external.for_stock(ticker="BBCA")
        self.assertEqual(res["status"], "tidak_tersedia")
        self.assertTrue(any("gagal total" in m for m in ctx.output))


if __name__ == "__main__":
    unittest.main()
