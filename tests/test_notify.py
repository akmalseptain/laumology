"""Tes alert webhook terstruktur (notify.signal_alert).

Data sintetis, tanpa jaringan: dispatch di-mock. Yang dijaga: payload
terstruktur lengkap dan jujur (field absen jadi None, bukan teks yang
menyesatkan), teks alert tetap aman dibangun walau field harga absen.
"""
from __future__ import annotations

import unittest
from unittest import mock

import notify


class TestSignalAlert(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "ticker": "BBCA", "signal": "BUY", "action": "BELI", "score": 78,
            "confidence": 65, "grade": "B", "price": 9500.0, "entry": 9450.0,
            "stop_loss": 9100.0, "tp1": 10000.0, "source": "scan",
            "ts": "2026-10-17 10:00:00",
        }
        row.update(overrides)
        return row

    def _capture(self, row):
        sent = []

        def fake_dispatch(text, payload=None):
            sent.append((text, payload))
            return {"webhook": {"ok": True}}

        with mock.patch.object(notify, "dispatch", fake_dispatch):
            notify.signal_alert(row)
        self.assertEqual(len(sent), 1)
        return sent[0]

    def test_payload_terstruktur_lengkap(self):
        text, payload = self._capture(self._row())
        self.assertEqual(payload["type"], "signal")
        self.assertEqual(payload["ticker"], "BBCA")
        self.assertEqual(payload["signal"], "BUY")
        self.assertEqual(payload["action"], "BELI")
        self.assertEqual(payload["score"], 78)
        self.assertEqual(payload["confidence"], 65)
        self.assertEqual(payload["grade"], "B")
        self.assertEqual(payload["price"], 9500.0)
        self.assertEqual(payload["entry"], 9450.0)
        self.assertEqual(payload["stop_loss"], 9100.0)
        self.assertEqual(payload["tp1"], 10000.0)
        self.assertEqual(payload["source"], "scan")
        self.assertEqual(payload["ts"], "2026-10-17 10:00:00")

    def test_teks_lengkap_dan_terbaca(self):
        text, _ = self._capture(self._row())
        self.assertIn("[BUY] BBCA", text)
        self.assertIn("skor 78", text)
        self.assertIn("conf 65%", text)
        self.assertIn("harga 9,500", text)
        self.assertIn("SL 9,100", text)
        self.assertIn("TP1 10,000", text)

    def test_field_harga_absen_tidak_crash(self):
        # Sinyal manual bisa tanpa SL/TP1/harga: payload jujur (None) dan
        # teks menampilkan "n/a", bukan exception.
        text, payload = self._capture({"price": None, "stop_loss": None, "tp1": None})
        self.assertIsNone(payload["price"])
        self.assertIsNone(payload["stop_loss"])
        self.assertIsNone(payload["tp1"])
        self.assertIn("harga n/a", text)
        self.assertIn("SL n/a TP1 n/a", text)

    def test_baris_minimal_hanya_ticker(self):
        text, payload = self._capture({"ticker": "TSTA"})
        self.assertEqual(payload["type"], "signal")
        self.assertEqual(payload["ticker"], "TSTA")
        self.assertIsNone(payload["signal"])
        self.assertIn("TSTA", text)


if __name__ == "__main__":
    unittest.main()
