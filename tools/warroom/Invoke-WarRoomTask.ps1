# Invoke-WarRoomTask.ps1 — menjalankan satu tugas agen (satu panggilan OpenCode) dengan kendali anggaran.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Agent,
    [string]$Prompt = '',
    [string]$PromptFile = '',
    [string]$CycleId = 'adhoc',
    [string]$Role = '',
    [string]$Model = '',
    [string]$SessionId = '',
    [int]$TimeoutSec = 600,
    [string]$ResultFile = '',
    [switch]$NoBudget,
    [switch]$Auto
)

$ErrorActionPreference = 'Stop'
$libDir = Join-Path $PSScriptRoot 'lib'
. (Join-Path $libDir 'Common.ps1')
. (Join-Path $libDir 'EventLog.ps1')
. (Join-Path $libDir 'StateManager.ps1')
. (Join-Path $libDir 'GitGuard.ps1')
. (Join-Path $libDir 'BudgetManager.ps1')
. (Join-Path $libDir 'AgentRunner.ps1')

Initialize-WarRoomState

if ($PromptFile) {
    if (-not (Test-Path -LiteralPath $PromptFile)) { throw "PromptFile tidak ditemukan: $PromptFile" }
    $Prompt = Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8
}
if (-not $Prompt) { throw "Prompt kosong." }

if (-not $ResultFile) {
    $ResultFile = Join-Path (Get-WarRoomStateDir) ("task-result-{0}.json" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
}

$result = $null
$ok = $false
try {
    if ($NoBudget) {
        $r = Invoke-OpenCodeAgent -Agent $Agent -Prompt $Prompt -Model $Model -SessionId $SessionId -TimeoutSec $TimeoutSec -Auto:$Auto
        $result = [ordered]@{
            ok = ($r.exitCode -eq 0); agent = $Agent; role = $Role; cycleId = $CycleId
            sessionId = $r.sessionId; text = $r.text; exitCode = $r.exitCode
            timedOut = $r.timedOut; costIDR = $null; costSource = $r.costSource
            tokens = $r.tokens
        }
        $ok = ($r.exitCode -eq 0)
    } else {
        $o = Invoke-OpenCodeAgentWithBudget -Agent $Agent -Prompt $Prompt -Model $Model -CycleId $CycleId -Role $Role -SessionId $SessionId -TimeoutSec $TimeoutSec -Auto:$Auto
        if (-not $o.allowed) {
            $result = [ordered]@{
                ok = $false; agent = $Agent; role = $Role; cycleId = $CycleId
                text = ''; exitCode = $null; budgetDenied = $true; reason = $o.reason; estimatedIDR = $o.estimatedIDR
            }
        } else {
            $r = $o.result
            $result = [ordered]@{
                ok = ($r.exitCode -eq 0); agent = $Agent; role = $Role; cycleId = $CycleId
                sessionId = $r.sessionId; text = $r.text; exitCode = $r.exitCode
                timedOut = $r.timedOut; costIDR = $r.ledgerEntry.costIDR; costSource = $r.ledgerEntry.source
                tokens = $r.tokens; estimatedIDR = $o.estimatedIDR
            }
            $ok = ($r.exitCode -eq 0)
        }
    }
} catch {
    $ok = $false
    $result = [ordered]@{
        ok = $false; agent = $Agent; role = $Role; cycleId = $CycleId
        error = (Protect-WarRoomSecret $_.Exception.Message)
    }
}

Write-WarRoomJsonFile -Path $ResultFile -Object $result
Write-Output ($result | ConvertTo-Json -Depth 10 -Compress)
if (-not $ok) { exit 1 } else { exit 0 }
