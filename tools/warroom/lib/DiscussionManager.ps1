# lib/DiscussionManager.ps1 — diskusi multi-agen berbasis bukti (maks putaran terbatas, eksekusi nyata).

function Get-PowerShellExe {
    $p = Join-Path $PSHOME 'powershell.exe'
    if (Test-Path -LiteralPath $p) { return $p }
    return (Get-Command powershell).Source
}

function Start-WarRoomAgentProcess {
    param(
        [Parameter(Mandatory)][string]$Agent,
        [Parameter(Mandatory)][string]$Prompt,
        [string]$CycleId = 'adhoc',
        [string]$Role = '',
        [string]$Model = '',
        [int]$TimeoutSec = 600,
        [switch]$Auto,
        [switch]$NoBudget
    )
    $taskScript = Join-Path (Get-WarRoomToolDir) 'Invoke-WarRoomTask.ps1'
    $tmpDir = Join-Path (Get-WarRoomStateDir) 'tmp'
    if (-not (Test-Path -LiteralPath $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null }
    $id = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $promptFile = Join-Path $tmpDir "prompt-$id.txt"
    $resultFile = Join-Path (Get-WarRoomStateDir) "task-result-$id.json"
    Set-Content -LiteralPath $promptFile -Value $Prompt -Encoding UTF8

    $psExe = Get-PowerShellExe
    $args = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$taskScript`"",
        '-Agent', $Agent, '-PromptFile', "`"$promptFile`"", '-ResultFile', "`"$resultFile`"",
        '-CycleId', $CycleId, '-TimeoutSec', $TimeoutSec
    )
    if ($Role) { $args += @('-Role', $Role) }
    if ($Model) { $args += @('-Model', $Model) }
    if ($Auto) { $args += '-Auto' }
    if ($NoBudget) { $args += '-NoBudget' }

    $proc = Start-Process -FilePath $psExe -ArgumentList $args -NoNewWindow -PassThru
    return [pscustomobject]@{ process = $proc; resultFile = $resultFile; agent = $Agent; role = $Role }
}

function Wait-WarRoomProcesses {
    param([Parameter(Mandatory)]$Runs, [int]$TimeoutSec = 900)
    foreach ($r in $Runs) {
        if (-not $r.process.HasExited) {
            $null = $r.process.WaitForExit($TimeoutSec * 1000)
        }
    }
    $out = @()
    foreach ($r in $Runs) {
        $res = Read-WarRoomJsonFile -Path $r.resultFile -Default $null
        $out += [pscustomobject]@{ agent = $r.agent; role = $r.role; result = $res }
    }
    return $out
}

