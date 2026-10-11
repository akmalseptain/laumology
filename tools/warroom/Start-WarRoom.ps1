# Start-WarRoom.ps1 — terminal komando War Room (PowerShell) + status nyata.
[CmdletBinding()]
param(
    [string]$Command = '',
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Continue'
$libDir = Join-Path $PSScriptRoot 'lib'
. (Join-Path $libDir 'Common.ps1')
. (Join-Path $libDir 'EventLog.ps1')
. (Join-Path $libDir 'StateManager.ps1')
. (Join-Path $libDir 'GitGuard.ps1')
. (Join-Path $libDir 'BudgetManager.ps1')
. (Join-Path $libDir 'BacklogManager.ps1')
. (Join-Path $libDir 'AgentRunner.ps1')
. (Join-Path $libDir 'DiscussionManager.ps1')
. (Join-Path $libDir 'ChatManager.ps1')

Initialize-WarRoomState

# --- UTF-8 untuk logo Unicode (fallback plain bila tak didukung) ---
$script:UnicodeOK = $true
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { $script:UnicodeOK = $false }
if ($env:WARROOM_NO_UNICODE) { $script:UnicodeOK = $false }

$script:LogoUnicode = @()
$script:_logoPath = Join-Path (Get-WarRoomToolDir) 'logo.txt'
if (Test-Path -LiteralPath $script:_logoPath) {
    try {
        $script:LogoUnicode = ([System.IO.File]::ReadAllText($script:_logoPath, [System.Text.Encoding]::UTF8)) -split "`r?`n"
    } catch { $script:LogoUnicode = @() }
}
$script:LogoAscii = @(
    '  ============================================================',
    '                L A U M O L O G Y   W A R   R O O M',
    '  ============================================================'
)

# --- Warna: truecolor (Windows Terminal / VS Code) bila tersedia, else 16-warna ---
$script:TrueColor = [bool]($env:WT_SESSION -or $env:TERM_PROGRAM -or ($env:COLORTERM -match 'truecolor|24bit'))
function Write-Rgb {
    param([string]$Text, [int]$R, [int]$G, [int]$B, [string]$Fallback = 'Cyan')
    if ($script:TrueColor) {
        $esc = [char]27
        Write-Host ($esc + "[38;2;$R;$G;${B}m" + $Text + $esc + "[0m")
    } else {
        Write-Host $Text -ForegroundColor $Fallback
    }
}

function Show-Banner {
    Write-Host ""
    if ($script:UnicodeOK -and $script:LogoUnicode.Count -gt 0) {
        # Gradient vertikal: cyan -> biru -> violet -> magenta
        $n = [Math]::Max($script:LogoUnicode.Count - 1, 1)
        for ($k = 0; $k -lt $script:LogoUnicode.Count; $k++) {
            $t = $k / $n
            $r = [int](34 + ($t * 190))
            $g = [int](211 - ($t * 120))
            $b = [int](238 + ($t * 17))
            $fb = if ($k % 2 -eq 0) { 'Cyan' } else { 'Blue' }
            Write-Rgb -Text (' ' + $script:LogoUnicode[$k]) -R $r -G $g -B $b -Fallback $fb
        }
    } else {
        foreach ($l in $script:LogoAscii) { Write-Host $l -ForegroundColor Cyan }
    }
    Write-Host ""
    Write-Rgb -Text "        >>  A I   E N G I N E E R I N G   W A R   R O O M  <<" -R 255 -G 255 -B 255 -Fallback White
    Write-Host "        Rekayasa otonom . bukti nyata . peningkatan berkelanjutan" -ForegroundColor DarkGray
    Write-Host ""
}

function Show-Header {
    $st = Get-WarRoomState
    $snap = Get-GitSnapshot
    $cfg = Get-WarRoomConfig
    $cwd = Get-WarRoomRoot
    Write-Host "  CWD     : " -NoNewline -ForegroundColor DarkGray
    Write-Host $cwd -ForegroundColor Gray
    Write-Host "  Git     : " -NoNewline -ForegroundColor DarkGray
    Write-Host $snap.branch -NoNewline -ForegroundColor Green
    Write-Host (" @ {0}  (staged={1} unstaged={2} untracked={3})" -f $snap.head, $snap.staged.Count, $snap.unstaged.Count, $snap.untracked.Count) -ForegroundColor Gray
    Write-Host "  Iterasi : " -NoNewline -ForegroundColor DarkGray
    Write-Host ("#{0}  " -f $st.iteration) -NoNewline -ForegroundColor Yellow
    Write-Host ("Status: {0}  " -f $st.state) -NoNewline -ForegroundColor Cyan
    Write-Host ("Model: {0}" -f $cfg.Model) -ForegroundColor Magenta
    Write-Host ""
}

function Show-Status {
    $st = Get-WarRoomState
    $b = Get-BudgetStatus
    Write-Host "  --- STATUS ---" -ForegroundColor Cyan
    Write-Host "  Status      : " -NoNewline -ForegroundColor DarkGray
    Write-Host $st.state -ForegroundColor Cyan
    Write-Host ("  Iterasi     : #{0}  (sukses terakhir: #{1})" -f $st.iteration, $st.lastSuccessIteration) -ForegroundColor Gray
    Write-Host ("  Tindakan    : {0}" -f $st.nextAction) -ForegroundColor Gray
    $modeColor = switch ($b.mode) { 'normal' { 'Green' } 'warning' { 'Yellow' } 'reduced' { 'DarkYellow' } 'paused' { 'Red' } default { 'Gray' } }
    Write-Host "  Anggaran    : mode=" -NoNewline -ForegroundColor DarkGray
    Write-Host $b.mode -NoNewline -ForegroundColor $modeColor
    Write-Host ("  terpakai=Rp{0:N0}  cadangan=Rp{1:N0}  sisa=Rp{2:N0}" -f $b.spentIDR, $b.reservedIDR, $b.remainingIDR) -ForegroundColor Gray
    Write-Host ("  Ambang      : warning=Rp{0:N0} reduced=Rp{1:N0} pause=Rp{2:N0}" -f $b.warningIDR, $b.reducedIDR, $b.hardPauseIDR) -ForegroundColor DarkGray
    Write-Host "  Ledger sehat: " -NoNewline -ForegroundColor DarkGray
    Write-Host $b.ledgerHealthy -ForegroundColor $(if ($b.ledgerHealthy) { 'Green' } else { 'Red' })
}

function Show-Team {
    $cfg = Get-WarRoomConfig
    Write-Host "  --- TIM (peran logis -> agen OpenCode nyata) ---" -ForegroundColor Cyan
    $rows = @(
        @('Lead Engineer', $cfg.Agents.Lead, '(primary)'),
        @('Code Engineer', $cfg.Agents.Code, '(subagent, edit)'),
        @('Quant Analyst', $cfg.Agents.Quant, '(subagent, read-only)'),
        @('QA Engineer', $cfg.Agents.QA, '(subagent, edit)'),
        @('Independent Reviewer', $cfg.Agents.Reviewer, '(subagent, read-only)')
    )
    foreach ($r in $rows) {
        Write-Host ("  {0,-20} -> " -f $r[0]) -NoNewline -ForegroundColor Gray
        Write-Host ("{0,-16}" -f $r[1]) -NoNewline -ForegroundColor (Get-AgentColor -Agent $r[1])
        Write-Host (" {0}" -f $r[2]) -ForegroundColor DarkGray
    }
}

function Show-Backlog {
    $sum = Get-BacklogSummary
    Write-Host ("  --- BACKLOG (total={0}) ---" -f $sum.total) -ForegroundColor Cyan
    foreach ($k in $sum.byStatus.Keys) {
        $kc = switch ($k) { 'done' { 'Green' } 'open' { 'Yellow' } 'blocked' { 'Red' } 'rejected' { 'DarkGray' } default { 'Gray' } }
        Write-Host ("    {0}: {1}" -f $k, $sum.byStatus[$k]) -ForegroundColor $kc
    }
    if ($sum.next) {
        Write-Host ("  Berikutnya : {0}  [{1}/{2}/eff={3}]  {4}" -f $sum.next.id, $sum.next.severity, $sum.next.confidence, $sum.next.effort, $sum.next.title) -ForegroundColor Yellow
    } else {
        Write-Host "  Tidak ada item terbuka." -ForegroundColor DarkGray
    }
}

function Show-Replay {
    $dir = Get-WarRoomStateDir
    $f = Get-ChildItem -LiteralPath $dir -Filter 'notulen-*.md' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $f) {
        $f = Get-ChildItem -LiteralPath $dir -Filter 'discussion-*.json' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
    if ($f) {
        Write-Host ("  --- REPLAY: {0} ---" -f $f.Name) -ForegroundColor Cyan
        Get-Content -LiteralPath $f.FullName -Encoding UTF8 | ForEach-Object { Write-Host ("  " + $_) }
    } else {
        Write-Host "  Belum ada notulen/debat tersimpan." -ForegroundColor DarkGray
    }
}

function Show-Demo {
    # Pratinjau tampilan (data CONTOH, bukan hasil nyata) - tanpa biaya API.
    Write-Host "  --- DEMO TAMPILAN (data contoh, bukan hasil nyata) ---" -ForegroundColor Cyan
    $samples = @(
        @('lead-engineer', 'Oke tim, fokus ya. Bagas cek risiko input, Sari siapkan acceptance-nya.'),
        @('quant-analyst', 'Tunggu, ada yang janggal di routes/portfolio.py:97 - input aneh bisa bikin 500.'),
        @('qa-engineer', 'Eh tapi kalau capital-nya string gimana? Aku tambah tesnya ya.'),
        @('security-engineer', 'Ini bisa dieksploitasi ki, validasi ticker dicek dulu sebelum nyentuh cache.'),
        @('code-engineer', 'Udah gue beresin ya, pakai json_object + guard. Gate LULUS.'),
        @('reviewer', 'Saya belum yakin di bagian non-finite, tapi buktinya jelas. REKOMENDASI: TERIMA.'),
        @('lead-engineer', 'Contoh teks panjang untuk menguji wrapping: karena rapat tadi sempat melantur soal makan siang, saya ingatkan lagi supaya fokus ke satu peningkatan kecil yang aman, reversibel, dan berbukti path:line, lalu diuji lewat quality gate sebelum diterima.')
    )
    foreach ($s in $samples) { Write-AgentVoice -Agent $s[0] -Text $s[1] }
    Write-Host ""
    Write-StageProgress -Stages @('PLAN', 'INVESTIGATE', 'IMPLEMENT', 'VERIFY') -Current 2
    Write-ProgressBar -Current 3 -Total 4 -Label "SIKLUS 3/4  cyc-demo  (contoh)"
    Write-Host "  (Ini hanya pratinjau. Jalankan 'rapat <topik>' atau 'loop' untuk yang nyata.)" -ForegroundColor DarkGray
    Write-Host ""
}

function Show-Logs {
    param([int]$Tail = 20)
    Write-Host "  --- EVENT LOG (tail $Tail) ---" -ForegroundColor Cyan
    foreach ($e in (Get-WarRoomEvents -Tail $Tail)) {
        $color = switch ($e.level) { 'error' { 'Red' } 'warn' { 'Yellow' } default { 'Gray' } }
        Write-Host ("  [{0}] {1}/{2} {3}" -f $e.ts, $e.category, $e.actor, $e.message) -ForegroundColor $color
    }
}

function Show-Mascot {
    # Potret gaya blok (monokrom) dari tools\warroom\mascot.txt, di-center, warna cyan.
    $p = Join-Path (Get-WarRoomToolDir) 'mascot.txt'
    if (-not (Test-Path -LiteralPath $p)) { return }
    try { $txt = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8) } catch { return }
    $lines = @($txt -split "`r?`n" | ForEach-Object { $_.TrimEnd() })
    $cw = 100
    try { $cw = [Math]::Max(40, [Console]::WindowWidth - 1) } catch { }
    $wmax = ($lines | ForEach-Object { $_.Length } | Measure-Object -Maximum).Maximum
    $pad = if ($wmax -lt $cw) { [int](($cw - $wmax) / 2) } else { 0 }
    $prefix = ' ' * $pad
    Write-Host ""
    foreach ($ln in $lines) { Write-Host ($prefix + $ln) -ForegroundColor Cyan }
    Write-Host ""
}

