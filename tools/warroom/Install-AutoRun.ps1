# Install-AutoRun.ps1 — pasang/lepas agar War Room otomatis jalan sendiri tiap laptop.
# Default: Scheduled Task saat logon. Alternatif: taruh .bat di folder Startup.
[CmdletBinding()]
param(
    [ValidateSet('Logon', 'Startup')][string]$Method = 'Logon',
    [int]$MaxCycles = 0,
    [switch]$Remove,
    [switch]$Hidden
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$loop = Join-Path $PSScriptRoot 'Invoke-AutonomousLoop.ps1'
$taskName = 'LAUMOLOGY War Room'
$startupDir = [Environment]::GetFolderPath('Startup')
$startupBat = Join-Path $startupDir 'LAUMOLOGY War Room.bat'
$maxArg = if ($MaxCycles -gt 0) { " -MaxCycles $MaxCycles" } else { '' }

if ($Remove) {
    try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch { }
    if (Test-Path -LiteralPath $startupBat) { Remove-Item -LiteralPath $startupBat -Force }
    Write-Host "AutoRun dihapus (task '$taskName' + startup bat bila ada)." -ForegroundColor Yellow
    return
}

if (-not (Test-Path -LiteralPath $loop)) { throw "Tidak menemukan $loop" }

$win = if ($Hidden) { '-WindowStyle Hidden ' } else { '-WindowStyle Minimized ' }
$arg = "-NoProfile $win-ExecutionPolicy Bypass -File `"$loop`"$maxArg"

if ($Method -eq 'Logon') {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Terpasang: Scheduled Task '$taskName' menjalankan War Room otomatis saat logon." -ForegroundColor Green
    Write-Host "  Repo  : $root"
    Write-Host "  Perintah: $arg"
    Write-Host "  Lepas : powershell -NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" -Remove"
} else {
    $content = "@echo off`r`ncd /d `"$root`"`r`npowershell $arg`r`n"
    Set-Content -LiteralPath $startupBat -Value $content -Encoding ASCII
    Write-Host "Terpasang di folder Startup: $startupBat" -ForegroundColor Green
    Write-Host "  Lepas: powershell -NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" -Remove"
}
