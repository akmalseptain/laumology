# make_mascot.ps1 - buat tools\warroom\mascot.txt dari gambar.
# Utamakan 'ascii-image-converter' (rujukan neofetch #2259); fallback ke make_mascot.py.
[CmdletBinding()]
param(
    [string]$Image = 'referensimuka.png',
    [int]$Width = 90,
    [switch]$Color
)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$img = if ([System.IO.Path]::IsPathRooted($Image)) { $Image } else { Join-Path $root $Image }
$out = Join-Path $PSScriptRoot 'mascot.txt'
$env:Path = "$env:LOCALAPPDATA\Microsoft\WinGet\Links;" + $env:Path

if (-not (Test-Path -LiteralPath $img)) { Write-Host "Gambar tidak ditemukan: $img" -ForegroundColor Red; exit 1 }

if (Get-Command ascii-image-converter -ErrorAction SilentlyContinue) {
    $a = @($img, '-W', $Width, '--complex')
    if ($Color) { $a += '-C' }
    $art = (& ascii-image-converter @a 2>&1 | Out-String)
    [System.IO.File]::WriteAllText($out, $art, [System.Text.Encoding]::UTF8)
    Write-Host "OK (ascii-image-converter, color=$([bool]$Color)) -> $out" -ForegroundColor Green
} else {
    Write-Host "ascii-image-converter tidak ada; pakai make_mascot.py (fallback)." -ForegroundColor Yellow
    & py -3.14 (Join-Path $PSScriptRoot 'make_mascot.py') $img -Width $Width -Agg mean -Gamma 0.30 -Out $out
}
