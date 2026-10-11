# Buat-Shortcut.ps1 - buat shortcut Desktop yang membuka War Room LANGSUNG via PowerShell
# (tanpa cmd). Jalankan sekali: powershell -ExecutionPolicy Bypass -File tools\warroom\Buat-Shortcut.ps1
[CmdletBinding()]
param([string]$Name = 'LAUMOLOGY War Room')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script = Join-Path $PSScriptRoot 'Start-WarRoom.ps1'
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desktop ("$Name.lnk")

$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = 'powershell.exe'
$s.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $script + '"'
$s.WorkingDirectory = $root
$s.IconLocation = 'powershell.exe,0'
$s.Description = 'LAUMOLOGY War Room (PowerShell)'
$s.WindowStyle = 1
$s.Save()

Write-Host "Shortcut dibuat di Desktop: $lnk" -ForegroundColor Green
Write-Host "Klik dua kali shortcut itu -> terbuka PowerShell (bukan cmd)."
