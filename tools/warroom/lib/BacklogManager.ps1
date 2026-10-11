# lib/BacklogManager.ps1 — backlog rekayasa persisten & pemrioritasan.

function Get-BacklogPath { return (Join-Path (Get-WarRoomStateDir) 'backlog.json') }
function Get-BacklogLockPath { return (Join-Path (Get-WarRoomStateDir) 'backlog.lock') }

function Get-Backlog {
    $obj = Read-WarRoomJsonFile -Path (Get-BacklogPath) -Default $null
    if ($null -eq $obj) {
        return [pscustomobject]@{ updatedAt = $null; items = @() }
    }
    if (-not $obj.PSObject.Properties.Name.Contains('items')) {
        return [pscustomobject]@{ updatedAt = $obj.updatedAt; items = @() }
    }
    return $obj
}

function Save-Backlog {
    param([Parameter(Mandatory)]$Backlog)
    $Backlog.updatedAt = Get-WarRoomUtcNow
    Write-WarRoomJsonFile -Path (Get-BacklogPath) -Object $Backlog
}

function Get-NextBacklogId {
    $b = Get-Backlog
    $max = 0
    foreach ($it in $b.items) {
        if ($it.id -match '^W-(\d+)$') {
            $n = [int]$Matches[1]
            if ($n -gt $max) { $max = $n }
        }
    }
    return ('W-{0:0000}' -f ($max + 1))
}

function Get-BacklogPriorityScore {
    param($Item)
    $sev = switch ("$($Item.severity)".ToLowerInvariant()) { 'critical' { 100 } 'high' { 70 } 'medium' { 40 } 'low' { 15 } default { 20 } }
    $conf = switch ("$($Item.confidence)".ToLowerInvariant()) { 'high' { 1.0 } 'medium' { 0.7 } 'low' { 0.4 } default { 0.5 } }
    $eff = switch ("$($Item.effort)".ToLowerInvariant()) { 's' { 1.0 } 'm' { 2.0 } 'l' { 3.5 } default { 2.0 } }
    return [math]::Round(($sev * $conf) / $eff, 3)
}

function Add-BacklogItem {
    param(
        [Parameter(Mandatory)][string]$Title,
        [string]$Description = '',
        [string]$Evidence = '',
        [string[]]$Files = @(),
        [string]$Benefit = '',
        [ValidateSet('critical', 'high', 'medium', 'low')][string]$Severity = 'medium',
        [ValidateSet('high', 'medium', 'low')][string]$Confidence = 'medium',
        [ValidateSet('S', 'M', 'L', 's', 'm', 'l')][string]$Effort = 'M',
        [string]$RegressionRisk = 'medium',
        [string]$Acceptance = '',
        [string]$Status = 'open'
    )
    $result = Invoke-WithFileLock -LockPath (Get-BacklogLockPath) -Script {
        $b = Get-Backlog
        $id = Get-NextBacklogId
        $item = [ordered]@{
            id             = $id
            title          = $Title
            description    = $Description
            evidence       = $Evidence
            files          = $Files
            benefit        = $Benefit
            severity       = $Severity
            confidence     = $Confidence
            effort         = $Effort.ToUpperInvariant()
            regressionRisk = $RegressionRisk
            acceptance     = $Acceptance
            status         = $Status
            testResult     = ''
            disposition    = ''
            note           = ''
            createdAt      = Get-WarRoomUtcNow
            updatedAt      = Get-WarRoomUtcNow
        }
        $b.items = @($b.items) + [pscustomobject]$item
        Save-Backlog -Backlog $b
        return $item
    }
    Write-WarRoomEvent -Category 'orchestrator' -Message "backlog ditambah $($result.id): $Title" | Out-Null
    return $result
}

function Update-BacklogItem {
    param(
        [Parameter(Mandatory)][string]$Id,
        [string]$Status = '',
        [string]$TestResult = '',
        [string]$Disposition = '',
        [string]$Note = ''
    )
    $setTestResult = $PSBoundParameters.ContainsKey('TestResult')
    $setDisposition = $PSBoundParameters.ContainsKey('Disposition')
    $result = Invoke-WithFileLock -LockPath (Get-BacklogLockPath) -Script {
        $b = Get-Backlog
        $found = $false
        foreach ($it in $b.items) {
            if ($it.id -eq $Id) {
                $found = $true
                if ($Status) { $it.status = $Status }
                if ($setTestResult) { $it.testResult = $TestResult }
                if ($setDisposition) { $it.disposition = $Disposition }
                if ($Note) { $it | Add-Member -NotePropertyName note -NotePropertyValue $Note -Force }
                $it.updatedAt = Get-WarRoomUtcNow
            }
        }
        if (-not $found) { return $null }
        Save-Backlog -Backlog $b
        return $true
    }
    if ($result) { Write-WarRoomEvent -Category 'orchestrator' -Message "backlog update $Id" | Out-Null }
    return $result
}

function Get-NextBacklogItem {
    $b = Get-Backlog
    $open = @($b.items | Where-Object { $_.status -in @('open', 'in_progress') })
    if ($open.Count -eq 0) { return $null }
    $scored = foreach ($it in $open) {
        $it | Add-Member -NotePropertyName priorityScore -NotePropertyValue (Get-BacklogPriorityScore -Item $it) -Force -PassThru
    }
    return ($scored | Sort-Object -Property priorityScore -Descending | Select-Object -First 1)
}

function Get-BacklogSummary {
    $b = Get-Backlog
    $byStatus = @{}
    foreach ($it in $b.items) {
        $s = if ($it.status) { $it.status } else { 'unknown' }
        if (-not $byStatus.ContainsKey($s)) { $byStatus[$s] = 0 }
        $byStatus[$s]++
    }
    return [pscustomobject]@{
        total    = @($b.items).Count
        byStatus = $byStatus
        next     = Get-NextBacklogItem
    }
}
