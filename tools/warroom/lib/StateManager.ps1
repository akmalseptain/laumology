# lib/StateManager.ps1 — status supervisor persisten + kontrol pause/resume/stop + kunci single-instance.

$script:WarRoomValidStates = @(
    'STOPPED', 'STARTING', 'OBSERVING', 'INVESTIGATING', 'PLANNING',
    'IMPLEMENTING', 'TESTING', 'REVIEWING', 'RECORDING', 'OBSERVING_AGAIN',
    'PAUSED', 'ERROR', 'IDLE'
)

function Get-WarRoomStateFile {
    return (Join-Path (Get-WarRoomStateDir) 'supervisor.json')
}

function Get-WarRoomControlFile {
    return (Join-Path (Get-WarRoomStateDir) 'control.json')
}

function Initialize-WarRoomState {
    $sf = Get-WarRoomStateFile
    if (-not (Test-Path -LiteralPath $sf)) {
        Set-WarRoomState -State 'STOPPED' -Note 'init' -Iteration 0 | Out-Null
    }
    $cf = Get-WarRoomControlFile
    if (-not (Test-Path -LiteralPath $cf)) {
        Set-WarRoomControl -Clear | Out-Null
    }
}

function Get-WarRoomState {
    $sf = Get-WarRoomStateFile
    $st = Read-WarRoomJsonFile -Path $sf -Default $null
    if ($null -eq $st) {
        return [pscustomobject]@{
            state = 'STOPPED'; iteration = 0; updatedAt = $null; pid = $null
            note = ''; lastSuccessIteration = 0; nextAction = ''; startedAt = $null
        }
    }
    return $st
}

function Set-WarRoomState {
    param(
        [Parameter(Mandatory)]
        [ValidateScript({ $script:WarRoomValidStates -contains $_ })]
        [string]$State,
        [string]$Note = '',
        [int]$Iteration = -1,
        [string]$NextAction = '',
        [switch]$MarkSuccess
    )
    $sf = Get-WarRoomStateFile
    $cur = Get-WarRoomState
    $iter = if ($Iteration -ge 0) { $Iteration } else { [int]$cur.iteration }
    $lastSuccess = [int]$cur.lastSuccessIteration
    if ($MarkSuccess) { $lastSuccess = $iter }
    $startedAt = if ($cur.startedAt) { $cur.startedAt } else { Get-WarRoomUtcNow }
    if ($State -eq 'STARTING' -or $State -eq 'STOPPED') { $startedAt = Get-WarRoomUtcNow }
    $next = if ($PSBoundParameters.ContainsKey('NextAction')) { $NextAction } else { $cur.nextAction }
    $obj = [ordered]@{
        state                = $State
        iteration            = $iter
        updatedAt            = Get-WarRoomUtcNow
        pid                  = $PID
        note                 = (Protect-WarRoomSecret $Note)
        lastSuccessIteration = $lastSuccess
        nextAction           = (Protect-WarRoomSecret $next)
        startedAt            = $startedAt
    }
    Write-WarRoomJsonFile -Path $sf -Object $obj
    Write-WarRoomEvent -Category 'state' -Message "state=$State" -Data @{ iteration = $iter; note = $Note } | Out-Null
    return $obj
}

function Get-WarRoomControl {
    $cf = Get-WarRoomControlFile
    $c = Read-WarRoomJsonFile -Path $cf -Default $null
    if ($null -eq $c) {
        return [pscustomobject]@{ pauseRequested = $false; stopRequested = $false; updatedAt = $null }
    }
    return $c
}

function Set-WarRoomControl {
    param(
        [switch]$Pause,
        [switch]$Resume,
        [switch]$Stop,
        [switch]$Clear
    )
    $cf = Get-WarRoomControlFile
    $start = if ($Clear) {
        [pscustomobject]@{ pauseRequested = $false; stopRequested = $false }
    } else {
        Get-WarRoomControl
    }
    $pauseState = [bool]$start.pauseRequested
    $stopState = [bool]$start.stopRequested
    if ($Pause) { $pauseState = $true }
    if ($Resume) { $pauseState = $false; $stopState = $false }
    if ($Stop) { $stopState = $true; $pauseState = $false }
    $obj = [ordered]@{
        pauseRequested = $pauseState
        stopRequested  = $stopState
        updatedAt      = Get-WarRoomUtcNow
        by             = $PID
    }
    Write-WarRoomJsonFile -Path $cf -Object $obj
    Write-WarRoomEvent -Category 'orchestrator' -Message "control pause=$pauseState stop=$stopState" | Out-Null
    return $obj
}

function Test-WarRoomStopRequested { return [bool](Get-WarRoomControl).stopRequested }
function Test-WarRoomPauseRequested { return [bool](Get-WarRoomControl).pauseRequested }

function Test-WarRoomCanLaunch {
    # True bila supervisor boleh meluncurkan pekerjaan baru.
    $c = Get-WarRoomControl
    return ((-not [bool]$c.stopRequested) -and (-not [bool]$c.pauseRequested))
}

# --- Kunci single-instance supervisor ---
$script:WarRoomInstanceLock = $null

function Enter-WarRoomSingleInstance {
    $lockFile = Join-Path (Get-WarRoomStateDir) 'supervisor.lock'
    try {
        $script:WarRoomInstanceLock = [System.IO.File]::Open($lockFile, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $bytes = [System.Text.Encoding]::UTF8.GetBytes("$PID $(Get-WarRoomUtcNow)")
        $script:WarRoomInstanceLock.SetLength(0)
        $script:WarRoomInstanceLock.Write($bytes, 0, $bytes.Length)
        $script:WarRoomInstanceLock.Flush()
        return $true
    } catch {
        return $false
    }
}

function Exit-WarRoomSingleInstance {
    if ($script:WarRoomInstanceLock) {
        try { $script:WarRoomInstanceLock.Dispose() } catch { }
        $script:WarRoomInstanceLock = $null
    }
}
