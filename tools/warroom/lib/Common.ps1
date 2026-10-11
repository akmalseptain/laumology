# lib/Common.ps1 — helper bersama War Room (path, IO, redaksi, kunci file, JSON).
# Kompatibel Windows PowerShell 5.1.

$script:WarRoomLibDir = $PSScriptRoot
$script:WarRoomRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path

function Get-WarRoomRoot {
    return $script:WarRoomRoot
}

function Get-WarRoomToolDir {
    return (Resolve-Path (Join-Path $script:WarRoomRoot 'tools\warroom')).Path
}

function Get-WarRoomStateDir {
    if ($env:WARROOM_STATE_DIR) {
        $d = $env:WARROOM_STATE_DIR
    } else {
        $d = Join-Path (Get-WarRoomToolDir) 'state'
    }
    if (-not (Test-Path -LiteralPath $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
    return $d
}

function Get-WarRoomConfig {
    $path = if ($env:WARROOM_CONFIG_PATH) { $env:WARROOM_CONFIG_PATH } else { Join-Path (Get-WarRoomToolDir) 'warroom.options.psd1' }
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Config tidak ditemukan: $path"
    }
    $cfg = Import-PowerShellDataFile -LiteralPath $path
    return $cfg
}

function Get-WarRoomStatePath {
    param([Parameter(Mandatory)][string]$Name)
    return (Join-Path (Get-WarRoomStateDir) $Name)
}

function Protect-WarRoomSecret {
    # Hapus rahasia umum dari teks sebelum masuk log.
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return $Text }
    $t = $Text
    $t = [regex]::Replace($t, '(?i)(sk-[A-Za-z0-9_\-]{8,})', 'sk-***REDACTED***')
    $t = [regex]::Replace($t, '(?i)(api[_-]?key\s*[=:]\s*)("?)[^"\s,}]+', '$1$2***REDACTED***')
    $t = [regex]::Replace($t, '(?i)(authorization\s*:\s*bearer\s+)[^\s"]+', '$1***REDACTED***')
    $t = [regex]::Replace($t, '(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}', '$1***REDACTED***')
    $t = [regex]::Replace($t, '(?i)(OPENAI_API_KEY|LLM_API_KEY|API_KEY|DEEPSEEK_API_KEY)\s*[=:]\s*[^\s,;}"]+', '$1=***REDACTED***')
    return $t
}

function Write-WarRoomJsonFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Object,
        [int]$Depth = 20
    )
    $json = $Object | ConvertTo-Json -Depth $Depth
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $tmp = "$Path.tmp.$PID"
    Set-Content -LiteralPath $tmp -Value $json -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Read-WarRoomJsonFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        $Default = $null
    )
    if (-not (Test-Path -LiteralPath $Path)) { return $Default }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
    return ($raw | ConvertFrom-Json)
}

