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
. (Join-Path $libDir 'ModelRouter.ps1')
. (Join-Path $libDir 'AgentRunner.ps1')
. (Join-Path $libDir 'DiscussionManager.ps1')
. (Join-Path $libDir 'PipelineManager.ps1')
. (Join-Path $libDir 'LearningManager.ps1')

Initialize-WarRoomState
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$cfg = Get-WarRoomConfig
$cyclesPerRun = if ($cfg.ContainsKey('CyclesPerRun')) { [int]$cfg.CyclesPerRun } else { 4 }
$maxRunMinutes = if ($cfg.ContainsKey('MaxRunMinutes')) { [int]$cfg.MaxRunMinutes } else { 180 }
$delaySec = if ($cfg.ContainsKey('InterCycleDelaySeconds')) { [int]$cfg.InterCycleDelaySeconds } else { 20 }
$executeDefault = if ($cfg.ContainsKey('ExecuteByDefault')) { [bool]$cfg.ExecuteByDefault } else { $true }
$autoCommit = if ($cfg.ContainsKey('AutoCommit')) { [bool]$cfg.AutoCommit } else { $false }
$autoPush = if ($cfg.ContainsKey('AutoPush')) { [bool]$cfg.AutoPush } else { $false }
$publishPaths = if ($cfg.ContainsKey('PublishPaths')) { @($cfg.PublishPaths) } else { @('.opencode', 'tools', 'routes', 'tests') }

if ($MaxCycles -le 0) { $MaxCycles = $cyclesPerRun }
if ($MaxMinutes -le 0) { $MaxMinutes = $maxRunMinutes }
$execute = (-not $DryRun) -and ($Execute -or $executeDefault)

