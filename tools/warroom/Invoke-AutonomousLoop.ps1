# Invoke-AutonomousLoop.ps1 — supervisor otonom batch (satu run = beberapa siklus, lalu berhenti).
# Siklus: OBSERVING -> INVESTIGATING -> PLANNING -> IMPLEMENTING -> TESTING -> REVIEWING -> RECORDING -> OBSERVING AGAIN
# Dirancang untuk pemakaian manual (tanpa VPS): jalankan -> N siklus -> selesai dalam batas waktu.
[CmdletBinding()]
param(
    [int]$MaxCycles = 0,      # 0 = pakai CyclesPerRun dari config (default 4)
    [int]$MaxMinutes = 0,     # 0 = pakai MaxRunMinutes dari config (default 180)
    [int]$CycleTimeoutSec = 900,
    [switch]$Execute,         # paksa eksekusi nyata
    [switch]$DryRun,          # paksa tanpa panggilan model
    [switch]$Once             # satu siklus saja (abaikan jeda)
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
$cfg = Get-WarRoomConfig
$cyclesPerRun = if ($cfg.ContainsKey('CyclesPerRun')) { [int]$cfg.CyclesPerRun } else { 4 }
$maxRunMinutes = if ($cfg.ContainsKey('MaxRunMinutes')) { [int]$cfg.MaxRunMinutes } else { 180 }
$delaySec = if ($cfg.ContainsKey('InterCycleDelaySeconds')) { [int]$cfg.InterCycleDelaySeconds } else { 20 }
$executeDefault = if ($cfg.ContainsKey('ExecuteByDefault')) { [bool]$cfg.ExecuteByDefault } else { $true }

if ($MaxCycles -le 0) { $MaxCycles = $cyclesPerRun }
if ($MaxMinutes -le 0) { $MaxMinutes = $maxRunMinutes }
$execute = (-not $DryRun) -and ($Execute -or $executeDefault)

function Get-CyclesToday {
    $path = Join-Path (Get-WarRoomStateDir) 'cycles.jsonl'
    if (-not (Test-Path -LiteralPath $path)) { return 0 }
    $today = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
    $n = 0
    foreach ($l in (Get-Content -LiteralPath $path -Encoding UTF8)) {
        if ([string]::IsNullOrWhiteSpace($l)) { continue }
        try { $o = $l | ConvertFrom-Json; if ($o.date -eq $today) { $n++ } } catch { }
    }
    return $n
}

function Add-CycleRecord {
    param([string]$CycleId, [string]$Outcome)
    $path = Join-Path (Get-WarRoomStateDir) 'cycles.jsonl'
    $rec = [ordered]@{ date = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd'); ts = Get-WarRoomUtcNow; cycleId = $CycleId; outcome = $Outcome }
    Add-ContentSafe -Path $path -Value ($rec | ConvertTo-Json -Compress)
    Write-WarRoomEvent -Category 'orchestrator' -Message "siklus $CycleId selesai: $Outcome" | Out-Null
}

if (-not (Enter-WarRoomSingleInstance)) {
    Write-Host "  Supervisor lain sudah berjalan (kunci dimiliki proses lain). Batal." -ForegroundColor Red
    exit 2
}

$stopReason = 'max-cycles'
$runStart = Get-Date
Set-WarRoomState -State 'STARTING' -Note 'supervisor mulai' | Out-Null
Write-Host ("  LAUMOLOGY War Room mulai. Execute={0} MaxCycles={1} MaxMinutes={2}" -f [bool]$execute, $MaxCycles, $MaxMinutes) -ForegroundColor Cyan

try {
    for ($i = 1; $i -le $MaxCycles; $i++) {
        if (Test-WarRoomStopRequested) { $stopReason = 'stop-requested'; break }
        if (Test-WarRoomPauseRequested) {
            Set-WarRoomState -State 'PAUSED' -Note 'pause diminta' | Out-Null
            Write-Host "  PAUSED. Menunggu resume..." -ForegroundColor Yellow
            while (Test-WarRoomPauseRequested -and -not (Test-WarRoomStopRequested)) { Start-Sleep -Seconds 5 }
            if (Test-WarRoomStopRequested) { $stopReason = 'stop-requested'; break }
        }
        $elapsedMin = ((Get-Date) - $runStart).TotalMinutes
        if ($elapsedMin -ge $MaxMinutes) {
            $stopReason = 'run-time-limit'
            Write-Host ("  Batas waktu run tercapai ({0:N1} menit >= {1}). Berhenti." -f $elapsedMin, $MaxMinutes) -ForegroundColor Yellow
            break
        }
        $maxDaily = [int]$cfg.MaxCyclesPerDay
        if ((Get-CyclesToday) -ge $maxDaily) {
            $stopReason = 'daily-cycle-limit'; Write-Host "  Batas siklus harian tercapai." -ForegroundColor Yellow; break
        }
        $b = Get-BudgetStatus
        if ($b.mode -eq 'paused' -or -not $b.ledgerHealthy) {
            $stopReason = if (-not $b.ledgerHealthy) { 'ledger-unhealthy' } else { 'budget-paused' }
            Write-Host ("  Berhenti meluncurkan pekerjaan AI: mode={0} ledgerSehat={1}" -f $b.mode, $b.ledgerHealthy) -ForegroundColor Yellow
            break
        }

        $cycleId = "cyc-{0:yyyyMMdd-HHmmss}" -f (Get-Date)
        Write-Host ("`n  ===== Siklus {0} (#{1}) | {2:N0} menit berjalan =====" -f $cycleId, $i, $elapsedMin) -ForegroundColor Cyan

        # OBSERVING
        Set-WarRoomState -State 'OBSERVING' -Note 'snapshot git + anggaran' -Iteration $i | Out-Null
        $snap = Protect-UserChanges
        Write-Host ("  Git {0}@{1} staged={2} unstaged={3} untracked={4}" -f $snap.branch, $snap.head, $snap.staged.Count, $snap.unstaged.Count, $snap.untracked.Count)

        # INVESTIGATING / PLANNING
        Set-WarRoomState -State 'INVESTIGATING' -Note 'pilih backlog' -Iteration $i | Out-Null
        $next = Get-NextBacklogItem
        if ($next) {
            Write-Host ("  Berikutnya: {0} - {1}" -f $next.id, $next.title) -ForegroundColor Yellow
        } else {
            Write-Host "  Backlog kosong; siklus akan melakukan discovery." -ForegroundColor DarkGray
        }
        Set-WarRoomState -State 'PLANNING' -Note 'rencana siklus' -Iteration $i -NextAction ($(if ($next) { $next.id } else { 'discovery' })) | Out-Null

        # IMPLEMENTING
        Set-WarRoomState -State 'IMPLEMENTING' -Note 'eksekusi' -Iteration $i | Out-Null
        if (-not $execute) {
            Write-Host "  [dry-run] Tidak memanggil model." -ForegroundColor DarkGray
        } elseif ($next) {
            $prompt = @"
Anda Lead Engineer War Room. Kerjakan SATU peningkatan kecil dan aman untuk item backlog berikut.
Ikuti AGENTS.md (bahasa Indonesia, jangan ubah rumus keuangan tanpa bukti, jaga uji golden).
Jangan commit/push. Jangan operasi Git destruktif.

ITEM: $($next.id) - $($next.title)
EVIDENCE: $($next.evidence)
FILES: $($next.files -join ', ')
ACCEPTANCE: $($next.acceptance)

Lakukan: implementasi terfokus, lalu jalankan 'py -3.14 tools/quality_gate.py' dan laporkan berkas yang diubah + hasil nyata.
"@
            $o = Invoke-OpenCodeAgentWithBudget -Agent $cfg.Agents.Lead -Prompt $prompt -CycleId $cycleId -Role 'lead-engineer' -TimeoutSec $CycleTimeoutSec -Auto
            if (-not $o.allowed) {
                Write-Host "  Panggilan Lead ditolak anggaran: $($o.reason)" -ForegroundColor Yellow
            } elseif ($o.result.exitCode -ne 0) {
                Write-Host "  Panggilan Lead gagal (exit=$($o.result.exitCode), timeout=$($o.result.timedOut))." -ForegroundColor Red
            } else {
                Write-Host "  Lead Engineer selesai; perubahan diterapkan." -ForegroundColor Green
            }
        } else {
            $discPrompt = @"
Anda Lead Engineer War Room. Tidak ada item backlog terbuka.
Tugas: temukan SATU peningkatan kecil, aman, dan reversibel pada aplikasi LAUMOLOGY, LALU implementasikan.
Aturan: baca AGENTS.md; sertakan bukti path:line; jangan ubah rumus keuangan tanpa fixture; jangan tambah dependensi; jangan commit/push; jangan operasi Git destruktif.
Setelah selesai jalankan 'py -3.14 tools/quality_gate.py' dan laporkan berkas yang diubah + ringkasan. Bila tidak ada perubahan aman yang layak, nyatakan dan jangan ubah apa pun.
"@
            $o = Invoke-OpenCodeAgentWithBudget -Agent $cfg.Agents.Lead -Prompt $discPrompt -CycleId $cycleId -Role 'lead-engineer-discovery' -TimeoutSec $CycleTimeoutSec -Auto
            if ($o.allowed -and $o.result.exitCode -eq 0) {
                Write-Host "  Discovery+implementasi selesai." -ForegroundColor Green
            } else {
                Write-Host "  Discovery tidak menghasilkan perubahan (atau ditolak anggaran)." -ForegroundColor DarkGray
            }
        }

        # TESTING
        Set-WarRoomState -State 'TESTING' -Note 'unittest' -Iteration $i | Out-Null
        Push-Location (Get-WarRoomRoot)
        try {
            $tout = & py -3.14 tools/quality_gate.py 2>&1
            $tcode = $LASTEXITCODE
        } finally { Pop-Location }
        $tSummary = ($tout | Select-Object -Last 3) -join ' | '
        Write-Host ("  Gate exit={0}: {1}" -f $tcode, $tSummary) -ForegroundColor $(if ($tcode -eq 0) { 'Green' } else { 'Red' })
        Write-WarRoomEvent -Category 'test' -Message "siklus $cycleId gate exit=$tcode" -Data @{ tail = $tSummary } | Out-Null

        # REVIEWING
        Set-WarRoomState -State 'REVIEWING' -Note 'diff' -Iteration $i | Out-Null
        Write-Host ("  Diff: {0}" -f ((Get-GitDiffStat) -replace "`n", ' ; '))

        # RECORDING
        Set-WarRoomState -State 'RECORDING' -Note 'catat hasil' -Iteration $i | Out-Null
        $outcome = if ($tcode -eq 0) { 'ok' } else { 'test-failed' }
        Add-CycleRecord -CycleId $cycleId -Outcome $outcome
        Set-WarRoomState -State 'OBSERVING_AGAIN' -Note 'siap iterasi berikut' -Iteration $i -MarkSuccess:($tcode -eq 0) | Out-Null

        if ($Once) { $stopReason = 'once'; break }
        if ($i -lt $MaxCycles) {
            Write-Host ("  Jeda {0} detik sebelum siklus berikutnya..." -f $delaySec) -ForegroundColor DarkGray
            $remaining = $delaySec
            while ($remaining -gt 0) {
                if (Test-WarRoomStopRequested) { $stopReason = 'stop-requested'; break }
                if (((Get-Date) - $runStart).TotalMinutes -ge $MaxMinutes) { $stopReason = 'run-time-limit'; break }
                Start-Sleep -Seconds ([math]::Min(5, $remaining))
                $remaining -= 5
            }
            if ($stopReason -in @('stop-requested', 'run-time-limit')) { break }
        }
    }
} catch {
    Set-WarRoomState -State 'ERROR' -Note $_.Exception.Message | Out-Null
    Write-WarRoomEvent -Category 'error' -Level 'error' -Message "supervisor error: $($_.Exception.Message)" | Out-Null
    Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red
    $stopReason = 'error'
} finally {
    Set-WarRoomState -State 'STOPPED' -Note "berhenti: $stopReason" | Out-Null
    Exit-WarRoomSingleInstance
    $mins = [math]::Round(((Get-Date) - $runStart).TotalMinutes, 1)
    Write-Host ("  Supervisor berhenti ({0}) setelah {1} menit." -f $stopReason, $mins) -ForegroundColor Cyan
}
