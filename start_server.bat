@echo off
title Apex Ceviri Sunucusu
cd /d "%~dp0"

:: Admin check
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ====================================================================
    echo   WARNING: NOT RUNNING AS ADMINISTRATOR!
    echo.
    echo   To capture the T key inside Apex Legends, Windows requires
    echo   this script to run with administrator rights.
    echo.
    echo   Please RIGHT-CLICK this file and select "Run as administrator".
    echo.
    echo   Continuing in normal mode in 3 seconds...
    echo ====================================================================
    ping 127.0.0.1 -n 4 >nul
)

echo ====================================================
echo   APEX LEGENDS SES CEVIRI SUNUCUSU BASLATILIYOR...
echo ====================================================
echo.

python server.py

if %errorlevel% neq 0 (
    echo.
    echo HATA: Sunucu baslatilamadi!
    echo Python ve gereksinimlerin yuklu oldugundan emin olun.
    pause
)
