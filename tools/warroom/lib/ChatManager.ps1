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
        # Rapat hanya diisi agen yang RELEVAN dengan topik (hemat biaya & fokus),
        # bukan semua agen. Lead memimpin, spesialis yang cocok ikut, reviewer menantang.
        $Agents = Select-WarRoomRelevantAgents -Topic $Topic
    }
    $Agents = @($Agents | Where-Object { $_ })
    if ($Rounds -le 0) { $Rounds = 1 }

    Write-Section -Title ("RAPAT: " + $Topic) -Color 'Cyan'
    Write-Host ("  (peserta: {0})" -f ($Agents -join ', ')) -ForegroundColor DarkGray
    Invoke-WarRoomBeep -Kind 'info'

    $transcript = "TOPIK: $Topic"
    $messages = @()
    $cycleId = 'rapat-' + (Get-Date -Format 'HHmmss')
    $tuning = Get-WarRoomTuning

    for ($r = 1; $r -le $Rounds; $r++) {
        foreach ($ag in $Agents) {
            $transcriptCtx = Limit-WarRoomText $transcript $tuning.FindingsMaxChars
            $prompt = @"
KARAKTER: $(Get-AgentPersona -Agent $ag)
Kamu IKUT RAPAT santai (bukan laporan formal). Ini obrolan sejauh ini:
$transcriptCtx

Balas sebagai '$ag' dalam BAHASA SEHARI-HARI, MAKSIMAL 2 kalimat. Tanggapi pesan terakhir (boleh setuju/nyela/bercanda/debat ringan). Tanpa bullet/heading. Jangan mengarang fakta.
"@
            $o = Invoke-OpenCodeAgentWithBudget -Agent $ag -Prompt $prompt -CycleId $cycleId -Role 'rapat' -Model (Resolve-WarRoomModel -Agent $ag -Role 'rapat' -Tier 'fast') -TimeoutSec $TimeoutSec -Auto:$Auto -Stream
            if ($o.allowed -and $o.result -and $o.result.text) {
                $txt = (($o.result.text -replace "\s+", ' ').Trim())
                Write-AgentVoice -Agent $ag -Text $txt
                $transcript += "`n${ag}: $txt"
                $messages += [pscustomobject]@{ agent = $ag; text = $txt }
            } elseif (-not $o.allowed) {
                Write-Host ("  ({0} dilewati: {1})" -f $ag, $o.reason) -ForegroundColor DarkGray
            }
        }
    }

    Write-Host ""
    Invoke-WarRoomBeep -Kind 'ok'

    # Persist notulen rapat agar 'replay' menampilkan rapat yang baru dibahas,
    # bukan rapat lama dari siklus loop sebelumnya.
    try { Out-WarRoomMinutes -Title ("Rapat: $Topic") -Messages $messages | Out-Null } catch { }

    # Simpan hasil rapat ke backlog agar loop mengerjakannya (rapat -> backlog -> loop).
    if ($env:WARROOM_CHAT_NO_BACKLOG -ne '1') {
        try {
            $desc = (($transcript -split "`r?`n" | Where-Object { $_ -match '^[a-z].*: ' } | Select-Object -First 6) -join ' | ')
            $item = Add-BacklogItem -Title $Topic -Description $desc -Evidence 'hasil rapat (rapat <topik>)' -Files @() -Benefit 'Tindak lanjut hasil rapat' -Severity 'medium' -Confidence 'medium' -Effort 'M' -Status 'open'
            Write-Host ("  ^ dimasukkan ke backlog: {0} - {1}  (loop akan mengerjakannya)" -f $item.id, $Topic) -ForegroundColor DarkGray
        } catch {
            Write-Host "  (gagal menambah backlog dari rapat)" -ForegroundColor DarkGray
        }
    }

    Send-WarRoomToast -Title 'LAUMOLOGY War Room' -Text ("Rapat '$Topic' selesai.") | Out-Null
    return $transcript
}
