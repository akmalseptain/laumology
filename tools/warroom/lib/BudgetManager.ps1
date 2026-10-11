# lib/BudgetManager.ps1 — buku besar penggunaan token + kendali anggaran (reservasi atomik, fail-closed).
# Sumber biaya: 'reported' (dari opencode) | 'estimated' (perkiraan lokal konservatif) | 'unknown'.

function Get-UsageLedgerPath { return (Join-Path (Get-WarRoomStateDir) 'usage-ledger.jsonl') }
function Get-ReservationsPath { return (Join-Path (Get-WarRoomStateDir) 'reservations.json') }
function Get-BudgetLockPath { return (Join-Path (Get-WarRoomStateDir) 'budget.lock') }

function Get-WarRoomRate {
    param([Parameter(Mandatory)][string]$Model)
    $cfg = Get-WarRoomConfig
    if ($cfg.Rates.ContainsKey($Model)) { return $cfg.Rates[$Model] }
    return $cfg.DefaultRate
}

function Get-ConservativeEstimateIDR {
    # Estimasi terburuk (semua input cache-miss, output maksimum).
    param(
        [Parameter(Mandatory)][string]$Model,
        [int]$ExpectedInputTokens = 8000,
        [int]$MaxOutputTokens = 0
    )
    $cfg = Get-WarRoomConfig
    if ($MaxOutputTokens -le 0) { $MaxOutputTokens = [int]$cfg.MaxOutputTokensPerCall }
    $rate = Get-WarRoomRate -Model $Model
    $usd = (($ExpectedInputTokens * [double]$rate.InputCacheMissPerMillionUSD) +
            ($MaxOutputTokens   * [double]$rate.OutputPerMillionUSD)) / 1000000.0
    $idr = $usd * [double]$cfg.UsdToIdr
    return [math]::Round($idr, 2)
}

function Get-UsageEntries {
    $path = Get-UsageLedgerPath
    if (-not (Test-Path -LiteralPath $path)) { return @() }
    $out = @()
    foreach ($l in (Get-Content -LiteralPath $path -Encoding UTF8)) {
        if ([string]::IsNullOrWhiteSpace($l)) { continue }
        $out += ($l | ConvertFrom-Json)
    }
    return $out
}

function Test-LedgerHealthy {
    # Fail-closed: ledger harus dapat dibaca & setiap baris valid.
    $path = Get-UsageLedgerPath
    if (-not (Test-Path -LiteralPath $path)) { return $true }
    try {
        foreach ($l in (Get-Content -LiteralPath $path -Encoding UTF8)) {
            if ([string]::IsNullOrWhiteSpace($l)) { continue }
            $null = $l | ConvertFrom-Json
        }
        return $true
    } catch {
        Write-WarRoomEvent -Category 'budget' -Level 'error' -Message "ledger tidak sehat: $($_.Exception.Message)" | Out-Null
        return $false
    }
}

function Get-Reservations {
    $path = Get-ReservationsPath
    $obj = Read-WarRoomJsonFile -Path $path -Default $null
    if ($null -eq $obj -or -not $obj.PSObject.Properties.Name.Contains('reservations')) {
        return @{}
    }
    $ht = @{}
    foreach ($p in $obj.reservations.PSObject.Properties) { $ht[$p.Name] = $p.Value }
    return $ht
}

function Get-BudgetSpentIDR {
    $sum = 0.0
    foreach ($e in (Get-UsageEntries)) {
        if ($null -ne $e.costIDR) { $sum += [double]$e.costIDR }
    }
    return [math]::Round($sum, 2)
}

function Get-BudgetReservedIDR {
    $sum = 0.0
    foreach ($k in (Get-Reservations).Keys) { $sum += [double](Get-Reservations)[$k].amountIDR }
    return [math]::Round($sum, 2)
}

function Get-BudgetMode {
    param([double]$EffectiveIDR)
    $cfg = Get-WarRoomConfig
    if ($EffectiveIDR -ge [double]$cfg.TargetAutomationBudgetIDR) { return 'paused' }
    if ($EffectiveIDR -ge [double]$cfg.ReducedModeThresholdIDR)   { return 'reduced' }
    if ($EffectiveIDR -ge [double]$cfg.WarningThresholdIDR)       { return 'warning' }
    return 'normal'
}

