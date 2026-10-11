# Invoke-AutonomousLoop.ps1 — supervisor otonom persisten (satu siklus rekayasa per iterasi).
# Siklus: OBSERVING -> INVESTIGATING -> PLANNING -> IMPLEMENTING -> TESTING -> REVIEWING -> RECORDING -> OBSERVING AGAIN
[CmdletBinding()]
param(
    [int]$MaxCycles = 0,
    [int]$IdleMinutes = 0,
    [int]$CycleTimeoutSec = 900,
    [switch]$Execute,
    [switch]$Once
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
if ($MaxCycles -le 0) { $MaxCycles = [int]$cfg.MaxCyclesPerDay }
if ($IdleMinutes -le 0) { $IdleMinutes = [int]$cfg.NormalIdleIntervalMinutes }

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
Set-WarRoomState -State 'STARTING' -Note 'supervisor mulai' | Out-Null
Write-Host "  LAUMOLOGY War Room supervisor mulai. Execute=$([bool]$Execute) MaxCycles=$MaxCycles" -ForegroundColor Cyan

try {
    for ($i = 1; $i -le $MaxCycles; $i++) {
        if (Test-WarRoomStopRequested) { $stopReason = 'stop-requested'; break }
        if (Test-WarRoomPauseRequested) {
            Set-WarRoomState -State 'PAUSED' -Note 'pause diminta' | Out-Null
            Write-Host "  PAUSED. Menunggu resume..." -ForegroundColor Yellow
            while (Test-WarRoomPauseRequested -and -not (Test-WarRoomStopRequested)) { Start-Sleep -Seconds 5 }
            if (Test-WarRoomStopRequested) { $stopReason = 'stop-requested'; break }
        }
        if ((Get-CyclesToday) -ge [int]$cfg.MaxCyclesPerDay) {
            $stopReason = 'daily-cycle-limit'; Write-Host "  Batas siklus harian tercapai." -ForegroundColor Yellow; break
        }
        $b = Get-BudgetStatus
        if ($b.mode -eq 'paused' -or -not $b.ledgerHealthy) {
            $stopReason = if (-not $b.ledgerHealthy) { 'ledger-unhealthy' } else { 'budget-paused' }
            Write-Host ("  Berhenti meluncurkan pekerjaan AI: mode={0} ledgerSehat={1}" -f $b.mode, $b.ledgerHealthy) -ForegroundColor Yellow
            break
        }

        $cycleId = "cyc-{0:yyyyMMdd-HHmmss}" -f (Get-Date)
        Write-Host ("`n  ===== Siklus {0} (#{1}) =====" -f $cycleId, $i) -ForegroundColor Cyan

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
            Write-Host "  Backlog kosong (belum ada item terverifikasi)." -ForegroundColor DarkGray
        }
        Set-WarRoomState -State 'PLANNING' -Note 'rencana siklus' -Iteration $i -NextAction ($(if ($next) { $next.id } else { 'discovery' })) | Out-Null

        # IMPLEMENTING
        Set-WarRoomState -State 'IMPLEMENTING' -Note 'eksekusi' -Iteration $i | Out-Null
        if (-not $Execute) {
            Write-Host "  [dry-run] Tidak memanggil model. Gunakan -Execute untuk eksekusi nyata." -ForegroundColor DarkGray
        } elseif ($next) {
            $prompt = @"
Anda Lead Engineer War Room. Kerjakan SATU peningkatan kecil dan aman untuk item backlog berikut.
Ikuti AGENTS.md (bahasa Indonesia, jangan ubah rumus keuangan tanpa bukti, jaga uji golden).
Jangan commit/push. Jangan operasi Git destruktif.

ITEM: $($next.id) - $($next.title)
EVIDENCE: $($next.evidence)
FILES: $($next.files -join ', ')
ACCEPTANCE: $($next.acceptance)

Lakukan: implementasi terfokus, lalu laporkan berkas yang diubah + ringkasan perubahan.
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
            Write-Host "  Tidak ada item backlog; lewati implementasi." -ForegroundColor DarkGray
        }

        # TESTING
        Set-WarRoomState -State 'TESTING' -Note 'unittest' -Iteration $i | Out-Null
        Push-Location (Get-WarRoomRoot)
        try {
            $tout = & py -3.14 -m unittest tests.test_engine 2>&1
            $tcode = $LASTEXITCODE
        } finally { Pop-Location }
        $tSummary = ($tout | Select-Object -Last 3) -join ' | '
        Write-Host ("  Test exit={0}: {1}" -f $tcode, $tSummary) -ForegroundColor $(if ($tcode -eq 0) { 'Green' } else { 'Red' })
        Write-WarRoomEvent -Category 'test' -Message "siklus $cycleId unittest exit=$tcode" -Data @{ tail = $tSummary } | Out-Null

        # REVIEWING
        Set-WarRoomState -State 'REVIEWING' -Note 'diff' -Iteration $i | Out-Null
        Write-Host ("  Diff: {0}" -f ((Get-GitDiffStat) -replace "`n", ' ; '))

        # RECORDING
        Set-WarRoomState -State 'RECORDING' -Note 'catat hasil' -Iteration $i | Out-Null
        $outcome = if ($tcode -eq 0) { 'ok' } else { 'test-failed' }
        Add-CycleRecord -CycleId $cycleId -Outcome $outcome
        Set-WarRoomState -State 'OBSERVING_AGAIN' -Note 'siap iterasi berikut' -Iteration $i -MarkSuccess:($tcode -eq 0) | Out-Null

        if ($Once) { $stopReason = 'once'; break }
        Write-Host ("  Idle {0} menit..." -f $IdleMinutes) -ForegroundColor DarkGray
        $remaining = $IdleMinutes * 60
        while ($remaining -gt 0) {
            if (Test-WarRoomStopRequested) { $stopReason = 'stop-requested'; break }
            Start-Sleep -Seconds ([math]::Min(5, $remaining))
            $remaining -= 5
        }
        if ($stopReason -eq 'stop-requested') { break }
    }
} catch {
    Set-WarRoomState -State 'ERROR' -Note $_.Exception.Message | Out-Null
    Write-WarRoomEvent -Category 'error' -Level 'error' -Message "supervisor error: $($_.Exception.Message)" | Out-Null
    Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red
    $stopReason = 'error'
} finally {
    Set-WarRoomState -State 'STOPPED' -Note "berhenti: $stopReason" | Out-Null
    Exit-WarRoomSingleInstance
    Write-Host "  Supervisor berhenti ($stopReason)." -ForegroundColor Cyan
}