function Wait-WarRoomProcessesStreaming {
    # Seperti Wait-WarRoomProcesses, tapi mencetak pesan tiap agen begitu selesai
    # (terasa seperti diskusi berjalan) + spinner saat menunggu. Mengembalikan hasil.
    param(
        [Parameter(Mandatory)]$Runs,
        [string]$Phase = '',
        [int]$TimeoutSec = 900
    )
    $runList = @($Runs)
    $done = @{}
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $start = Get-Date
    $spin = @('|', '/', '-', '\')
    $si = 0
    while ($done.Count -lt $runList.Count -and (Get-Date) -lt $deadline) {
        foreach ($r in $runList) {
            if ($done.ContainsKey($r.resultFile)) { continue }
            if (Test-Path -LiteralPath $r.resultFile) {
                $res = Read-WarRoomJsonFile -Path $r.resultFile -Default $null
                if ($res) {
                    $done[$r.resultFile] = $true
                    Write-Host ("`r" + (' ' * 100) + "`r") -NoNewline
                    Write-AgentVoice -Agent $r.agent -Phase $Phase -Text $res.text
                }
            }
        }
        if ($done.Count -ge $runList.Count) { break }
        $pending = ($runList | Where-Object { -not $done.ContainsKey($_.resultFile) } | ForEach-Object { $_.agent }) -join ', '
        $secs = [int]((Get-Date) - $start).TotalSeconds
        if ($pending) {
            Write-Host ("`r  {0} [{1,3}s] menunggu: {2}" -f $spin[$si % 4], $secs, $pending) -NoNewline -ForegroundColor DarkGray
            $si++
        }
        Start-Sleep -Milliseconds 300
    }
    Write-Host ("`r" + (' ' * 100) + "`r") -NoNewline
    $results = @()
    foreach ($r in $runList) {
        $res = Read-WarRoomJsonFile -Path $r.resultFile -Default $null
        if ($res -and -not $done.ContainsKey($r.resultFile)) {
            Write-AgentVoice -Agent $r.agent -Phase $Phase -Text $res.text
        }
        $results += [pscustomobject]@{ agent = $r.agent; role = $r.role; result = $res }
    }
    return $results
}

function Invoke-WarRoomDiscussion {
    param(
        [Parameter(Mandatory)][string]$Topic,
        [Parameter(Mandatory)][string]$Problem,
        [string[]]$Agents = @(),
        [int]$MaxRounds = 0,
        [int]$MaxConcurrent = 0,
        [string]$CycleId = 'adhoc',
        [string]$Context = '',
        [int]$TimeoutSec = 600,
        [switch]$Auto
    )
    $cfg = Get-WarRoomConfig
    $tuning = Get-WarRoomTuning
    if ($MaxRounds -le 0) { $MaxRounds = [int]$cfg.MaxDiscussionRounds }
    if ($MaxConcurrent -le 0) { $MaxConcurrent = [int]$cfg.MaxConcurrentModelTasks }
    # Mode anggaran reduced: batasi konkurensi untuk menghemat biaya.
    if ((Get-BudgetStatus).mode -eq 'reduced' -and $MaxConcurrent -gt 1) { $MaxConcurrent = 1 }
    if ($Agents.Count -eq 0) {
        $Agents = @($cfg.Agents.Quant, $cfg.Agents.Code, $cfg.Agents.QA)
    }

    $messages = @()
    $rounds = 0

    # --- Putaran 1: usulan/penyelidikan independen (paralel terbatas) ---
    $rounds++
    $batches = @()
    for ($i = 0; $i -lt $Agents.Count; $i += $MaxConcurrent) {
        $batches += , @($Agents[$i..([math]::Min($i + $MaxConcurrent - 1, $Agents.Count - 1))])
    }
    foreach ($batch in $batches) {
        $runs = @()
        foreach ($ag in $batch) {
            $prompt = @"
KARAKTER: $(Get-AgentPersona -Agent $ag)
Perankan dirimu NATURAL seperti ngobrol di kantor: sapa rekan dengan nama depan, boleh nyela/bercanda/berdebat ringan, sesuaikan diksi dengan asal daerah (secukupnya). WAJIB: jujur, sertakan bukti path:line, jangan mengarang. (Agama/keluarga hanya latar.)

Anda berperan sebagai agen '$ag'. Selidiki masalah berikut SECARA INDEPENDEN dan read-only.
Sajikan temuan berbasis BUKTI (path:line, output uji nyata). Jangan mengubah berkas. Ringkas (<= 10 baris).

TOPIK: $Topic
KONTEKS: $Context
MASALAH:
$Problem

Format: ringkas, poin-poin, setiap klaim disertai bukti.
"@
            $runs += Start-WarRoomAgentProcess -Agent $ag -Prompt $prompt -CycleId $CycleId -Role $ag -Model (Resolve-WarRoomModel -Agent $ag -Role $ag -Tier 'fast') -TimeoutSec $TimeoutSec -Auto:$Auto
        }
        $collected = Wait-WarRoomProcessesStreaming -Runs $runs -Phase 'proposal' -TimeoutSec ($TimeoutSec + 120)
        foreach ($c in $collected) {
            $messages += [pscustomobject]@{
                round = $rounds; agent = $c.agent; role = $c.role
                phase = 'proposal'
                text = $(if ($c.result) { $c.result.text } else { '' })
                ok = $(if ($c.result) { $c.result.ok } else { $false })
                costIDR = $(if ($c.result) { $c.result.costIDR } else { $null })
                sessionId = $(if ($c.result) { $c.result.sessionId } else { $null })
            }
        }
    }

    # --- Putaran 2: tantangan/review independen (bila MaxRounds >= 2) ---
    if ($MaxRounds -ge 2) {
        $rounds++
        $synthesis = ($messages | Where-Object { $_.phase -eq 'proposal' } | ForEach-Object {
            "[$($_.agent)]`n$($_.text)"
        }) -join "`n`n"
        $synthesis = Limit-WarRoomText $synthesis $tuning.FindingsMaxChars
        $challenge = @"
KARAKTER: $(Get-AgentPersona -Agent $cfg.Agents.Reviewer)
Perankan natural & menantang, tapi tetap berbukti.

Anda adalah Independent Reviewer. Berikut temuan tim atas masalah berikut.
Tantang secara KRITIS: cari regresi, masalah keamanan, kerumitan tak perlu, dan klaim tanpa bukti. Ringkas.

TOPIK: $Topic
MASALAH:
$Problem

TEMUAN TIM:
$synthesis

WAJIB akhiri dengan satu baris: REKOMENDASI: TERIMA | REVISI | TOLAK
"@
        $r = Start-WarRoomAgentProcess -Agent $cfg.Agents.Reviewer -Prompt $challenge -CycleId $CycleId -Role 'reviewer' -Model (Resolve-WarRoomModel -Agent $cfg.Agents.Reviewer -Role 'reviewer' -Tier 'strong') -TimeoutSec $TimeoutSec -Auto:$Auto
        $col = Wait-WarRoomProcessesStreaming -Runs @($r) -Phase 'challenge' -TimeoutSec ($TimeoutSec + 120)
        foreach ($c in $col) {
            $messages += [pscustomobject]@{
                round = $rounds; agent = $cfg.Agents.Reviewer; role = 'reviewer'
                phase = 'challenge'
                text = $(if ($c.result) { $c.result.text } else { '' })
                ok = $(if ($c.result) { $c.result.ok } else { $false })
                costIDR = $(if ($c.result) { $c.result.costIDR } else { $null })
                sessionId = $(if ($c.result) { $c.result.sessionId } else { $null })
            }
        }
    }

    # Ekstraksi rekomendasi reviewer (bila ada).
    $recommendation = $null
    foreach ($m in $messages) {
        if ($m.phase -eq 'challenge' -and $m.text -match 'REKOMENDASI:\s*(TERIMA|REVISI|TOLAK)') {
            $recommendation = $Matches[1]
        }
    }

    $record = [ordered]@{
        topic          = $Topic
        cycleId        = $CycleId
        problem        = $Problem
        rounds         = $rounds
        maxRounds      = $MaxRounds
        maxConcurrent  = $MaxConcurrent
        recommendation = $recommendation
        messages       = $messages
        at             = Get-WarRoomUtcNow
    }
    $discPath = Join-Path (Get-WarRoomStateDir) ("discussion-{0}-{1}.json" -f $CycleId, (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Write-WarRoomJsonFile -Path $discPath -Object $record
    Write-WarRoomEvent -Category 'review' -Message "diskusi selesai topic='$Topic' rounds=$rounds rekomendasi=$recommendation" | Out-Null
    $record | Add-Member -NotePropertyName file -NotePropertyValue (Split-Path -Leaf $discPath)
    return $record
}