function Get-BudgetStatus {
    $cfg = Get-WarRoomConfig
    $spent = Get-BudgetSpentIDR
    $reserved = Get-BudgetReservedIDR
    $effective = [math]::Round($spent + $reserved, 2)
    $mode = Get-BudgetMode -EffectiveIDR $effective
    $hasHealthyLedger = Test-LedgerHealthy
    return [pscustomobject]@{
        spentIDR             = $spent
        reservedIDR          = $reserved
        effectiveIDR         = $effective
        remainingIDR         = [math]::Round([double]$cfg.MonthlyBudgetIDR - $effective, 2)
        automationRemaining  = [math]::Round([double]$cfg.TargetAutomationBudgetIDR - $effective, 2)
        mode                 = $mode
        ledgerHealthy        = $hasHealthyLedger
        monthlyBudgetIDR     = [double]$cfg.MonthlyBudgetIDR
        targetIDR            = [double]$cfg.TargetAutomationBudgetIDR
        warningIDR           = [double]$cfg.WarningThresholdIDR
        reducedIDR           = [double]$cfg.ReducedModeThresholdIDR
        hardPauseIDR         = [double]$cfg.HardPauseThresholdIDR
    }
}

function Test-BudgetAvailable {
    # Cek SEBELUM memanggil model. Fail-closed bila ledger tidak sehat.
    param([Parameter(Mandatory)][double]$EstimatedCostIDR)
    if (-not (Test-LedgerHealthy)) {
        Write-WarRoomEvent -Category 'budget' -Level 'error' -Message 'ledger tidak sehat -> tolak panggilan baru (fail-closed)' | Out-Null
        return $false
    }
    $cfg = Get-WarRoomConfig
    $status = Get-BudgetStatus
    $after = $status.effectiveIDR + $EstimatedCostIDR
    if ($after -gt [double]$cfg.HardPauseThresholdIDR) { return $false }
    if ($status.effectiveIDR -ge [double]$cfg.TargetAutomationBudgetIDR) { return $false }
    return $true
}

function Reserve-Budget {
    # Reservasi atomik. Mengembalikan objek { granted=true/false; reservationId; amountIDR; reason }.
    param(
        [Parameter(Mandatory)][string]$ReservationId,
        [Parameter(Mandatory)][double]$EstimatedCostIDR,
        [string]$CycleId = '',
        [string]$Model = ''
    )
    $result = Invoke-WithFileLock -LockPath (Get-BudgetLockPath) -Script {
        $cfg = Get-WarRoomConfig
        if (-not (Test-LedgerHealthy)) {
            return [pscustomobject]@{ granted = $false; reason = 'ledger-unhealthy'; reservationId = $ReservationId }
        }
        $res = Get-Reservations
        $spent = Get-BudgetSpentIDR
        $reserved = 0.0
        foreach ($k in $res.Keys) { $reserved += [double]$res[$k].amountIDR }
        $effective = $spent + $reserved
        if (($effective + $EstimatedCostIDR) -gt [double]$cfg.HardPauseThresholdIDR) {
            return [pscustomobject]@{ granted = $false; reason = 'hard-pause-threshold'; reservationId = $ReservationId; effectiveIDR = $effective }
        }
        if ($effective -ge [double]$cfg.TargetAutomationBudgetIDR) {
            return [pscustomobject]@{ granted = $false; reason = 'target-automation-reached'; reservationId = $ReservationId; effectiveIDR = $effective }
        }
        $res[$ReservationId] = [pscustomobject]@{
            amountIDR = [math]::Round($EstimatedCostIDR, 2)
            cycleId   = $CycleId
            model     = $Model
            ts        = Get-WarRoomUtcNow
        }
        $payload = [pscustomobject]@{ reservations = $res; updatedAt = Get-WarRoomUtcNow }
        Write-WarRoomJsonFile -Path (Get-ReservationsPath) -Object $payload
        return [pscustomobject]@{ granted = $true; reason = 'ok'; reservationId = $ReservationId; amountIDR = [math]::Round($EstimatedCostIDR, 2); effectiveIDR = $effective }
    }
    if ($null -eq $result) { $result = [pscustomobject]@{ granted = $false; reason = 'lock-failed'; reservationId = $ReservationId } }
    Write-WarRoomEvent -Category 'budget' -Message "reservasi $ReservationId" -Data @{ amountIDR = $EstimatedCostIDR; granted = $result.granted; reason = $result.reason } | Out-Null
    return $result
}

