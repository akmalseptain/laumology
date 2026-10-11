@echo off
rem LAUMOLOGY War Room - launcher terminal komando (utamakan Windows Terminal).
cd /d "%~dp0"
where wt.exe >nul 2>nul
if %errorlevel%==0 (
    wt.exe -d "%~dp0" -p "Windows PowerShell" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\warroom\Start-WarRoom.ps1"
) else (
    echo Windows Terminal tidak ditemukan; memakai konsol biasa.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\warroom\Start-WarRoom.ps1"
    pause
)