function Show-Doctor {
    Write-Host "  --- DOCTOR ---" -ForegroundColor Cyan
    $checks = @()
    $checks += [pscustomobject]@{ name = 'opencode CLI'; ok = (Test-OpenCodeAvailable); detail = (Get-OpenCodeCommand) }
    $checks += [pscustomobject]@{ name = 'opencode versi'; ok = $true; detail = (Get-OpenCodeVersion) }
    $pv = try { (& py -3.14 -c "import sys;print(sys.version.split()[0])") } catch { $null }
    $checks += [pscustomobject]@{ name = 'py -3.14'; ok = [bool]$pv; detail = $pv }
    $gv = (Invoke-GitRaw @('--version')).Output.Trim()
    $checks += [pscustomobject]@{ name = 'git'; ok = [bool]$gv; detail = $gv }
    $b = Get-BudgetStatus
    $checks += [pscustomobject]@{ name = 'ledger anggaran'; ok = $b.ledgerHealthy; detail = ("mode=$($b.mode)") }
    $cfg = try { Get-WarRoomConfig; $true } catch { $false }
    $checks += [pscustomobject]@{ name = 'config psd1'; ok = [bool]$cfg; detail = 'warroom.options.psd1' }
    # --- Tampilan (HD) ---
    $cp = try { [Console]::OutputEncoding.CodePage } catch { 0 }
    $checks += [pscustomobject]@{ name = 'encoding UTF-8'; ok = ($cp -eq 65001); detail = ("codepage=$cp") }
    $tc = [bool]($env:WT_SESSION -or $env:TERM_PROGRAM -or ($env:COLORTERM -match 'truecolor|24bit'))
    $checks += [pscustomobject]@{ name = 'truecolor (gradient)'; ok = $tc; detail = $(if ($tc) { 'aktif' } else { 'fallback 16-warna' }) }
    $checks += [pscustomobject]@{ name = 'unicode/emoji'; ok = (-not $env:WARROOM_NO_UNICODE); detail = $(if ($env:WARROOM_NO_UNICODE) { 'dimatikan' } else { 'aktif' }) }
    foreach ($c in $checks) {
        $mark = if ($c.ok) { 'OK  ' } else { 'FAIL' }
        $color = if ($c.ok) { 'Green' } else { 'Red' }
        Write-Host ("  [{0}] {1}: {2}" -f $mark, $c.name, $c.detail) -ForegroundColor $color
    }
}

