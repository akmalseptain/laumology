"""Tes konsistensi /api/schema dengan endpoint nyata yang terdaftar.

Mengunci regresi: /api/edge dan /api/trackrecord (ditambahkan di batch-3)
harus tetap terdaftar di skema dengan parameter yang benar. Skema tidak
boleh membocorkan endpoint internal War Room (dilindungi API_KEY).
"""
from __future__ import annotations

import unittest

from flask import Flask

import routes


class SchemaApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        routes.register(app)
        app.config["TESTING"] = True
        self.client = app.test_client()
        resp = self.client.get("/api/schema")
        self.assertEqual(resp.status_code, 200)
        js = resp.get_json()
        self.assertIn("endpoints", js)
        self.endpoints = {e["path"]: e for e in js["endpoints"]}

    def test_edge_terdaftar_dengan_param_benar(self):
        ep = self.endpoints.get("/api/edge")
        self.assertIsNotNone(ep, "/api/edge harus terdaftar di /api/schema")
        self.assertEqual(ep["method"], "GET")
        self.assertEqual(ep["params"], ["universe", "horizon", "top", "min_count"])

    def test_trackrecord_terdaftar(self):
        ep = self.endpoints.get("/api/trackrecord")
        self.assertIsNotNone(ep, "/api/trackrecord harus terdaftar di /api/schema")
        self.assertEqual(ep["method"], "GET")

    def test_attribution_terdaftar_dengan_param_benar(self):
        ep = self.endpoints.get("/api/attribution")
        self.assertIsNotNone(ep, "/api/attribution harus terdaftar di /api/schema")
        self.assertEqual(ep["method"], "GET")
        self.assertEqual(ep["params"], ["horizon", "min_n"])

    def test_verdicts_terdaftar_dengan_param_benar(self):
        ep = self.endpoints.get("/api/verdicts")
        self.assertIsNotNone(ep, "/api/verdicts harus terdaftar di /api/schema")
        self.assertEqual(ep["method"], "GET")
        self.assertEqual(ep["params"], ["horizon", "limit"])

    def test_schema_tidak_membocorkan_warroom(self):
        # Endpoint War Room internal (dilindungi X-API-Key): tidak boleh
        # diiklankan di skema publik.
        for path in self.endpoints:
            self.assertFalse(path.startswith("/api/warroom"),
                            f"endpoint internal {path} tidak boleh di skema publik")

    def test_semua_entri_bentuk_lengkap(self):
        for path, ep in self.endpoints.items():
            self.assertIn("method", ep, f"{path} tanpa method")
            self.assertIn(ep["method"], ("GET", "POST"), f"{path} method tak terduga")
            self.assertIn("params", ep, f"{path} tanpa params")


if __name__ == "__main__":
    unittest.main()
