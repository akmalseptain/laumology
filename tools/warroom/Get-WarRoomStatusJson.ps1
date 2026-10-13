# Get-WarRoomStatusJson.ps1 - emit status War Room sebagai JSON satu baris.
# Dipakai panel web HP (routes/warroom.py) agar tidak perlu menyalin logika
# status/anggaran/backlog ke Python: cukup baca fungsi yang sudah ada (read-only).
[CmdletBinding()]
param(
    [int]$EventsTail = 20
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$libDir = Join-Path $PSScriptRoot 'lib'
. (Join-Path $libDir 'Common.ps1')
. (Join-Path $libDir 'EventLog.ps1')
. (Join-Path $libDir 'StateManager.ps1')
. (Join-Path $libDir 'BudgetManager.ps1')
. (Join-Path $libDir 'BacklogManager.ps1')

$st = Get-WarRoomState
$ctrl = Get-WarRoomControl
$b = Get-BudgetStatus
$sum = Get-BacklogSummary
$next = $sum.next

$stateBlock = [ordered]@{
    state                = "$($st.state)"
    iteration            = [int]$st.iteration
    lastSuccessIteration = [int]$st.lastSuccessIteration
    note                 = "$($st.note)"
    nextAction           = "$($st.nextAction)"
    updatedAt            = "$($st.updatedAt)"
    startedAt            = "$($st.startedAt)"
    pid                  = "$($st.pid)"
}
$controlBlock = [ordered]@{
    pauseRequested = [bool]$ctrl.pauseRequested
    stopRequested  = [bool]$ctrl.stopRequested
    updatedAt      = "$($ctrl.updatedAt)"
}
$budgetBlock = [ordered]@{
    mode               = "$($b.mode)"
    ledgerHealthy      = [bool]$b.ledgerHealthy
    spentIDR           = [double]$b.spentIDR
    reservedIDR        = [double]$b.reservedIDR
    effectiveIDR       = [double]$b.effectiveIDR
    remainingIDR       = [double]$b.remainingIDR
    monthlyBudgetIDR   = [double]$b.monthlyBudgetIDR
    targetIDR          = [double]$b.targetIDR
    warningIDR         = [double]$b.warningIDR
    reducedIDR         = [double]$b.reducedIDR
    hardPauseIDR       = [double]$b.hardPauseIDR
}
$nextBlock = $null
if ($next) {
    $nextBlock = [ordered]@{
        id         = "$($next.id)"
        title      = "$($next.title)"
        severity   = "$($next.severity)"
        confidence = "$($next.confidence)"
        effort     = "$($next.effort)"
        status     = "$($next.status)"
    }
}
$backlogBlock = [ordered]@{
    total    = [int]$sum.total
    byStatus = $sum.byStatus
    next     = $nextBlock
}
# Ambil lebih banyak event untuk mendeteksi penanda rapat; tampilkan sebagian saja.
$scan = @(Get-WarRoomEvents -Tail 200)
$display = if ($scan.Count -gt $EventsTail) { $scan[($scan.Count - $EventsTail)..($scan.Count - 1)] } else { $scan }
$eventsBlock = @(
    $display | ForEach-Object {
        [ordered]@{
            ts       = "$($_.ts)"
            level    = "$($_.level)"
            category = "$($_.category)"
            actor    = "$($_.actor)"
            message  = "$($_.message)"
        }
    }
)

# Aktivitas nyata: bedakan LOOP / RAPAT / AGEN / DIAM, bukan sekadar status lama,
# supaya panel tahu ini sedang jalan atau tidak + hasil rapat terakhir.
$activeStates = @('STARTING', 'OBSERVING', 'INVESTIGATING', 'PLANNING', 'IMPLEMENTING',
    'TESTING', 'REVIEWING', 'RECORDING', 'OBSERVING_AGAIN', 'PAUSED')
$loopRunning = ($activeStates -contains "$($stateBlock.state)")
$warroomProcs = 0
try {
    $warroomProcs = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'WarRoomTask|AutonomousLoop' }).Count
} catch { $warroomProcs = 0 }

$rapatStartIdx = -1; $rapatEndIdx = -1; $rapatTopic = ''; $rapatResult = ''
for ($i = $scan.Count - 1; $i -ge 0; $i--) {
    $m = "$($scan[$i].message)"
    if ($rapatEndIdx -lt 0 -and $m -match "diskusi selesai topic='(?<t>.+?)' rounds=\d+ rekomendasi=(?<r>\S+)") {
        $rapatEndIdx = $i; $rapatTopic = $Matches['t']; $rapatResult = $Matches['r']
    }
    if ($rapatStartIdx -lt 0 -and $m -match "diskusi mulai topic='(?<t>.+?)'") {
        $rapatStartIdx = $i; if (-not $rapatTopic) { $rapatTopic = $Matches['t'] }
    }
}
$rapatRunning = ($rapatStartIdx -ge 0 -and $rapatStartIdx -gt $rapatEndIdx)

if ($loopRunning) {
    $kind = 'loop'; $running = $true
    $label = "Loop berjalan - siklus #$($stateBlock.iteration) (tahap $($stateBlock.state))"
} elseif ($rapatRunning) {
    $kind = 'rapat'; $running = $true
    $label = 'Rapat sedang berjalan' + $(if ($rapatTopic) { " - $rapatTopic" } else { '' })
} elseif ($warroomProcs -gt 0) {
    $kind = 'agen'; $running = $true
    $label = 'Agen sedang bekerja'
} else {
    $kind = 'idle'; $running = $false
    if ($rapatResult) { $label = "Rapat terakhir selesai ($rapatResult)" + $(if ($rapatTopic) { ": $rapatTopic" } else { '' }) }
    else { $label = 'Diam - tidak ada proses' }
}

$lastEventAgeSec = $null
if ($eventsBlock.Count -gt 0) {
    $lastTs = $eventsBlock[-1].ts
    try {
        $age = ((Get-Date).ToUniversalTime() - [datetimeoffset]::Parse($lastTs).UtcDateTime).TotalSeconds
        if ($age -lt 0) { $age = 0 }
        $lastEventAgeSec = [int]$age
    } catch { $lastEventAgeSec = $null }
}
$activityBlock = [ordered]@{
    kind            = $kind
    running         = $running
    label           = $label
    rapatRunning    = $rapatRunning
    rapatTopic      = $rapatTopic
    rapatResult     = $rapatResult
    warroomProcs    = $warroomProcs
    lastEventAgeSec = $lastEventAgeSec
}

# Feed "di balik layar": cuplikan suara agen terakhir (loop/rapat) untuk HP.
$voicePath = Join-Path (Get-WarRoomStateDir) 'voice.jsonl'
$voiceBlock = @()
if (Test-Path -LiteralPath $voicePath) {
    foreach ($line in @(Get-Content -LiteralPath $voicePath -Tail 12 -Encoding UTF8)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $o = $line | ConvertFrom-Json
            $t = "$($o.text)"
            if ($t.Length -gt 240) { $t = $t.Substring(0, 240) + '...' }
            $voiceBlock += [ordered]@{ ts = "$($o.ts)"; agent = "$($o.agent)"; phase = "$($o.phase)"; text = $t }
        } catch { }
    }
}

$out = [ordered]@{
    state    = $stateBlock
    control  = $controlBlock
    budget   = $budgetBlock
    backlog  = $backlogBlock
    events   = $eventsBlock
    activity = $activityBlock
    voice    = $voiceBlock
}
$out | ConvertTo-Json -Depth 12 -Compress
