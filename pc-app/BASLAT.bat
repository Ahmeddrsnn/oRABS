@echo off
title GLT v3 Master Control Panel
echo Uygulama baslatiliyor...
cd /d "%~dp0"
python src/main.py
if errorlevel 1 (
    echo.
    echo Bir hata olustu! Pencere kapanmadan once hatayi yukarida gorebilirsiniz.
    echo.
    pause
)