function Release-Budget {
    param([Parameter(Mandatory)][string]$ReservationId)
    Invoke-WithFileLock -LockPath (Get-BudgetLockPath) -Script {
        $res = Get-Reservations
        if ($res.ContainsKey($ReservationId)) {
            $res.Remove($ReservationId)
            Write-WarRoomJsonFile -Path (Get-ReservationsPath) -Object ([pscustomobject]@{ reservations = $res; updatedAt = Get-WarRoomUtcNow })
        }
    }
}

function Commit-Budget {
    # Rekonsiliasi reservasi dengan penggunaan aktual. Menulis entri ledger.
    param(
        [Parameter(Mandatory)][string]$ReservationId,
        [string]$CycleId = '',
        [string]$Role = '',
        [string]$Agent = '',
        [string]$Model = '',
        [string]$Operation = 'model-call',
        [string]$SessionId = '',
        $Tokens = $null,
        [double]$ReportedCostUSD = -1,
        [string]$Source = 'reported',
        [string]$Error = '',
        [switch]$Cancelled
    )
    $cfg = Get-WarRoomConfig
    $res = Get-Reservations
    $reservedAmount = 0.0
    if ($res.ContainsKey($ReservationId)) { $reservedAmount = [double]$res[$ReservationId].amountIDR }

    $costIDR = $null
    $costUSD = $null
    if ($Source -eq 'reported' -and $ReportedCostUSD -ge 0) {
        $costUSD = $ReportedCostUSD
        $costIDR = [math]::Round($ReportedCostUSD * [double]$cfg.UsdToIdr, 4)
    } elseif ($Source -eq 'estimated') {
        $costIDR = [math]::Round($reservedAmount, 4)
        $costUSD = [math]::Round($reservedAmount / [double]$cfg.UsdToIdr, 6)
    } else {
        # unknown: jangan menganggap nol. Pakai reservasi konservatif + tandai.
        $Source = 'unknown'
        $costIDR = [math]::Round($reservedAmount, 4)
        $costUSD = $null
    }

    $entry = [ordered]@{
        ts         = Get-WarRoomUtcNow
        cycleId    = $CycleId
        role       = $Role
        agent      = $Agent
        model      = $Model
        operation  = $Operation
        sessionId  = $SessionId
        tokens     = $Tokens
        costUSD    = $costUSD
        costIDR    = $costIDR
        source     = $Source
        error      = (Protect-WarRoomSecret $Error)
        cancelled  = [bool]$Cancelled
        unknown    = ($Source -eq 'unknown')
        usdToIdr   = [double]$cfg.UsdToIdr
        priceVerifiedDate = $cfg.PriceVerifiedDate
    }
    $line = $entry | ConvertTo-Json -Depth 12 -Compress
    Add-ContentSafe -Path (Get-UsageLedgerPath) -Value (Protect-WarRoomSecret $line)

    Release-Budget -ReservationId $ReservationId
    Write-WarRoomEvent -Category 'budget' -Message "commit $ReservationId ($Source)" -Data @{ costIDR = $costIDR; unknown = ($Source -eq 'unknown') } | Out-Null
    return $entry
}

function Invoke-WithBudgetGuard {
    # Helper: reservasi -> jalankan panggilan -> commit. Mengembalikan hasil panggilan.
    param(
        [Parameter(Mandatory)][string]$ReservationId,
        [Parameter(Mandatory)][scriptblock]$Call,
        [Parameter(Mandatory)][string]$Model,
        [string]$CycleId = '',
        [string]$Role = '',
        [string]$Agent = '',
        [int]$ExpectedInputTokens = 8000
    )
    $est = Get-ConservativeEstimateIDR -Model $Model -ExpectedInputTokens $ExpectedInputTokens
    $r = Reserve-Budget -ReservationId $ReservationId -EstimatedCostIDR $est -CycleId $CycleId -Model $Model
    if (-not $r.granted) {
        return [pscustomobject]@{ allowed = $false; reason = $r.reason; result = $null }
    }
    try {
        $result = & $Call
        return [pscustomobject]@{ allowed = $true; reason = 'ok'; result = $result }
    } finally {
        # Pemanggil bertanggung jawab memanggil Commit-Budget; bila tidak, reservasi tetap (aman).
    }
}
