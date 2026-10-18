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

## Opsi A — GRATIS, tetap di Render (rekomendasi hemat)
a) **Replikasi SQLite via Litestream** ke object storage gratis (Cloudflare R2
   free 10GB / Backblaze B2). Alur: saat boot → `litestream restore` DB dari
   replica; saat jalan → `litestream replicate` streaming terus-menerus.
   Contoh konfigurasi: lihat `litestream.yml.example`.
b) **Ping /health berkala** dari UptimeRobot / cron-job.org (gratis) supaya
   instance tidak tidur dan scheduler terus merekam sinyal (sesuai catatan
   di render.yaml).
c) Set env `DATA_DIR` (opsional) untuk lokasi DB yang konsisten.

Tanpa (a), DB hilang tiap restart. Tanpa (b), sinyal hanya terekam saat ada
pengunjung. Keduanya gratis.

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
