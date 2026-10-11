# AGENTS.md — LAUMOLOGY

Panduan untuk agen AI (OpenCode) yang bekerja di repositori ini.

## Ringkasan Proyek

LAUMOLOGY adalah aplikasi analisis saham IDX berbasis Python/Flask.
- **Entry web:** `webapp.py` (WSGI target `webapp:app`).
- **Entry CLI:** `main.py` (`analyze|screen|backtest|chart`).
- **Routing:** `routes/` (6 blueprint, 50 endpoint) diregistrasi via `routes/__init__.py:register`.
- **Mesin analisis:** `indicators.py`, `factors.py`, `signals.py`, `decision.py`, `calibration.py`, `musyawarah.py`, `stock.py`.
- **Backtest/risiko:** `backtest.py`, `risk.py`, `metrics.py`, `validation.py`.
- **Config:** `config.py` (dataclass `settings`, nilai default di kode). Flag penting dapat di-override lewat environment variable dengan prefix `LAUM_` (12-factor), lihat `.env.example`.
- **Penyimpanan:** `store.py` (SQLite), `state.py` (state runtime in-memory).

## Perintah Penting

Interpreter: **`py -3.14`** (Python 3.14 di `C:\Python314`). `python` tidak ada di PATH; `py -3.11`/`py -3.12` tidak memiliki dependensi.

```powershell
# Test (semua)
py -3.14 -m unittest tests.test_engine

# Test (verbose)
py -3.14 -m unittest tests.test_engine -v

# Quality gate lokal (syntax seluruh modul + regresi tests.test_engine)
py -3.14 tools/quality_gate.py

# Jalankan web lokal
py -3.14 webapp.py --host 127.0.0.1 --port 5000

# CLI analisis
py -3.14 main.py analyze BBCA
```

Tidak ada linter/type-checker/CI. Gerbang kualitas lokal: `py -3.14 tools/quality_gate.py` (syntax seluruh modul + regresi `tests.test_engine`). Jaga agar `py -3.14 -m unittest tests.test_engine` tetap hijau.

## Konvensi Kode

- Python 3, `from __future__ import annotations` di modul.
- Komentar dan pesan pengguna berbahasa Indonesia (konsisten dengan kode yang ada).
- Ikuti pola modul yang ada; jangan menambah dependensi baru tanpa alasan kuat.
- Jangan mengubah rumus keuangan tanpa bukti/default fixture yang jelas.
- Uji golden di `tests/test_engine.py:TestLegacyRegression` harus tetap lulus.

## Keamanan Git (WAJIB)

Dilarang otomatis: `git reset --hard`, `git clean`, force-push, menulis ulang riwayat, menghapus pekerjaan pengguna, `vercel deploy`/deploy produksi langsung.
`git push origin <branch>` DIIZINKAN (kebijakan pengguna) agar War Room dapat deploy otomatis ke Render. Commit otonom hanya boleh men-stage modifikasi file terlacak dan jalur pengembangan (`tools/`, `routes/`, `tests/`, `api/`, `pine/`, `templates/`, `static/`, `.opencode/`); JANGAN pernah men-stage file pribadi pengguna (`Agent/`, `*.docx`, `*.pdf`).
Lindungi perubahan pengguna (staged, unstaged, untracked). Jangan pernah membuang/menimpa pekerjaan pengguna.
Jalankan `py -3.14 tools/quality_gate.py` (harus LULUS) sebelum push.

## Rahasia

Jangan pernah mencatat/mencetak API key, token, atau isi `.env`/`llm.json`/`realtime.json` ke log.

## War Room

`tools/warroom/` berisi supervisor otonom dan agen. Status persisten di `tools/warroom/state/` (gitignored).
