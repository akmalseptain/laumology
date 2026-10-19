"""Tes vonis sinyal (store.outcome_verdicts).

Semua data sintetis via SQLite sementara — tanpa jaringan/pandas.
Yang dijaga: kategori vonis a priori dihitung benar dari fwd/excess,
letak kesalahan hanya dihitung dari sinyal bervonis salah/turun,
DB kosong jujur (n=0), excess None tidak membuat vonis arbitrary.
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest

import store


def _insert_signal(conn, ticker, signal="BUY", action="BELI"):
    cur = conn.execute(
        "INSERT INTO signals(ts,ticker,signal,action,score,confidence,grade,"
        "price,entry,stop_loss,tp1,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2026-09-01 10:00:00", ticker, signal, action, 75, 65, "B",
         100.0, 100.0, 95.0, 110.0, "test"),
    )
    return cur.lastrowid


def _insert_outcome(conn, signal_id, horizon, fwd, excess, outcome):
    conn.execute(
        "INSERT INTO signal_outcomes(signal_id,horizon,evaluated_at,n_bars,fwd_return_pct,"
        "bench_fwd_pct,excess_pct,tp1_hit,sl_hit,outcome) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (signal_id, horizon, "2026-10-01 10:00:00", horizon, fwd,
         1.0 if excess is not None else None, excess,
         1 if outcome == "TP1" else 0, 1 if outcome == "SL" else 0, outcome),
    )


class VerdictTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_db = store.DB_PATH
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-verdict-test-")
        store.DB_PATH = pathlib.Path(self.tmp.name) / "t.db"
        store.init()
        self.conn = sqlite3.connect(store.DB_PATH)

    def tearDown(self):
        self.conn.close()
        store.DB_PATH = self._orig_db
        self.tmp.cleanup()

    def _seed(self, rows, horizon=5):
        """rows: list of (ticker, fwd, excess, outcome) atau (ticker, fwd, excess, outcome, signal, action)."""
        for row in rows:
            ticker, fwd, excess, outcome = row[0], row[1], row[2], row[3]
            signal = row[4] if len(row) > 4 else "BUY"
            action = row[5] if len(row) > 5 else "BELI"
            sid = _insert_signal(self.conn, ticker, signal, action)
            _insert_outcome(self.conn, sid, horizon, fwd, excess, outcome)
        self.conn.commit()


class TestOutcomeVerdicts(VerdictTestBase):
    def test_db_kosong_jujur(self):
        rep = store.outcome_verdicts(5)
        self.assertEqual(rep["n"], 0)
        self.assertEqual(rep["verdict_pct"], {})
        self.assertEqual(rep["wrong_where_pct"], {})

    def test_kategori_vonis(self):
        self._seed([
            ("TSTA", 2.0, 1.0, "TP1"),    # benar_nyata
            ("TSTB", 1.0, -0.5, "TP1"),   # untung_ikut_pasar
            ("TSTC", -1.0, 0.5, "NONE"),  # salah_relatif_ok
            ("TSTD", -2.0, -1.0, "SL"),   # salah
        ])
        rep = store.outcome_verdicts(5)
        self.assertEqual(rep["n"], 4)
        self.assertAlmostEqual(rep["verdict_pct"]["benar_nyata"], 25.0)
        self.assertAlmostEqual(rep["verdict_pct"]["untung_ikut_pasar"], 25.0)
        self.assertAlmostEqual(rep["verdict_pct"]["salah_relatif_ok"], 25.0)
        self.assertAlmostEqual(rep["verdict_pct"]["salah"], 25.0)

    def test_letak_kesalahan_hanya_dari_sinyal_salah(self):
        self._seed([
            ("TSTA", 3.0, 1.0, "TP1"),     # benar — tidak ikut dihitung
            ("TSTB", -2.0, -1.0, "SL"),    # salah: SL duluan + kalah IHSG
            ("TSTC", -1.0, -0.5, "SL"),    # salah: SL duluan + kalah IHSG
            ("TSTD", -0.5, -0.2, "NONE"),  # salah: nyalet + kalah IHSG
        ])
        rep = store.outcome_verdicts(5)
        self.assertEqual(rep["wrong_n"], 3)
        self.assertAlmostEqual(rep["wrong_where_pct"]["sl_duluan"], 100.0 * 2 / 3, delta=0.05)
        self.assertAlmostEqual(rep["wrong_where_pct"]["tanpa_tp1_dan_sl"], 100.0 * 1 / 3, delta=0.05)
        self.assertAlmostEqual(rep["wrong_where_pct"]["kalah_dari_ihsg"], 100.0)

    def test_excess_none_tidak_sembarangan(self):
        self._seed([
            ("TSTA", 2.0, None, "NONE"),   # fwd+ tanpa bench -> benar_nyata
            ("TSTB", -1.0, None, "SL"),    # fwd- tanpa bench -> salah (SL duluan)
        ])
        rep = store.outcome_verdicts(5)
        self.assertEqual(rep["verdict_pct"]["benar_nyata"], 50.0)
        self.assertEqual(rep["verdict_pct"]["salah"], 50.0)
        self.assertEqual(rep["wrong_where_pct"]["sl_duluan"], 100.0)
        self.assertEqual(rep["wrong_where_pct"]["kalah_dari_ihsg"], 0.0)

    def test_horizon_terpisah(self):
        self._seed([("TSTA", 2.0, 1.0, "TP1")], horizon=10)
        self.assertEqual(store.outcome_verdicts(5)["n"], 0)
        self.assertEqual(store.outcome_verdicts(10)["n"], 1)


class TestDirectionAwareVerdicts(VerdictTestBase):
    def test_sinyal_sell_dibalik(self):
        # "Disuruh tutup/turun ternyata harga naik" = SALAH.
        self._seed([
            ("TSTA", 2.0, 1.0, "NONE", "SELL", "JUAL"),   # naik -> salah
            ("TSTB", -2.0, -1.0, "NONE", "SELL", "JUAL"), # turun -> benar_nyata
        ])
        rep = store.outcome_verdicts(5)
        v = {x["signal_id"]: x for x in rep["recent"]}
        self.assertEqual(rep["n"], 2)
        self.assertAlmostEqual(rep["verdict_pct"]["salah"], 50.0)
        self.assertAlmostEqual(rep["verdict_pct"]["benar_nyata"], 50.0)
        self.assertEqual(rep["wrong_n"], 1)
        self.assertAlmostEqual(rep["wrong_where_pct"]["naik_padahal_turun"], 100.0)
        self.assertAlmostEqual(rep["wrong_where_pct"]["kalah_dari_ihsg"], 100.0)

    def test_sell_turun_tapi_ikut_pasar_tetap_tidak_unggul(self):
        # SELL & harga turun, tapi IHSG turun lebih dalam -> cuma ikut pasar.
        self._seed([
            ("TSTA", -1.0, 1.0, "NONE", "AVOID", "AVOID"),  # excess>0: saham turun kurang dr IHSG
        ])
        rep = store.outcome_verdicts(5)
        self.assertAlmostEqual(rep["verdict_pct"]["untung_ikut_pasar"], 100.0)

    def test_avoid_bernilai_avoid(self):
        self._seed([("TSTA", 1.5, 0.5, "NONE", "AVOID", "AVOID")])
        rep = store.outcome_verdicts(5)
        self.assertAlmostEqual(rep["verdict_pct"]["salah"], 100.0)
        self.assertEqual(rep["wrong_where_pct"]["naik_padahal_turun"], 100.0)


if __name__ == "__main__":
    unittest.main()