function Invoke-TestSuite {
    Write-Host "  --- TEST (py -3.14 -m unittest tests.test_engine) ---" -ForegroundColor Cyan
    Push-Location (Get-WarRoomRoot)
    try {
        $out = & py -3.14 -m unittest tests.test_engine 2>&1
        $code = $LASTEXITCODE
        $out | ForEach-Object { Write-Host "  $_" }
        Write-Host ("  exit={0}" -f $code) -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Red' })
        Write-WarRoomEvent -Category 'test' -Message "unittest exit=$code" -Data @{ output = ($out -join "`n") } | Out-Null
    } finally { Pop-Location }
}

function Show-Help {
    Write-Host "  --- PERINTAH ---" -ForegroundColor Cyan
    @(
        'help             tampilkan bantuan ini',
        'team             daftar agen',
        'status           status supervisor + anggaran',
        'backlog          ringkasan backlog',
        'diff             git diff --stat',
        'test             jalankan unittest',
        'logs             tail event log',
        'doctor           diagnostik lingkungan',
        'pause            minta jeda (setelah checkpoint aman)',
        'resume           lanjutkan',
        'stop             minta berhenti anggun',
        'discuss <topik>  jalankan diskusi multi-agen (nyata, berbiaya)',
        'ask <agen|all> <teks> kirim prompt ke agen (lead|code|quant|qa|reviewer) atau semua',
        'rapat <topik>    obrolan tim bergantian (interaktif, ala chat)',
        'demo             pratinjau tampilan (tanpa biaya API)',
        'replay           tampilkan notulen/debat terakhir',
        'loop             jalankan supervisor otonom (Invoke-AutonomousLoop)',
        'exit             keluar'
    ) | ForEach-Object { Write-Host ("  {0}" -f $_) }
}