function Invoke-WithFileLock {
    # Kunci lintas-proses berbasis file. Gagal cepat bila terkunci (untuk uji concurrency).
    param(
        [Parameter(Mandatory)][string]$LockPath,
        [Parameter(Mandatory)][scriptblock]$Script,
        [int]$TimeoutSeconds = 15
    )
    $dir = Split-Path -Parent $LockPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $fs = $null
    while ($true) {
        try {
            $fs = [System.IO.File]::Open($LockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            break
        } catch {
            if ((Get-Date) -ge $deadline) {
                throw "Gagal memperoleh kunci '$LockPath' dalam ${TimeoutSeconds}s (kemungkinan proses lain memegangnya)."
            }
            Start-Sleep -Milliseconds 50
        }
    }
    try {
        return (& $Script)
    } finally {
        if ($fs) { $fs.Dispose() }
    }
}

function Get-WarRoomUtcNow {
    return (Get-Date).ToUniversalTime().ToString('o')
}

function Get-AgentColor {
    param([string]$Agent)
    switch -Wildcard ($Agent) {
        '*lead*'    { 'Cyan' }
        '*code*'    { 'Green' }
        '*quant*'   { 'Yellow' }
        '*qa*'      { 'Magenta' }
        '*review*'  { 'Blue' }
        default     { 'White' }
    }
}

function Write-Section {
    # Header tahap/siklus yang dekoratif (ASCII agar aman di semua konsol).
    param(
        [Parameter(Mandatory)][string]$Title,
        [string]$Color = 'Cyan'
    )
    $pad = [Math]::Max(4, 58 - $Title.Length)
    Write-Host ""
    Write-Host ("  " + ('>' * 2) + " " + $Title + " " + ('<' * $pad)) -ForegroundColor $Color
}

function Write-ProgressBar {
    param([int]$Current, [int]$Total, [string]$Label = '')
    if ($Total -le 0) { $Total = 1 }
    $filled = [Math]::Min($Current, $Total)
    $bar = ('#' * $filled) + ('.' * ($Total - $filled))
    Write-Host ("  [" + $bar + "] " + $Label) -ForegroundColor Cyan
}

function Get-AgentIcon {
    # Ikon per agen. Emoji bila didukung, fallback ASCII bila WARROOM_NO_UNICODE.
    param([string]$Agent)
    if ($env:WARROOM_NO_UNICODE) {
        switch -Wildcard ($Agent) {
            '*lead*'   { return '[*]' }
            '*code*'   { return '[#]' }
            '*quant*'  { return '[Q]' }
            '*qa*'     { return '[?]' }
            '*review*' { return '[R]' }
            default    { return '[-]' }
        }
    }
    $cp = switch -Wildcard ($Agent) {
        '*lead*'   { 0x1F9E0 }
        '*code*'   { 0x1F4BB }
        '*quant*'  { 0x1F4CA }
        '*qa*'     { 0x1F50D }
        '*review*' { 0x1F6E1 }
        default    { 0x1F464 }
    }
    try { return [char]::ConvertFromUtf32($cp) } catch { return '[-]' }
}

function Get-AgentPersonaData {
    $path = Join-Path (Get-WarRoomToolDir) 'personas.psd1'
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try { return (Import-PowerShellDataFile -LiteralPath $path) } catch { return $null }
}

function Get-AgentName {
    param([string]$Agent)
    $p = Get-AgentPersonaData
    if ($p -and $p.ContainsKey($Agent)) { return $p[$Agent].Nama }
    return $Agent
}

function Get-AgentPersona {
    param([string]$Agent)
    $p = Get-AgentPersonaData
    if ($p -and $p.ContainsKey($Agent)) {
        $d = $p[$Agent]
        return ("Kamu adalah {0} ({1} th), {2}. Lulusan {3}. {4}. Beragama {5}. Hobi: {6}. Sifat: {7}. Gaya bicara: {8}." -f `
            $d.Nama, $d.Usia, $d.Peran, $d.Lulusan, $d.Keluarga, $d.Agama, $d.Hobi, $d.Sifat, $d.Gaya)
    }
    return ''
}

function Invoke-WarRoomBeep {
    param([ValidateSet('ok', 'info', 'warn', 'error')][string]$Kind = 'info')
    if ($env:WARROOM_NO_SOUND) { return }
    try {
        switch ($Kind) {
            'ok' { [console]::beep(880, 110); [console]::beep(1175, 110) }
            'info' { [console]::beep(700, 90) }
            'warn' { [console]::beep(520, 200) }
            'error' { [console]::beep(340, 280) }
        }
    } catch { }
}

function Write-StageProgress {
    param([Parameter(Mandatory)][string[]]$Stages, [int]$Current = 0, [string]$Color = 'Cyan')
    $parts = @()
    for ($i = 0; $i -lt $Stages.Count; $i++) {
        if ($i -lt $Current) { $parts += ('[v] ' + $Stages[$i]) }
        elseif ($i -eq $Current) { $parts += ('[>] ' + $Stages[$i]) }
        else { $parts += ('[ ] ' + $Stages[$i]) }
    }
    Write-Host ("  " + ($parts -join '   ')) -ForegroundColor $Color
}

function Send-WarRoomToast {
    param([string]$Title = 'LAUMOLOGY War Room', [string]$Text = '')
    if ($env:WARROOM_NO_TOAST) { return }
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        Add-Type -AssemblyName System.Drawing -ErrorAction Stop
        $ni = New-Object System.Windows.Forms.NotifyIcon
        $ni.Icon = [System.Drawing.SystemIcons]::Information
        $ni.Visible = $true
        $ni.ShowBalloonTip(5000, $Title, $Text, [System.Windows.Forms.ToolTipIcon]::Info)
        Start-Sleep -Milliseconds 400
        $ni.Dispose()
    } catch { }
}

function Out-WarRoomMinutes {
    # Notulen rapat: ringkasan tiap pembicara + keputusan. Disimpan .md di state/.
    param(
        [string]$Title = 'Rapat',
        $Messages,
        [string]$Decision = '',
        [string]$Id = ''
    )
    $name = if ($Id) { "notulen-$Id.md" } else { ("notulen-{0}.md" -f (Get-Date -Format 'yyyyMMdd-HHmmss')) }
    $path = Join-Path (Get-WarRoomStateDir) $name
    $lines = @("# Notulen: $Title", "", ("Waktu: " + (Get-WarRoomUtcNow)), "")
    foreach ($m in @($Messages)) {
        if (-not $m) { continue }
        $body = ($m.text -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 6) -join ' / '
        $lines += ("- **{0}**: {1}" -f $m.agent, $body)
    }
    if ($Decision) { $lines += "", ("**Keputusan:** " + $Decision) }
    $lines += "", ("Biaya rapat: " + (Get-BudgetStatus).spentIDR + " IDR (kumulatif)")
    Set-Content -LiteralPath $path -Value ($lines -join "`n") -Encoding UTF8
    return $path
}

function Get-QuickStatusLine {
    try {
        $b = Get-BudgetStatus
        $s = Get-WarRoomState
        return ("iter #{0} {1} | budget {2} Rp{3:N0}/Rp{4:N0}" -f `
            $s.iteration, $s.state, $b.mode, $b.effectiveIDR, $b.monthlyBudgetIDR)
    } catch { return '' }
}

function Write-AgentVoice {
    # Cetak pesan agen bergaya chat kantor (nama + waktu + isi). -Plain untuk gaya blok.
    param(
        [Parameter(Mandatory)][string]$Agent,
        [string]$Phase = '',
        [string]$Text = '',
        [switch]$Plain
    )
    if ([string]::IsNullOrWhiteSpace($Text)) { return }
    $color = Get-AgentColor -Agent $Agent
    $lines = @($Text -split "`r?`n")
    if ($Plain) {
        $label = if ($Phase) { "$Agent : $Phase" } else { $Agent }
        Write-Host ("  +-- [ {0} ]" -f $label) -ForegroundColor $color
        foreach ($ln in $lines) { Write-Host ("  | {0}" -f $ln) -ForegroundColor $color }
        Write-Host ("  +--") -ForegroundColor $color
        return
    }
    $time = (Get-Date).ToString('HH:mm')
    Write-Host ""
    Write-Host ("  {0} {1} ({2}) {3}" -f (Get-AgentIcon -Agent $Agent), (Get-AgentName -Agent $Agent), $Agent, $time) -ForegroundColor $color
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($i -eq 0) { Write-Host ("    > " + $lines[$i]) -ForegroundColor $color }
        else { Write-Host ("      " + $lines[$i]) -ForegroundColor $color }
    }
}

function Add-ContentSafe {
    # Append tahan akses bersamaan (retry singkat).
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Value,
        [int]$TimeoutSeconds = 10
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ($true) {
        try {
            Add-Content -LiteralPath $Path -Value $Value -Encoding UTF8
            return
        } catch {
            if ((Get-Date) -ge $deadline) { throw }
            Start-Sleep -Milliseconds 50
        }
    }
}
