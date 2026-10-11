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
