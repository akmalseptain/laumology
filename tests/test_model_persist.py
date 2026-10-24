"""Tes persistensi model skor ke DB sqlite (batch-39).

Konteks produksi: file .cache di Render EPHEMERAL (hilang tiap deploy);
hanya DB sqlite yang direplika Litestream. Bobot model hasil kalibrasi
harus hidup di DB agar tidak hilang begitu saja pasca-deploy:
  - store.model_save/model_load: tabel model_state (stdlib murni).
  - calibration.save_model: tulis file + persist ke DB.
  - calibration.load_model: file hilang/korup -> fallback DB + hidrasi file.

Tes calibration butuh pandas/numpy (jalur CI); tes store jalan di mana pun.
"""
import json
import pathlib
import tempfile
import unittest

import store


class ModelStateStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = store.DB_PATH
        store.DB_PATH = pathlib.Path(self._tmp.name) / "test.db"
        store.init()

    def tearDown(self):
        store.DB_PATH = self._old_db
        self._tmp.cleanup()

    def test_roundtrip_simpan_muat(self):
        store.model_save("score_model", json.dumps({"coef": [1.0], "b": 2.0}))
        out = store.model_load("score_model")
        self.assertIsNotNone(out)
        self.assertEqual(json.loads(out), {"coef": [1.0], "b": 2.0})

    def test_upsert_timpa_versi_lama(self):
        store.model_save("score_model", json.dumps({"v": 1}))
        store.model_save("score_model", json.dumps({"v": 2}))
        self.assertEqual(json.loads(store.model_load("score_model"))["v"], 2)

    def test_muat_tidak_ada_none(self):
        self.assertIsNone(store.model_load("score_model"))
        self.assertIsNone(store.model_load("tidak_ada"))

    def test_nama_kosong(self):
        with self.assertRaises(ValueError):
            store.model_save("", "{}")
        self.assertIsNone(store.model_load(""))


try:
    import calibration
    _HAS_CAL = True
except Exception:  # pandas/numpy tak tersedia di sandbox lokal -> lompat
    _HAS_CAL = False


@unittest.skipUnless(_HAS_CAL, "butuh pandas/numpy (jalur CI)")
class CalibrationPersistTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = store.DB_PATH
        store.DB_PATH = pathlib.Path(self._tmp.name) / "test.db"
        store.init()
        import config
        self._cfg = config.settings
        self._old_path = self._cfg.score_model_path
        self._old_cache = dict(calibration._MODEL_CACHE)
        self._model_file = pathlib.Path(self._tmp.name) / "score_model.json"
        self._cfg.score_model_path = str(self._model_file)
        calibration._MODEL_CACHE.update(mtime=None, model=None, path=None)

    def tearDown(self):
        store.DB_PATH = self._old_db
        self._cfg.score_model_path = self._old_path
        calibration._MODEL_CACHE.clear()
        calibration._MODEL_CACHE.update(self._old_cache)
        self._tmp.cleanup()

    def _model(self):
        return {"coef": [0.1, -0.2], "intercept": 0.05, "mu": [0.0, 0.0],
                "sd": [1.0, 1.0], "base_rate": 0.5}

    def test_save_model_persist_ke_db(self):
        calibration.save_model(self._model())
        payload = store.model_load(calibration.MODEL_NAME)
        self.assertIsNotNone(payload)
        self.assertEqual(json.loads(payload), self._model())
        self.assertTrue(self._model_file.exists())  # file lokal tetap ditulis

    def test_load_model_fallback_dan_hidrasi_file(self):
        calibration.save_model(self._model())
        self._model_file.unlink()  # simulasi deploy: .cache ephemeral
        calibration._MODEL_CACHE.update(mtime=None, model=None, path=None)
        model = calibration.load_model()
        self.assertEqual(model, self._model())
        self.assertTrue(self._model_file.exists())  # file dihidrasi ulang

    def test_load_model_fallback_file_korup(self):
        calibration.save_model(self._model())
        self._model_file.write_text("{ korup", encoding="utf-8")
        calibration._MODEL_CACHE.update(mtime=None, model=None, path=None)
        model = calibration.load_model()
        self.assertEqual(model, self._model())
        self.assertEqual(json.loads(self._model_file.read_text(encoding="utf-8")),
                         self._model())

    def test_status_laporkan_db_persisted(self):
        st = calibration.status()
        self.assertFalse(st["available"])
        self.assertFalse(st["db_persisted"])
        calibration.save_model(self._model())
        st = calibration.status()
        self.assertTrue(st["available"])
        self.assertTrue(st["db_persisted"])


if __name__ == "__main__":
    unittest.main()
