# Protokol Operasi Agen — LAUMOLOGY War Room

Protokol bersama untuk SEMUA agen (lead, code, quant, qa, reviewer, security, uiux, technical).
Dokumen ini melengkapi `AGENTS.md`. Bila bertentangan, `AGENTS.md` menang.

## 1. Prinsip
- **Berbasis bukti.** Setiap klaim teknis wajib disertai `path:line` atau output perintah nyata. Tidak ada bukti → nyatakan sebagai dugaan, bukan fakta.
- **Jujur & tegas.** Bila tidak yakin, katakan. Bila menemukan masalah, sebutkan dampaknya dan keputusan (terima/revisi/tolak).
- **Kecil & reversibel.** Satu peningkatan bernilai tinggi per tugas; hindari perubahan melebar.
- **Hemat.** Token = biaya. Baca seperlunya, rangkum, jangan ulang pekerjaan.

## 2. Loop kerja (Observe → Plan → Act → Verify)
1. **Pahami** tujuan & batasannya. Baca konteks yang spesifik, bukan seluruh repo.
2. **Rencana** langkah sekecil mungkin yang menyelesaikan tujuan.
3. **Lakukan** dengan alat yang ada; batasi perubahan ke berkas yang relevan.
4. **Verifikasi** dengan perintah nyata (uji/gate), bukan asumsi.
5. **Laporkan** ringkas: apa, di mana, bukti, keputusan.

## 3. Ekonomi konteks (hemat token)
- Gunakan `glob`/`grep` untuk menemukan lokasi, lalu `read` hanya pada rentang baris yang perlu.
- Jangan memuat ulang berkas besar; ringkas temuan sebelumnya menjadi poin-poin.
- Untuk tugas yang jawabannya cukup singkat, hentikan lebih awal. Jangan menjelajah tanpa arah.
- Hindari menyalin isi berkas panjang ke dalam jawaban; cukup rujuk `path:line`.

## 4. Kontrak keluaran (format jawaban)
- Bahasa Indonesia, ringkas. Poin-poin, bukan paragraf panjang.
- Struktur rekomendasi: **(a)** masalah + bukti `path:line`, **(b)** langkah, **(c)** berkas terdampak, **(d)** kriteria penerimaan, **(e)** risiko regresi.
- Bila meninjau: akhiri dengan `REKOMENDASI: TERIMA` atau `REKOMENDASI: REVISI`.
- Tanpa basa-basi, tanpa mengulang instruksi, tanpa meminta klarifikasi bila tugas jelas.

## 5. Eksekusi & verifikasi
- Interpreter proyek: **`py -3.14`**. `python` tidak ada di PATH.
- Gerbang kualitas: `py -3.14 tools/quality_gate.py` (syntax + JS + regresi `tests.test_engine`). Wajib LULUS.
- Uji regresi: `py -3.14 -m unittest tests.test_engine`. Golden `TestLegacyRegression` wajib hijau.
- Gunakan perintah read-only untuk menyelidiki (`git diff`, `git status`, uji). Jangan commit/push.
- **Jangan** operasi Git destruktif (`reset --hard`, `clean`, force-push, rebase, filter-branch).

## 6. Domain LAUMOLOGY
- Aplikasi analisis saham IDX: Python/Flask. Mesin analisis: `indicators.py`, `factors.py`, `signals.py`, `decision.py`, `calibration.py`, `validation.py`, `backtest.py`, `risk.py`, `metrics.py`.
- **Jangan** mengubah rumus keuangan/indikator tanpa bukti atau fixture uji yang jelas.
- Waspadai **look-ahead bias** pada perhitungan berbasis bar (hanya pakai data sampai bar saat ini).
- Konvensi: `from __future__ import annotations`, komentar/pesan bahasa Indonesia, tanpa dependensi baru tanpa alasan kuat.
- Bila perlu panduan domain, muat skill `idx-analysis`; untuk operasional War Room, skill `warroom-ops`.

## 7. Keamanan
- Jangan pernah mencetak/menulis API key, token, atau isi `.env`/`llm.json`/`realtime.json` ke log.
- Validasi input di batas sistem (ticker, angka, payload HTTP). Gagal secara aman (*fail-closed*).

## 8. Koordinasi tim
- **Lead** memutuskan, membagi tugas, dan menyintesis.
- Spesialis (quant/qa/security/uiux/technical/fundamental/seo) memberi temuan read-only berbukti; code mengimplementasi; reviewer menantang secara independen.
- Jangan menduplikasi pekerjaan rekan; bangun di atas temuan yang ada.
