# lib/AgentRunner.ps1 — pemanggil OpenCode nyata (non-interaktif) + parsing penggunaan token/biaya.
# Bergantung pada: Common.ps1, EventLog.ps1, BudgetManager.ps1 (dot-source di pemanggil).

function Get-OpenCodeCommand {
    $cmd = Get-Command opencode.cmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $ps = Get-Command opencode.ps1 -ErrorAction SilentlyContinue
    if ($ps) { return $ps.Source }
    $exe = Get-Command opencode -ErrorAction SilentlyContinue
    if ($exe) { return $exe.Source }
    return $null
}

function Test-OpenCodeAvailable {
    return [bool](Get-OpenCodeCommand)
}

function Get-OpenCodeVersion {
    $cmd = Get-OpenCodeCommand
    if (-not $cmd) { return $null }
    try { return ((& $cmd --version) 2>&1 | Select-Object -First 1).ToString().Trim() } catch { return $null }
}

function ConvertFrom-OpenCodeEvents {
    # Parse baris JSON dari `opencode run --format json` menjadi teks + token + biaya.
    param([Parameter(Mandatory)][string[]]$Lines)
    $textParts = @()
    $sessionId = $null
    $tokens = $null
    $costUSD = $null
    $sawFinish = $false
    foreach ($l in $Lines) {
        $t = $l.Trim()
        if (-not $t.StartsWith('{')) { continue }
        try { $ev = $t | ConvertFrom-Json } catch { continue }
        if ($ev.sessionID) { $sessionId = $ev.sessionID }
        switch ($ev.type) {
            'text' { if ($ev.part -and $ev.part.text) { $textParts += $ev.part.text } }
            'step_finish' {
                $sawFinish = $true
                if ($ev.part -and $ev.part.tokens) { $tokens = $ev.part.tokens }
                if ($ev.part -and $null -ne $ev.part.cost) { $costUSD = [double]$ev.part.cost }
            }
        }
    }
    return [pscustomobject]@{
        text      = ($textParts -join "`n")
        sessionId = $sessionId
        tokens    = $tokens
        costUSD   = $costUSD
        sawFinish = $sawFinish
    }
}

