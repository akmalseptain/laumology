@echo off
rem LAUMOLOGY War Room — launcher terminal komando.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\warroom\Start-WarRoom.ps1"
pause
