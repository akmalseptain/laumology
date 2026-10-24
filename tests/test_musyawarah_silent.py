"""Tes observabilitas musyawarah: agen kehilangan data tidak lagi senyap.

CI-only: musyawarah butuh numpy + modul data/fundamentals/llm/market/ml/news.
Referensi modul di namespace musyawarah diganti fake, jadi pipeline utuh
berjalan sampai keputusan final TANPA jaringan dan tanpa Yahoo.
Jalur sehat TETAP tanpa log (by design) - dijaga tes happy-path.
Catatan desain: ml_error & engine llm sudah terlihat di payload respons
(ml_error / engine keys) - sisi itu sengaja TIDAK diberi log (preceden outcomes.py).
"""
import contextlib
import types
import unittest
from unittest import mock

try:
    import numpy as np  # noqa: F401
    import musyawarah
    _OK = True
except Exception:
    _OK = False


def _raise(msg):
    def _f(*_a, **_k):
        raise RuntimeError(msg)
    return _f


class _Series:
    def __init__(self, vals):
        self._vals = list(vals)

    def to_numpy(self, dtype=None):
        return np.asarray(self._vals, dtype=float)


class _Iloc:
    def __init__(self, row):
        self._row = row

    def __getitem__(self, _i):
        return self._row


class _FakeD:
    """Cukup untuk _bandarmologi: kolom dengan to_numpy + iloc[-1]."""

    def __getitem__(self, k):
        n = 60
        if k == "Close":
            return _Series([100.0 + i for i in range(n)])
        if k == "Volume":
            return _Series([1_000_000.0] * n)
        if k == "obv":
            return _Series([float(i) for i in range(n)])
        if k == "obv_ma20":
            return _Series([float(max(0, i - 10)) for i in range(n)])
        raise KeyError(k)

    @property
    def iloc(self):
        return _Iloc({"cmf": 0.05, "mfi": 55.0})


def _fake_a():
    return types.SimpleNamespace(
        signal="HOLD", trend="Sideways", weekly_trend="Sideways",
        monthly_trend="Sideways", regime="Netral", rsi=55.0, adx=20.0,
        macd_hist=0.01, support=100.0, resistance=110.0, score=50,
        grade="C", entry_breakout=None, price=105.0, change_1d=0.5,
        rs_change=0.1, rr2=2.5, decision={}, market_regime=None,
        buy_zone_high=None, entry=104.0, tp2=115.0, stop_loss=99.0,
    )


_FUND_HEALTHY = {
    "available": True, "has_financials": True, "roe": 0.15, "der": 0.5,
    "pe": 10.0, "pb": 1.5, "market_cap": 6e13,
    "valuation_code": "rendah", "valuation_label": "Murah",
    "valuation_note": "n", "quality_code": "baik",
    "quality_label": "Kualitas Baik", "quality_note": "n",
}
_NEWS_HEALTHY = {"label": "Netral", "avg_sentiment": 0, "count": 0, "items": []}
_MARKET_HEALTHY = {"regime": "Netral", "ret_1d": 0.1, "ret_20d": 0.5}
_EXTERNAL_HEALTHY = {
    "status": "netral", "label": "Netral", "intensity": 0,
    "summary": "Tidak ada tekanan luar.", "drivers": [],
    "x_compare": {"alignment": "belum cukup", "note": "Belum ada pos."},
}
_ML_HEALTHY = {"current_prob_up": 0.5, "base_rate": 0.5, "test_accuracy": 0.55}


@unittest.skipUnless(_OK, "musyawarah/numpy tidak tersedia (CI-only)")
class MusyawarahSilentTest(unittest.TestCase):
    @contextlib.contextmanager
    def _patched(self, *, fund=None, news_=None, market_=None,
                 external_=None, ml_=None):
        fake_data = types.SimpleNamespace(
            get_ohlcv=lambda t: object(),
            get_quote=lambda t: None,
            apply_live_quote=lambda df, q, tf: (df, None),
        )
        fake_fund = types.SimpleNamespace(
            get_fundamentals=fund or _raise("fund down"),
            classify_ratios=lambda pe, roe, der, sector=None: {
                "valuation_code": "n/a", "valuation_label": "Tidak dinilai",
                "valuation_note": None, "quality_code": "n/a",
                "quality_label": "Rasio tidak tersedia", "quality_note": None,
            },
        )
        fake_news = types.SimpleNamespace(
            get_news=news_ or _raise("news down"))
        fake_market = types.SimpleNamespace(
            ihsg=market_ or _raise("ihsg down"))
        fake_external = types.SimpleNamespace(
            for_stock=external_ or _raise("luar down"))
        fake_ml = types.SimpleNamespace(predict=ml_ or _raise("ml down"))
        with contextlib.ExitStack() as stack:
            for name, fake in (
                ("data", fake_data), ("fundamentals", fake_fund),
                ("news", fake_news), ("market", fake_market),
                ("external", fake_external), ("ml", fake_ml),
                ("analyze", lambda df, t: _fake_a()),
                ("add_indicators", lambda df: _FakeD()),
            ):
                stack.enter_context(mock.patch.object(musyawarah, name, fake))
            yield

    def test_empat_agen_gagal_warning_dan_keputusan_tetap_jujur(self):
        with self._patched():
            with self.assertLogs("laumology.musyawarah", level="WARNING") as ctx:
                res = musyawarah.musyawarah("BBCA")
        joined = " | ".join(ctx.output)
        self.assertEqual(len(ctx.output), 4)
        self.assertIn("fundamental BBCA gagal", joined)
        self.assertIn("berita emiten BBCA gagal", joined)
        self.assertIn("ihsg gagal", joined)
        self.assertIn("tekanan luar BBCA gagal", joined)
        # Keputusan tetap jujur & bobot fundamental dikecualikan (renormalisasi).
        self.assertFalse(res["fundamental_available"])
        self.assertNotIn("fundamental", res["weights_used"])
        self.assertIn(res["decision"], ("BUY", "WAIT", "SKIP"))
        # ml_error tetap jujur di payload - TANPA warning (by design).
        self.assertTrue(res.get("ml_error"))

    def test_agen_sehat_tanpa_warning(self):
        with self._patched(
            fund=lambda t: dict(_FUND_HEALTHY),
            news_=lambda t: dict(_NEWS_HEALTHY),
            market_=lambda: dict(_MARKET_HEALTHY),
            external_=lambda t, **k: dict(_EXTERNAL_HEALTHY),
            ml_=lambda df, t, horizon=5: dict(_ML_HEALTHY),
        ):
            with self.assertNoLogs("laumology.musyawarah", level="WARNING"):
                res = musyawarah.musyawarah("BBCA")
        self.assertTrue(res["fundamental_available"])
        self.assertIn("fundamental", res["weights_used"])
        self.assertIn(res["decision"], ("BUY", "WAIT", "SKIP"))


if __name__ == "__main__":
    unittest.main()
