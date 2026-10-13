---
name: warroom-ops
description: Use when working inside the LAUMOLOGY War Room or running its supervisor/loop, quality gate, backlog, or budget controls. Covers the exact py -3.14 commands, state files, budget modes, and Git safety rules.
---

# Skill: War Room Operations

Panduan operasional cepat untuk agen yang bekerja di repositori LAUMOLOGY.

## Interpreter & perintah inti
- Interpreter: **`py -3.14`** (`python` tidak ada di PATH).
- Gerbang kualitas (wajib LULUS): `py -3.14 tools/quality_gate.py`.
- Regresi: `py -3.14 -m unittest tests.test_engine` (verbose: tambah `-v`).
- Web lokal: `py -3.14 webapp.py --host 127.0.0.1 --port 5000`.
- CLI: `py -3.14 main.py analyze BBCA`.

## Lokasi state War Room (`tools/warroom/state/`, gitignored)
- `backlog.json` — item kerja terprioritas.
- `cycles.jsonl` — riwayat siklus supervisor.
- `pipeline-<cycleId>.json` — hasil pipeline per siklus.
- `discussion-*.json` — hasil diskusi multi-agen.
- `notulen-*.md` — notulen rapat/siklus (dipakai `replay`).
- `events.jsonl`, `usage-ledger.jsonl` — log & buku besar biaya.
- `control.json`, `supervisor.json` — kontrol pause/stop & status.

## Mode anggaran (fail-closed)
- `normal` → `warning` → `reduced` → `paused`. Ambang di `warroom.options.psd1`.
- `reduced`: paralelisme & cross-talk dimatikan otomatis.
- `paused` / ledger rusak: tidak ada panggilan model baru.

## Routing model & efisiensi
- Opsi `Models` di `warroom.options.psd1`: `Default`, `Fast`, `Strong`, `ByRole`, `ByAgent`.
- Default semua = `deepseek/deepseek-flash`. Isi `Strong`/`ByRole` untuk mengarahkan tugas kritis ke model lebih kuat.
- `EnableCrossTalk`, `MaxAgentRetries`, `*MaxChars` mengendalikan biaya konteks.

## Keamanan Git (WAJIB)
- Dilarang: `git reset --hard`, `git clean`, force-push, rebase, `filter-branch`.
- Hanya staging jalur pengembangan; JANGAN sentuh berkas pribadi pengguna (`Agent/`, `*.docx`, `*.pdf`).
- Jangan cetak API key/token atau isi `.env`/`llm.json`/`realtime.json`.