function Invoke-OpenCodeAgent {
    # Menjalankan satu panggilan agen OpenCode secara non-interaktif.
    param(
        [Parameter(Mandatory)][string]$Agent,
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Model = '',
        [string]$SessionId = '',
        [int]$TimeoutSec = 600,
        [switch]$Auto,
        [switch]$Stream
    )
    $cfg = Get-WarRoomConfig
    if (-not $Model) { $Model = $cfg.Model }
    $root = Get-WarRoomRoot
    if (-not (Test-OpenCodeAvailable)) {
        throw "opencode CLI tidak ditemukan di PATH."
    }

    # Shim opencode.cmd memotong argumen yang memuat baris baru. Untuk prompt
    # multi-baris, tulis ke berkas lalu kirim instruksi satu baris yang menunjuk
    # berkas tersebut (isi tetap utuh).
    $effectivePrompt = $Prompt
    if ($Prompt -match "[`r`n]") {
        $tmpDir = Join-Path (Get-WarRoomStateDir) 'tmp'
        if (-not (Test-Path -LiteralPath $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null }
        $pf = Join-Path $tmpDir ("prompt-{0}.md" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
        Set-Content -LiteralPath $pf -Value $Prompt -Encoding UTF8
        $effectivePrompt = "Instruksi lengkap ada di berkas '$pf'. Baca berkas itu lalu LANGSUNG kerjakan. JANGAN mengulang, menyalin, atau menyebut teks instruksinya; jangan minta klarifikasi. Keluarkan HANYA hasil akhirnya."
    }

    $startTs = Get-Date
    $tmpDir2 = Join-Path (Get-WarRoomStateDir) 'tmp'
    if (-not (Test-Path -LiteralPath $tmpDir2)) { New-Item -ItemType Directory -Path $tmpDir2 -Force | Out-Null }
    $streamFile = Join-Path $tmpDir2 ("stream-{0}.ndjson" -f [guid]::NewGuid().ToString('N').Substring(0, 8))

    $job = Start-Job -ArgumentList $root, $Agent, $Model, $effectivePrompt, $SessionId, [bool]$Auto, $streamFile -ScriptBlock {
        param($Root, $Agent, $Model, $Prompt, $SessionId, $Auto, $StreamFile)
        Set-Location -LiteralPath $Root
        $oCmd = (Get-Command opencode.cmd -ErrorAction SilentlyContinue).Source
        if (-not $oCmd) { $oCmd = (Get-Command opencode.ps1).Source }
        if (-not $oCmd) { $oCmd = 'opencode' }
        $a = @('run', '--format', 'json', '--agent', $Agent, '-m', $Model)
        if ($SessionId) { $a += @('--session', $SessionId) }
        if ($Auto) { $a += '--auto' }
        $a += $Prompt
        $out = & $oCmd @a 2>&1
        foreach ($ln in $out) { Add-Content -LiteralPath $StreamFile -Value "$ln" -Encoding UTF8 }
        Add-Content -LiteralPath $StreamFile -Value ("__WARROOM_EXIT__=" + $LASTEXITCODE) -Encoding UTF8
    }

    $timedOut = $false
    $streamed = $false
    $printedParts = @{}
    $offset = 0
    $buffer = ''
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $agentColor = Get-AgentColor -Agent $Agent
    $agentName = Get-AgentName -Agent $Agent
    $typingShown = $false
    $dots = @('.', '..', '...')
    $di = 0

    if ($Stream) {
        Write-Host ""
        Write-Host ("  {0} {1} ({2}) {3}" -f (Get-AgentIcon -Agent $Agent), $agentName, $Agent, (Get-Date).ToString('HH:mm')) -ForegroundColor $agentColor
    }

    while ($job.State -eq 'Running' -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
        if ($Stream -and (Test-Path -LiteralPath $streamFile)) {
            try {
                $fs = [System.IO.File]::Open($streamFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                $fs.Seek($offset, [System.IO.SeekOrigin]::Begin) | Out-Null
                $sr = New-Object System.IO.StreamReader($fs)
                $chunk = $sr.ReadToEnd()
                $offset = $fs.Position
                $sr.Dispose(); $fs.Dispose()
                if ($chunk) {
                    $buffer += $chunk
                    $segs = $buffer -split "`n"
                    if ($segs.Count -gt 1) {
                        for ($z = 0; $z -lt $segs.Count - 1; $z++) {
                            $t = $segs[$z].TrimEnd("`r").Trim()
                            if (-not $t.StartsWith('{')) { continue }
                            try {
                                $ev = $t | ConvertFrom-Json
                                if ($ev.type -eq 'text' -and $ev.part -and $ev.part.text) {
                                    $partId = [string]$ev.part.id
                                    $prev = if ($printedParts.ContainsKey($partId)) { [int]$printedParts[$partId] } else { 0 }
                                    $full = [string]$ev.part.text
                                    if ($full.Length -gt $prev) {
                                        if (-not $streamed) {
                                            if ($typingShown) { Write-Host ("`r" + (' ' * 70) + "`r") -NoNewline }
                                            Write-Host ("    > ") -NoNewline -ForegroundColor $agentColor
                                        }
                                        Write-Host $full.Substring($prev) -NoNewline -ForegroundColor $agentColor
                                        $printedParts[$partId] = $full.Length
                                        $streamed = $true
                                    }
                                }
                            } catch { }
                        }
                        $buffer = $segs[$segs.Count - 1]
                    }
                }
            } catch { }
        }
        if ($Stream -and -not $streamed) {
            Write-Host ("`r    {0} sedang mengetik{1}   " -f $agentName, $dots[$di % 3]) -NoNewline -ForegroundColor DarkGray
            $typingShown = $true
            $di++
        }
    }
    if ($job.State -eq 'Running') { $timedOut = $true; Stop-Job -Job $job }
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue

    # Flush akhir: cetak sisa teks yang belum tampil agar tidak hilang.
    if ($Stream -and (Test-Path -LiteralPath $streamFile)) {
        try {
            $fs = [System.IO.File]::Open($streamFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            $fs.Seek($offset, [System.IO.SeekOrigin]::Begin) | Out-Null
            $sr = New-Object System.IO.StreamReader($fs)
            $tail = $sr.ReadToEnd()
            $sr.Dispose(); $fs.Dispose()
            if ($tail) { $buffer += $tail }
            foreach ($seg in ($buffer -split "`n")) {
                $t = $seg.TrimEnd("`r").Trim()
                if (-not $t.StartsWith('{')) { continue }
                try {
                    $ev = $t | ConvertFrom-Json
                    if ($ev.type -eq 'text' -and $ev.part -and $ev.part.text) {
                        $partId = [string]$ev.part.id
                        $prev = if ($printedParts.ContainsKey($partId)) { [int]$printedParts[$partId] } else { 0 }
                        $full = [string]$ev.part.text
                        if ($full.Length -gt $prev) {
                            if (-not $streamed) {
                                if ($typingShown) { Write-Host ("`r" + (' ' * 70) + "`r") -NoNewline }
                                Write-Host ("    > ") -NoNewline -ForegroundColor $agentColor
                            }
                            Write-Host $full.Substring($prev) -NoNewline -ForegroundColor $agentColor
                            $printedParts[$partId] = $full.Length
                            $streamed = $true
                        }
                    }
                } catch { }
            }
        } catch { }
    }
    if ($Stream) { Write-Host "" }

    $raw = @()
    if (Test-Path -LiteralPath $streamFile) {
        try { $raw = @(Get-Content -LiteralPath $streamFile -Encoding UTF8) } catch { $raw = @() }
        Remove-Item -LiteralPath $streamFile -Force -ErrorAction SilentlyContinue
    }

    $exitCode = -1
    $lines = @()
    foreach ($l in $raw) {
        if ("$l" -match '^__WARROOM_EXIT__=(\-?\d+)$') { $exitCode = [int]$Matches[1]; continue }
        $lines += "$l"
    }
    $parsed = ConvertFrom-OpenCodeEvents -Lines $lines
    $duration = ((Get-Date) - $startTs).TotalSeconds

    $source = if ($null -ne $parsed.costUSD) { 'reported' } elseif ($parsed.tokens) { 'estimated' } else { 'unknown' }

    $result = [pscustomobject]@{
        agent      = $Agent
        model      = $Model
        sessionId  = $parsed.sessionId
        exitCode   = $exitCode
        timedOut   = $timedOut
        durationSec = [math]::Round($duration, 2)
        text       = $parsed.text
        tokens     = $parsed.tokens
        costUSD    = $parsed.costUSD
        costSource = $source
        streamed   = $streamed
        rawLines   = $lines
    }

    # Log tugas (teredaksi).
    $logName = "task-{0}-{1}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $Agent
    $logPath = Join-Path (Get-WarRoomStateDir) $logName
    $safe = ($lines | ForEach-Object { Protect-WarRoomSecret $_ }) -join "`n"
    Add-ContentSafe -Path $logPath -Value $safe
    $result | Add-Member -NotePropertyName logFile -NotePropertyValue $logName

    Write-WarRoomEvent -Category 'agent' -Actor $Agent -Message "panggil agen selesai (exit=$exitCode, timeout=$timedOut)" -Data @{
        model = $Model; durationSec = $result.durationSec; costSource = $source
        tokens = ($(if ($parsed.tokens) { "$($parsed.tokens.total)" } else { 'n/a' })); sessionId = $parsed.sessionId
    } | Out-Null
    return $result
}

function Invoke-OpenCodeAgentWithBudget {
    # Bungkus panggilan dengan reservasi anggaran + commit.
    param(
        [Parameter(Mandatory)][string]$Agent,
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Model = '',
        [string]$CycleId = '',
        [string]$Role = '',
        [string]$SessionId = '',
        [int]$TimeoutSec = 600,
        [int]$ExpectedInputTokens = 8000,
        [switch]$Auto,
        [switch]$Stream
    )
    $cfg = Get-WarRoomConfig
    if (-not $Model) { $Model = $cfg.Model }
    $resId = "res-$([guid]::NewGuid().ToString('N').Substring(0,12))"
    $est = Get-ConservativeEstimateIDR -Model $Model -ExpectedInputTokens $ExpectedInputTokens
    $r = Reserve-Budget -ReservationId $resId -EstimatedCostIDR $est -CycleId $CycleId -Model $Model
    if (-not $r.granted) {
        Write-WarRoomEvent -Category 'budget' -Level 'warn' -Message "panggilan ditolak anggaran ($($r.reason))" -Data @{ agent = $Agent; estIDR = $est } | Out-Null
        return [pscustomobject]@{ allowed = $false; reason = $r.reason; result = $null; estimatedIDR = $est }
    }
    try {
        $res = Invoke-OpenCodeAgent -Agent $Agent -Prompt $Prompt -Model $Model -SessionId $SessionId -TimeoutSec $TimeoutSec -Auto:$Auto -Stream:$Stream
        $entry = Commit-Budget -ReservationId $resId -CycleId $CycleId -Role $Role -Agent $Agent -Model $Model `
            -Operation 'agent-call' -SessionId $res.sessionId -Tokens $res.tokens `
            -ReportedCostUSD $(if ($null -ne $res.costUSD) { [double]$res.costUSD } else { -1 }) `
            -Source $res.costSource -Error $(if ($res.exitCode -ne 0) { "exit=$($res.exitCode); timeout=$($res.timedOut)" } else { '' }) `
            -Cancelled:$res.timedOut
        $res | Add-Member -NotePropertyName ledgerEntry -NotePropertyValue $entry
        return [pscustomobject]@{ allowed = $true; reason = 'ok'; result = $res; estimatedIDR = $est }
    } catch {
        Commit-Budget -ReservationId $resId -CycleId $CycleId -Role $Role -Agent $Agent -Model $Model `
            -Operation 'agent-call' -Source 'unknown' -Error $_.Exception.Message | Out-Null
        throw
    }
}
