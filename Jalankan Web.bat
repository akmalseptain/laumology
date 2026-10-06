@echo off
title LAUMOLOGY - IDX Trading Terminal
cd /d "%~dp0"
echo Menjalankan LAUMOLOGY...
echo.
echo   Di PC ini       : http://127.0.0.1:5000
echo   Dari HP (WiFi)  : lihat alamat LAN yang tercetak di bawah
echo   (Pastikan HP dan PC di jaringan WiFi yang sama)
echo.
echo Tekan CTRL+C untuk berhenti.
echo.
py webapp.py --host 0.0.0.0
pause