function Invoke-WarRoomAsk {
    # Kirim prompt bebas ke satu agen (dengan kendali anggaran + log).
    param([string]$Text)
    if (-not $Text -or -not $Text.Trim()) {
        Write-Host "  Gunakan: ask <agen> <instruksi>  (agen: lead|code|quant|qa|reviewer)" -ForegroundColor Yellow
        return
    }
    $p = $Text.Trim() -split '\s+', 2
    if ($p.Count -lt 2) {
        Write-Host "  Butuh instruksi. Contoh: ask lead Perbaiki bug pada X" -ForegroundColor Yellow
        return
    }
    $cfg = Get-WarRoomConfig
    $alias = $p[0].ToLowerInvariant()
    $task = Join-Path (Get-WarRoomToolDir) 'Invoke-WarRoomTask.ps1'
    if ($alias -in @('all', 'semua', '*')) {
        $names = @($cfg.Agents.Lead, $cfg.Agents.Code, $cfg.Agents.Quant, $cfg.Agents.QA, $cfg.Agents.Reviewer)
        Write-Host ("  Mengirim prompt ke SEMUA agen: {0}" -f ($names -join ', ')) -ForegroundColor Cyan
        foreach ($n in $names) {
            Write-Host ("  -> {0}" -f $n) -ForegroundColor DarkGray
            & $task -Agent $n -Role $n -CycleId 'manual-all' -Prompt $p[1] -TimeoutSec 900
        }
        return
    }
    $name = switch ($alias) {
        'lead'     { $cfg.Agents.Lead }
        'code'     { $cfg.Agents.Code }
        'quant'    { $cfg.Agents.Quant }
        'qa'       { $cfg.Agents.QA }
        'reviewer' { $cfg.Agents.Reviewer }
        default    { $p[0] }
    }
    Write-Host ("  Menjalankan agen '{0}'..." -f $name) -ForegroundColor Cyan
    & $task -Agent $name -Role $name -CycleId 'manual' -Prompt $p[1] -TimeoutSec 900
}

