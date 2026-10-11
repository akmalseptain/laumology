@echo off
rem LAUMOLOGY War Room - launcher (buka dengan Windows PowerShell).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\warroom\Start-WarRoom.ps1"
pause
