# Panduan Deployment & Persistensi Data

Status aktual (2026-10-18): **laumology.vercel.app sudah mati** (DEPLOYMENT_NOT_FOUND).
Live sebenarnya: **https://laumology.onrender.com** (render.yaml, plan free,
ENABLE_SCHEDULER=1, SCAN_INTERVAL=900).

## Masalah plan free Render
1. **Filesystem ephemeral** — SQLite (`store.py`: `.cache/laumology.db` atau `$DATA_DIR`)
   **terhapus setiap restart/spin-down**. Feedback loop (outcomes) tidak bisa
   mengumpulkan bukti; track record selalu kosong.
2. **Spin-down saat idle** — scheduler ikut pause; sinyal tidak direkam
   saat tidak ada pengunjung.

## Opsi A — GRATIS, tetap di Render (rekomendasi hemat) — SUDAH OTOMATIS DI REPO
Repo sudah membawa bootstrap-nya: `scripts/render-start.sh` (aman dua arah:
env belum diisi = jalan seperti biasa; env lengkap = restore + streaming).
Langkah kamu (sekali saja, ±10 menit):
1. **Cloudflare R2** (console.cloudflare.com → R2): buat bucket (mis.
   `laumology-db`) → Manage API Tokens → buat token Object Read & Write →
   catat Access Key ID, Secret Access Key, dan Endpoint
   (`https://<ACCOUNT_ID>.r2.cloudflarestorage.com`).
2. **Render Dashboard** → service `laumology` → Environment, tambahkan:
   - `LITESTREAM_BUCKET` = nama bucket
   - `LITESTREAM_ACCESS_KEY_ID` = access key R2
   - `LITESTREAM_SECRET_ACCESS_KEY` = secret R2
   - `LITESTREAM_ENDPOINT` = endpoint R2
   (opsional: `LITESTREAM_PATH`, `LITESTREAM_RETENTION`, `LITESTREAM_SYNC_INTERVAL`)
3. **Deploy ulang** (Manual Deploy → Deploy latest commit setelah merge).
   Log harus menampilkan `[render-start] Litestream AKTIF`.
4. **Anti tidur**: daftar UptimeRobot (free) → monitor HTTP
   `https://laumology.onrender.com/health` interval 5 menit.
   (cron-job.org juga bisa.) Tanpa ini, sinyal hanya terekam saat ada pengunjung.

Verifikasi: setelah beberapa hari, `/api/trackrecord` → `n_signals` harus
bertambah DAN tidak kembali ke 0 setelah restart (DB pulih dari replica).

## Opsi B — PALING SIMPEL, berbayar murah (±$7/bulan)
Upgrade ke **Render Starter** + **Persistent Disk 1GB**, set `DATA_DIR` ke
path disk (mis. `/var/lib/data`). `store.py` sudah mendukung `DATA_DIR`.
Contoh blueprint: `render-persist.yml.example`. Tidak perlu Litestream,
tidak perlu ping (Starter tidak spin-down).

## Opsi C — Ganti provider?
- **Koyeb / Hugging Face Spaces / Fly (user baru)**: free tier TANPA disk
  persisten untuk Python — masalah yang sama, tidak menyelesaikan apa pun.
- **Oracle Cloud Always Free (VM)**: gratis permanen + disk persisten, tapi
  setup manual (bukan PaaS): install Python, gunicorn, nginx/certbot sendiri.
- **Turso (SQLite) / Supabase-Neon (Postgres)**: DB eksternal free tier —
  menyelesaikan persistensi, tapi butuh refactor `store.py` (driver beda).
  Pertimbangkan hanya kalau ingin multi-region/multi-instance.

## Kesimpulan
Jangan ganti provider demi persistensi — pilih Opsi A (gratis, +1 langkah
setup) atau Opsi B ($7/bln, nol kerja). Yang penting: **DB harus persisten**
sebelum feedback loop bisa menghasilkan angka benar/salah yang nyata.
