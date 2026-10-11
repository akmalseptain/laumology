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

Initialize-WarRoomState

function Show-Banner {
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "                L A U M O L O G Y   W A R   R O O M" -ForegroundColor Cyan
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "  Rekayasa otonom . bukti nyata . peningkatan berkelanjutan" -ForegroundColor DarkGray
    Write-Host ""
}

function Show-Header {
    $st = Get-WarRoomState
    $snap = Get-GitSnapshot
    $cfg = Get-WarRoomConfig
    $cwd = Get-WarRoomRoot
    Write-Host ("  CWD     : {0}" -f $cwd) -ForegroundColor Gray
    Write-Host ("  Git     : {0} @ {1}  (staged={2} unstaged={3} untracked={4})" -f `
        $snap.branch, $snap.head, $snap.staged.Count, $snap.unstaged.Count, $snap.untracked.Count) -ForegroundColor Gray
    Write-Host ("  Iterasi : #{0}   Status: {1}   Model: {2}" -f $st.iteration, $st.state, $cfg.Model) -ForegroundColor Gray
    Write-Host ""
}

function Show-Status {
    $st = Get-WarRoomState
    $b = Get-BudgetStatus
    Write-Host "  --- STATUS ---" -ForegroundColor Cyan
    Write-Host ("  Status      : {0}" -f $st.state)
    Write-Host ("  Iterasi     : #{0}  (sukses terakhir: #{1})" -f $st.iteration, $st.lastSuccessIteration)
    Write-Host ("  Tindakan    : {0}" -f $st.nextAction)
    Write-Host ("  Anggaran    : mode={0}  terpakai=Rp{1:N0}  cadangan=Rp{2:N0}  sisa=Rp{3:N0}" -f `
        $b.mode, $b.spentIDR, $b.reservedIDR, $b.remainingIDR)
    Write-Host ("  Ambang      : warning=Rp{0:N0} reduced=Rp{1:N0} pause=Rp{2:N0}" -f `
        $b.warningIDR, $b.reducedIDR, $b.hardPauseIDR)
    Write-Host ("  Ledger sehat: {0}" -f $b.ledgerHealthy) -ForegroundColor $(if ($b.ledgerHealthy) { 'Green' } else { 'Red' })
}

function Show-Team {
    $cfg = Get-WarRoomConfig
    Write-Host "  --- TIM (peran logis -> agen OpenCode nyata) ---" -ForegroundColor Cyan
    Write-Host ("  Lead Engineer      -> {0}  (primary)" -f $cfg.Agents.Lead)
    Write-Host ("  Code Engineer      -> {0}  (subagent, edit)" -f $cfg.Agents.Code)
    Write-Host ("  Quant Analyst      -> {0}  (subagent, read-only)" -f $cfg.Agents.Quant)
    Write-Host ("  QA Engineer        -> {0}  (subagent, edit)" -f $cfg.Agents.QA)
    Write-Host ("  Independent Reviewer -> {0}  (subagent, read-only)" -f $cfg.Agents.Reviewer)
}

function Show-Backlog {
    $sum = Get-BacklogSummary
    Write-Host ("  --- BACKLOG (total={0}) ---" -f $sum.total) -ForegroundColor Cyan
    foreach ($k in $sum.byStatus.Keys) { Write-Host ("    {0}: {1}" -f $k, $sum.byStatus[$k]) }
    if ($sum.next) {
        Write-Host ("  Berikutnya : {0}  [{1}/{2}/eff={3}]  {4}" -f $sum.next.id, $sum.next.severity, $sum.next.confidence, $sum.next.effort, $sum.next.title) -ForegroundColor Yellow
    } else {
        Write-Host "  Tidak ada item terbuka." -ForegroundColor DarkGray
    }
}

function Show-Logs {
    param([int]$Tail = 20)
    Write-Host "  --- EVENT LOG (tail $Tail) ---" -ForegroundColor Cyan
    foreach ($e in (Get-WarRoomEvents -Tail $Tail)) {
        $color = switch ($e.level) { 'error' { 'Red' } 'warn' { 'Yellow' } default { 'Gray' } }
        Write-Host ("  [{0}] {1}/{2} {3}" -f $e.ts, $e.category, $e.actor, $e.message) -ForegroundColor $color
    }
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
        'ask <agen> <teks> kirim prompt ke agen (lead|code|quant|qa|reviewer)',
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
    $name = switch ($alias) {
        'lead'     { $cfg.Agents.Lead }
        'code'     { $cfg.Agents.Code }
        'quant'    { $cfg.Agents.Quant }
        'qa'       { $cfg.Agents.QA }
        'reviewer' { $cfg.Agents.Reviewer }
        default    { $p[0] }
    }
    $task = Join-Path (Get-WarRoomToolDir) 'Invoke-WarRoomTask.ps1'
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
        'exit'    { return $false }
        default   { Write-Host ("  Perintah tidak dikenal: {0}. Ketik 'help'." -f $cmd) -ForegroundColor Yellow }
    }
    return $true
}

# --- Main ---
Show-Banner
Show-Header

if ($Command) {
    Invoke-WarRoomCommand -Line $Command | Out-Null
    return
}
if ($NonInteractive) { return }

while ($true) {
    Write-Host ""
    Write-Host "warroom> " -NoNewline -ForegroundColor Cyan
    $line = Read-Host
    if ($null -eq $line) { break }
    $cont = Invoke-WarRoomCommand -Line $line
    if (-not $cont) { break }
}
Write-Host "  Keluar dari War Room." -ForegroundColor DarkGray
