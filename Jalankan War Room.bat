@echo off
rem LAUMOLOGY War Room - luncurkan PowerShell di jendela terpisah (cmd langsung menutup).
cd /d "%~dp0"
start "LAUMOLOGY War Room" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\warroom\Start-WarRoom.ps1"