function Publish-WarRoomChanges {
    # Commit + push otonom. Staging DIBATASI ke jalur pengembangan di $publishPaths
    # (plus modifikasi file yang sudah terlacak). File pribadi pengguna TIDAK disentuh.
    param([string]$CycleId = 'auto')
    Push-Location (Get-WarRoomRoot)
    try {
        & git add -u 2>&1 | Out-Null
        foreach ($p in $publishPaths) {
            if (Test-Path -LiteralPath $p) { & git add -- $p 2>&1 | Out-Null }
        }
        $staged = @(& git diff --cached --name-only 2>&1)
        if ($staged.Count -eq 0) {
            Write-Host "  Auto-publish: tidak ada perubahan untuk di-commit." -ForegroundColor DarkGray
            return $false
        }
        $msg = "chore(warroom): siklus otonom $CycleId"
        & git commit -m $msg 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Host "  Auto-commit gagal." -ForegroundColor Red; return $false }
        Write-WarRoomEvent -Category 'orchestrator' -Message "auto-commit $CycleId ($($staged.Count) file)" | Out-Null
        if ($autoPush) {
            $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
            # Selaraskan dengan remote dulu agar push berhasil (tanpa menulis ulang riwayat).
            $pullOut = & git pull --ff-only origin $branch 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  Sinkron remote (merge)..." -ForegroundColor DarkGray
                $pullOut = & git pull --no-rebase --no-edit origin $branch 2>&1
                if ($LASTEXITCODE -ne 0) {
                    & git merge --abort 2>&1 | Out-Null
                    Write-Host "  Auto-push DILEWATI: remote berbeda & tidak bisa digabung otomatis. Commit lokal disimpan." -ForegroundColor Yellow
                    Write-WarRoomEvent -Category 'git' -Level 'warn' -Message "auto-push dilewati (gabung gagal): $($pullOut -join ' ')" | Out-Null
                    return $false
                }
            }
            $pushOut = & git push origin $branch 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  Auto-push gagal: $($pushOut -join ' ')" -ForegroundColor Red
                Write-WarRoomEvent -Category 'error' -Level 'warn' -Message "auto-push gagal: $($pushOut -join ' ')" | Out-Null
                return $false
            }
            Write-Host "  Auto-push berhasil: origin/$branch" -ForegroundColor Green
            Write-WarRoomEvent -Category 'orchestrator' -Message "auto-push origin/$branch" | Out-Null
        }
        return $true
    } finally { Pop-Location }
}

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
        Write-Host ""
        Write-ProgressBar -Current $i -Total $MaxCycles -Label ("SIKLUS {0}/{1}   {2}   ({3:N0} menit)   |   {4}" -f $i, $MaxCycles, $cycleId, $elapsedMin, (Get-QuickStatusLine))

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

        # IMPLEMENTING (pipeline bertahap: plan -> investigate -> implement -> verify)
        Set-WarRoomState -State 'IMPLEMENTING' -Note 'pipeline' -Iteration $i | Out-Null
        $pipe = $null
        if (-not $execute) {
            Write-Host "  [dry-run] Tidak memanggil model." -ForegroundColor DarkGray
        } else {
            $pipe = Invoke-WarRoomPipeline -CycleId $cycleId -Item $next -ExtraContext "iterasi #$i" -TimeoutSec $CycleTimeoutSec -Auto
            Write-Host ("  Pipeline: plan={0} investigate={1}/2 implement={2} verify={3}/2 rekomendasi={4}" -f `
                $pipe.plan, $pipe.investigate, $pipe.implement, $pipe.verify, $pipe.recommendation)
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

        # AUTO-REPAIR: bila gate gagal, kirim error ke code-engineer lalu uji ulang (maks N).
        if ($execute -and $tcode -ne 0) {
            $maxRepair = if ($cfg.ContainsKey('MaxRepairAttempts')) { [int]$cfg.MaxRepairAttempts } else { 2 }
            $attempt = 0
            while ($tcode -ne 0 -and $attempt -lt $maxRepair) {
                $attempt++
                Write-Host ("  AUTO-REPAIR #{0}/{1}: mengirim error gate ke code-engineer..." -f $attempt, $maxRepair) -ForegroundColor Yellow
                Invoke-WarRoomBeep -Kind 'warn'
                $repPrompt = @"
Gate 'py -3.14 tools/quality_gate.py' GAGAL. Perbaiki PENYEBABNYA (jangan melemahkan/menghapus tes).
Ikuti AGENTS.md. Jangan commit/push. Jangan operasi Git destruktif.
Ringkasan error gate:
$tSummary
"@
                $ro = Invoke-OpenCodeAgentWithBudget -Agent $cfg.Agents.Code -Prompt $repPrompt -CycleId $cycleId -Role 'code-repair' -Model (Resolve-WarRoomModel -Agent $cfg.Agents.Code -Role 'code-repair' -Tier 'strong') -TimeoutSec $CycleTimeoutSec -Auto
                if ($ro.allowed -and $ro.result) { Write-AgentVoice -Agent $cfg.Agents.Code -Phase ("repair#$attempt") -Text $ro.result.text }
                Push-Location (Get-WarRoomRoot)
                try { $tout = & py -3.14 tools/quality_gate.py 2>&1; $tcode = $LASTEXITCODE } finally { Pop-Location }
                $tSummary = ($tout | Select-Object -Last 3) -join ' | '
                Write-Host ("  Gate ulang exit={0}: {1}" -f $tcode, $tSummary) -ForegroundColor $(if ($tcode -eq 0) { 'Green' } else { 'Red' })
                Write-WarRoomEvent -Category 'test' -Message "siklus $cycleId gate ulang #$attempt exit=$tcode" | Out-Null
            }
        }

        # REVIEWING
        Set-WarRoomState -State 'REVIEWING' -Note 'diff' -Iteration $i | Out-Null
        Write-Host ("  Diff: {0}" -f ((Get-GitDiffStat) -replace "`n", ' ; '))

        # LEARNING: rekam pelajaran dari hasil gate agar siklus berikutnya makin pintar.
        if ($execute -and (Get-Command Update-WarRoomLearning -ErrorAction SilentlyContinue)) {
            Update-WarRoomLearning -CycleId $cycleId -GateExit $tcode -GateTail $tSummary
        }

        # RECORDING
        Set-WarRoomState -State 'RECORDING' -Note 'catat hasil' -Iteration $i | Out-Null
        $outcome = if ($execute -and $pipe -and -not $pipe.plan) { 'no-plan' } elseif ($tcode -eq 0) { 'ok' } else { 'test-failed' }
        # RIWAYAT TUGAS: catat agar siklus berikutnya tidak mengulang pekerjaan ini.
        if ($execute -and $outcome -ne 'no-plan' -and (Get-Command Add-WarRoomTaskHistory -ErrorAction SilentlyContinue)) {
            $histTitle = if ($next) { $next.title } else { 'discovery peningkatan kecil' }
            Add-WarRoomTaskHistory -Title $histTitle -Outcome $outcome -CycleId $cycleId
        }
        # Hanya siklus eksekusi nyata yang dihitung terhadap batas harian.
        if ($execute) { Add-CycleRecord -CycleId $cycleId -Outcome $outcome }
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

    # PUBLISH otonom: setelah run selesai, commit + push ke origin (memicu deploy),
    # bila eksekusi nyata dan tidak berakhir error. AutoPush cukup sebagai saklar utama
    # (otomatis ikut commit), AutoCommit tetap didukung untuk sekadar commit lokal.
    if ($execute -and ($autoPush -or $autoCommit) -and $stopReason -ne 'error') {
        Write-Host "  PUBLISH: commit + push origin (deploy)..." -ForegroundColor Cyan
        Publish-WarRoomChanges -CycleId ("run-{0:yyyyMMdd-HHmmss}" -f (Get-Date)) | Out-Null
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
    if ($stopReason -eq 'error') { Invoke-WarRoomBeep -Kind 'error' } else { Invoke-WarRoomBeep -Kind 'ok' }
    Send-WarRoomToast -Title 'LAUMOLOGY War Room' -Text ("Run selesai ({0}) setelah {1} menit." -f $stopReason, $mins) | Out-Null
}
