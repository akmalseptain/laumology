# LAUMOLOGY AI WAR ROOM

Supervisor rekayasa otonom berbasis PowerShell untuk repositori LAUMOLOGY.
Menggunakan agen OpenCode yang nyata, kendali anggaran API, dan pengaman Git.

## Prasyarat

- Windows PowerShell 5.1.
- `py -3.14` (Python 3.14 di `C:\Python314`) dengan dependensi `requirements.txt`.
- `git` dan `opencode` CLI (v1.18.35+) tersedia di PATH.
- Kredensial provider DeepSeek terdaftar di OpenCode (`opencode auth`).

## Struktur

```
.opencode/agents/            # agen nyata: lead-engineer, code-engineer, quant-analyst, qa-engineer, reviewer, security-engineer, uiux-designer, technical-analyst, fundamental-analyst, seo-engineer
opencode.jsonc               # model + permission least-privilege (deny operasi destruktif)
tools/warroom/
  Start-WarRoom.ps1          # terminal komando
  Invoke-WarRoomTask.ps1     # satu panggilan agen (dengan kendali anggaran)
  Invoke-AutonomousLoop.ps1  # supervisor persisten
  warroom.options.psd1       # konfigurasi anggaran, tarif token, kurs (EDITABLE)
  lib/                       # Common, EventLog, StateManager, GitGuard, BudgetManager, BacklogManager, AgentRunner, DiscussionManager
  tests/Test-WarRoom.ps1     # uji mandiri
  state/                     # runtime (gitignored): status, ledger, log, backlog
```

## Perintah Persis

Semua dijalankan dari root repo LAUMOLOGY.

### Menjalankan terminal
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Start-WarRoom.ps1
```
Perintah dalam terminal: `help, team, status, backlog, diff, test, logs, doctor, pause, resume, stop, discuss <topik>, ask <agen> <teks>, loop, exit`.
`ask <agen> <teks>` mengirim prompt ke satu agen (`lead|code|quant|qa|reviewer|security|uiux|tech|fundamental|seo`) dengan kendali anggaran + log. `ask all <teks>` mengirim ke **seluruh agen**.

### Menjalankan supervisor otonom (mode batch manual)
```powershell
# Default: 4 siklus nyata, jeda pendek antar siklus, berhenti sendiri,
# dibatasi wall-clock 180 menit (3 jam). Cocok untuk dijalankan manual tanpa VPS.
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Invoke-AutonomousLoop.ps1

# Mode aman (tanpa panggilan model):
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Invoke-AutonomousLoop.ps1 -DryRun

# Override jumlah siklus / batas waktu:
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Invoke-AutonomousLoop.ps1 -MaxCycles 4 -MaxMinutes 180

# Satu siklus saja:
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Invoke-AutonomousLoop.ps1 -Once
```
Bila backlog kosong, tiap siklus otomatis melakukan **discovery+implementasi** kecil.
Setiap siklus eksekusi menjalankan **pipeline bertahap**: Lead (rencana) → investigasi paralel (2–3 spesialis pilihan Lead, read-only) → implementasi (code, satu penulis) → verifikasi paralel (spesialis + reviewer). Hasil per siklus disimpan di `state/pipeline-<cycleId>.json`.
Sesuaikan `CyclesPerRun`, `MaxRunMinutes`, `InterCycleDelaySeconds`, `ExecuteByDefault` di `warroom.options.psd1`.

### Memeriksa status dan anggaran
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Start-WarRoom.ps1 -Command status
```

### Auto-run tiap laptop (jalan sendiri saat logon)
```powershell
# Pasang: War Room otomatis menjalankan 4 siklus setiap kali logon
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Install-AutoRun.ps1
# Alternatif tanpa admin: taruh .bat di folder Startup
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Install-AutoRun.ps1 -Method Startup
# Lepas
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Install-AutoRun.ps1 -Remove
```
Sebelum push, loop menjalankan `git pull --ff-only`; bila remote berubah (bentrok antar-laptop), push **dilewati** dan commit lokal disimpan.

