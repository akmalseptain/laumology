# lib/ChatManager.ps1 - mode "rapat": agen bergantian dalam satu alur obrolan (interaktif).
function Invoke-WarRoomChat {
    param(
        [Parameter(Mandatory)][string]$Topic,
        [int]$Rounds = 1,
        [string[]]$Agents = @(),
        [int]$TimeoutSec = 180,
        [switch]$Auto
    )
    $cfg = Get-WarRoomConfig
    if (@($Agents).Count -eq 0) {
        $Agents = @($cfg.Agents.Lead, $cfg.Agents.Quant, $cfg.Agents.QA)
        if ($cfg.Agents.ContainsKey('Security')) { $Agents += $cfg.Agents.Security }
        $Agents += @($cfg.Agents.Code, $cfg.Agents.Reviewer)
    }
    $Agents = @($Agents | Where-Object { $_ })
    if ($Rounds -le 0) { $Rounds = 1 }

    Write-Section -Title ("RAPAT: " + $Topic) -Color 'Cyan'
    Write-Host ("  (peserta: {0})" -f ($Agents -join ', ')) -ForegroundColor DarkGray
    Invoke-WarRoomBeep -Kind 'info'

    $transcript = "TOPIK: $Topic"
    $cycleId = 'rapat-' + (Get-Date -Format 'HHmmss')

    for ($r = 1; $r -le $Rounds; $r++) {
        foreach ($ag in $Agents) {
            $prompt = @"
KARAKTER: $(Get-AgentPersona -Agent $ag)
Kamu IKUT RAPAT santai (bukan laporan formal). Ini obrolan sejauh ini:
$transcript

Balas sebagai '$ag' dalam BAHASA SEHARI-HARI, MAKSIMAL 2 kalimat. Tanggapi pesan terakhir (boleh setuju/nyela/bercanda/debat ringan). Tanpa bullet/heading. Jangan mengarang fakta.
"@
            $o = Invoke-OpenCodeAgentWithBudget -Agent $ag -Prompt $prompt -CycleId $cycleId -Role 'rapat' -TimeoutSec $TimeoutSec -Auto:$Auto -Stream
            if ($o.allowed -and $o.result -and $o.result.text) {
                $txt = (($o.result.text -replace "\s+", ' ').Trim())
                Write-AgentVoice -Agent $ag -Text $txt
                $transcript += "`n${ag}: $txt"
            } elseif (-not $o.allowed) {
                Write-Host ("  ({0} dilewati: {1})" -f $ag, $o.reason) -ForegroundColor DarkGray
            }
        }
    }

    Write-Host ""
    Invoke-WarRoomBeep -Kind 'ok'
    Send-WarRoomToast -Title 'LAUMOLOGY War Room' -Text ("Rapat '$Topic' selesai.") | Out-Null
    return $transcript
}
