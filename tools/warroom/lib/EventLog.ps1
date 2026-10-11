# lib/EventLog.ps1 — event log JSONL War Room.
# Kategori: orchestrator | agent | shell | test | user | error | review | budget | state | git

function Write-WarRoomEvent {
    param(
        [Parameter(Mandatory)][string]$Category,
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet('info', 'warn', 'error')][string]$Level = 'info',
        $Data = $null,
        [string]$Actor = 'orchestrator'
    )
    $dir = Get-WarRoomStateDir
    $path = Join-Path $dir 'events.jsonl'
    $entry = [ordered]@{
        ts       = Get-WarRoomUtcNow
        level    = $Level
        category = $Category
        actor    = $Actor
        message  = (Protect-WarRoomSecret $Message)
        data     = $null
    }
    if ($null -ne $Data) {
        try {
            $json = $Data | ConvertTo-Json -Depth 12 -Compress
            $entry.data = (Protect-WarRoomSecret $json)
        } catch {
            $entry.data = (Protect-WarRoomSecret ([string]$Data))
        }
    }
    $line = ($entry | ConvertTo-Json -Depth 12 -Compress)
    Add-ContentSafe -Path $path -Value $line
    return $entry
}

function Get-WarRoomEvents {
    param([int]$Tail = 20)
    $path = Join-Path (Get-WarRoomStateDir) 'events.jsonl'
    if (-not (Test-Path -LiteralPath $path)) { return @() }
    $lines = Get-Content -LiteralPath $path -Encoding UTF8
    if ($Tail -gt 0 -and $lines.Count -gt $Tail) {
        $lines = $lines[($lines.Count - $Tail)..($lines.Count - 1)]
    }
    $out = @()
    foreach ($l in $lines) {
        if ([string]::IsNullOrWhiteSpace($l)) { continue }
        try { $out += ($l | ConvertFrom-Json) } catch { }
    }
    return $out
}