### Menjeda / melanjutkan / menghentikan
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Start-WarRoom.ps1 -Command pause
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Start-WarRoom.ps1 -Command resume
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\Start-WarRoom.ps1 -Command stop
```

### Melihat log dan penggunaan
```powershell
Get-Content tools\warroom\state\usage-ledger.jsonl      # buku besar token/biaya
Get-Content tools\warroom\state\events.jsonl -Tail 30   # event log
Get-Content tools\warroom\state\supervisor.json         # status supervisor
```

### Menjalankan uji War Room
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\warroom\tests\Test-WarRoom.ps1
```

## Anggaran

Edit `tools/warroom/warroom.options.psd1`. Ambang default (IDR):
`Warning 25.000 · Reduced 30.000 · TargetOtomasi/HardPause 35.000 · Bulanan 50.000`.
Kurs `UsdToIdr` dan `ExchangeRateVerifiedDate` wajib disesuaikan pengguna.

- Mode **warning**: peringatan.
- Mode **reduced**: diskusi opsional & paralel dimatikan.
- Mode **paused**: tidak ada panggilan AI otomatis baru.
- **Fail-closed**: bila ledger rusak/tak terbaca, semua panggilan otomatis dihentikan.

## Pembelajaran (agen makin pintar, makin mengerucut, irit token)

War Room memakai **loop refleksi** deterministik: tiap siklus menyaring pelajaran
nyata (kegagalan `quality_gate`, verifikasi `REVISI/TOLAK`, pendekatan yang `TERIMA`)
ke berkas `state/learning/<agen>.md` (+ `global.md`), lalu menyuntikkannya kembali ke
prompt siklus berikutnya — tanpa panggilan model tambahan.

- **Mengerucut:** pelajaran yang mirip digabung (kemiripan token/Jaccard
  >= `LearningSimilarityThreshold`) menjadi satu entri kanonik berhitungan `(xN)`,
  jadi memori jadi padat, bukan menumpuk. Saat melebihi `LearningMaxEntries`,
  entri ber-signal terendah (hitungan kecil/tertua) yang dibuang.
- **Irit token (thrift):** hanya sinyal terpenting yang disuntik (`(xN)` tinggi
  lebih dulu) dan ukuran blok **menyusut otomatis** saat anggaran masuk mode
  `warning`/`reduced` (faktor 0.75/0.5). Matikan total dengan `EnableLearning = $false`.
- **Riwayat tugas:** tugas yang sudah dikerjakan dicatat ringkas di
  `state/learning/history.md` dan disuntik ke Lead agar tidak mengulang pekerjaan
  lama (bangun di atasnya), tetapi hemat karena dibatasi `LearningHistoryMaxChars`.

Disuntik ke tahap PLAN (lead: memori + riwayat + global), INVESTIGATE (spesialis +
global), IMPLEMENT (code + global), dan VERIFY (spesialis + global).

Knob di `warroom.options.psd1`: `EnableLearning`, `LearningMaxEntries`,
`LearningMemoryMaxChars`, `LearningSimilarityThreshold`, `LearningHistoryMaxEntries`,
`LearningHistoryMaxChars`.

Periksa memori yang terkumpul:
```powershell
Get-ChildItem tools\warroom\state\learning
Get-Content tools\warroom\state\learning\global.md
Get-Content tools\warroom\state\learning\history.md
```

## Batasan (jujur)

- Supervisor lokal **tidak dapat menjamin** batas penagihan mutlak di sisi provider.
  Kendali berlaku untuk panggilan yang diluncurkan War Room; panggilan di luar itu tidak terpantau.
- Biaya aktual diambil dari `cost` yang dilaporkan OpenCode; bila tidak tersedia,
  digunakan perkiraan konservatif dan entri ditandai `unknown=true` (tidak dianggap nol).
- Model rutin: `deepseek/deepseek-flash`. Tarif token: harga resmi DeepSeek (diverifikasi 2026-10-11),
  mode peak untuk reservasi konservatif.
