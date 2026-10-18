"""Tes endpoint /api/edge (ringkasan uji edge indikator).

Tanpa jaringan: `indicator_edge.evaluate` di-mock dengan laporan sintetis.
Yang dijaga: payload jujur (top_events dipotong sesuai `top`, event sampel
kecil tetap di `skipped_low_sample`), parameter di-clamp, cache bekerja,
parameter non-angka ditolak 400, dan error evaluasi jujur (502).
"""
from __future__ import annotations

import unittest
from unittest import mock

from flask import Flask

import routes


def _fake_report():
    return {
        "generated": "2026-10-18 01:00:00",
        "universe": "lq45",
        "horizon_days": 5,
        "warmup_bars": 250,
        "min_count": 30,
        "tickers_evaluated": 40,
        "tickers_total": 45,
        "baseline_hit": 0.484,
        "baseline_med_ret": 0.001,
        "ranking": [
            {"event": "e_a", "dir": 1, "n": 120, "ranked": True, "hit_5d": 0.6,
             "med_ret_5d": 0.01, "uplift_vs_baseline": 0.116,
             "worst_half_hit": 0.55, "n_halves": 4},
            {"event": "e_b", "dir": 1, "n": 90, "ranked": True, "hit_5d": 0.55,
             "med_ret_5d": 0.008, "uplift_vs_baseline": 0.066,
             "worst_half_hit": 0.51, "n_halves": 4},
            {"event": "e_c", "dir": -1, "n": 60, "ranked": True, "hit_5d": 0.52,
             "med_ret_5d": -0.002, "uplift_vs_baseline": 0.036,
             "worst_half_hit": 0.49, "n_halves": 3},
        ],
        "skipped_low_sample": ["e_kecil"],
        "catatan": "event a priori, tanpa tuning.",
    }


class EdgeApiTestBase(unittest.TestCase):
    def setUp(self):
        routes.edge._CACHE["key"] = None
        routes.edge._CACHE["ts"] = 0.0
        routes.edge._CACHE["payload"] = None
        app = Flask(__name__)
        routes.register(app)
        app.config["TESTING"] = True
        self.client = app.test_client()


class TestEdgeApi(EdgeApiTestBase):
    def test_payload_ringkas_dan_jujur(self):
        with mock.patch.object(routes.edge.indicator_edge, "evaluate", return_value=_fake_report()) as ev:
            resp = self.client.get("/api/edge?universe=lq45&horizon=5&top=2")
        self.assertEqual(resp.status_code, 200)
        js = resp.get_json()
        ev.assert_called_once_with("lq45", 5, 30)
        self.assertEqual(js["universe"], "lq45")
        self.assertEqual(js["horizon_days"], 5)
        self.assertEqual(js["tickers_evaluated"], 40)
        self.assertEqual(len(js["top_events"]), 2)
        self.assertEqual(js["top_events"][0]["event"], "e_a")
        self.assertEqual(js["skipped_low_sample"], ["e_kecil"])
        self.assertIn("catatan", js)

    def test_cache_dipakai_untuk_permintaan_sama(self):
        with mock.patch.object(routes.edge.indicator_edge, "evaluate", return_value=_fake_report()) as ev:
            self.client.get("/api/edge?universe=lq45&horizon=5&top=2")
            self.client.get("/api/edge?universe=lq45&horizon=5&top=2")
        self.assertEqual(ev.call_count, 1)

    def test_kunci_cache_berbeda_mengevaluasi_ulang(self):
        with mock.patch.object(routes.edge.indicator_edge, "evaluate", return_value=_fake_report()) as ev:
            self.client.get("/api/edge?universe=lq45&horizon=5")
            self.client.get("/api/edge?universe=lq45&horizon=10")
        self.assertEqual(ev.call_count, 2)
        self.assertEqual(ev.call_args_list[1].args, ("lq45", 10, 30))

    def test_parameter_di_clamp(self):
        with mock.patch.object(routes.edge.indicator_edge, "evaluate", return_value=_fake_report()) as ev:
            resp = self.client.get("/api/edge?horizon=999&top=0&min_count=1")
        self.assertEqual(resp.status_code, 200)
        # horizon 999 -> 60, top 0 -> 1, min_count 1 -> 10
        self.assertEqual(ev.call_args_list[0].args, ("lq45", 60, 10))

    def test_parameter_non_angka_ditolak(self):
        resp = self.client.get("/api/edge?horizon=abc")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_error_evaluasi_jujur_502(self):
        with mock.patch.object(routes.edge.indicator_edge, "evaluate", side_effect=RuntimeError("data gagal")):
            resp = self.client.get("/api/edge?universe=lq45&horizon=5")
        self.assertEqual(resp.status_code, 502)
        self.assertIn("data gagal", resp.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