function Invoke-WarRoomCommand {
    param([string]$Line)
    $line = $Line.Trim()
    if ($line.StartsWith('/')) { $line = $line.Substring(1) }
    if (-not $line) { return $true }
    $parts = $line.Split(' ', 2)
    $cmd = $parts[0].ToLowerInvariant()
    $arg = if ($parts.Count -gt 1) { $parts[1] } else { '' }
    switch ($cmd) {
        'help'    { Show-Help }
        'team'    { Show-Team }
        'status'  { Show-Status }
        'backlog' { Show-Backlog }
        'diff'    { Write-Host (Get-GitDiffStat) }
        'test'    { Invoke-TestSuite }
        'logs'    { Show-Logs }
        'doctor'  { Show-Doctor }
        'pause'   { Set-WarRoomControl -Pause | Out-Null; Write-Host "  Jeda diminta." -ForegroundColor Yellow }
        'resume'  { Set-WarRoomControl -Resume | Out-Null; Write-Host "  Dilanjutkan." -ForegroundColor Green }
        'stop'    { Set-WarRoomControl -Stop | Out-Null; Write-Host "  Berhenti diminta." -ForegroundColor Yellow }
        'discuss' {
            if (-not $arg) { Write-Host "  Gunakan: discuss <topik>" -ForegroundColor Yellow }
            else { Invoke-WarRoomDiscussion -Topic $arg -Problem $arg -CycleId 'manual' | Out-Null }
        }
        'loop' {
            $loop = Join-Path (Get-WarRoomToolDir) 'Invoke-AutonomousLoop.ps1'
            & $loop
        }
        'ask'     { Invoke-WarRoomAsk -Text $arg }
        'prompt'  { Invoke-WarRoomAsk -Text $arg }
        'replay'  { Show-Replay }
        'demo'    { Show-Demo }
        'rapat'   {
            if (-not $arg) { Write-Host "  Gunakan: rapat <topik>" -ForegroundColor Yellow }
            else { Invoke-WarRoomChat -Topic $arg | Out-Null }
        }
        'chat'    {
            if (-not $arg) { Write-Host "  Gunakan: rapat <topik>" -ForegroundColor Yellow }
            else { Invoke-WarRoomChat -Topic $arg | Out-Null }
        }
        'exit'    { return $false }
        default   { Write-Host ("  Perintah tidak dikenal: {0}. Ketik 'help'." -f $cmd) -ForegroundColor Yellow }
    }
    return $true
}

# --- Main ---
Show-Banner
if (Test-Path -LiteralPath (Join-Path (Get-WarRoomToolDir) 'mascot.txt')) { Show-Mascot }
Show-Header

if ($Command) {
    Invoke-WarRoomCommand -Line $Command | Out-Null
    return
}
if ($NonInteractive) { return }

while ($true) {
    Write-Host ""
    $qs = Get-QuickStatusLine
    if ($qs) { Write-Host ("  " + $qs) -ForegroundColor DarkGray }
    Write-Host "warroom> " -NoNewline -ForegroundColor Cyan
    $line = Read-Host
    if ($null -eq $line) { break }
    $cont = Invoke-WarRoomCommand -Line $line
    if (-not $cont) { break }
}
Write-Host "  Keluar dari War Room." -ForegroundColor DarkGray
