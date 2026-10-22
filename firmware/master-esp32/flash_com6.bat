@echo off
chcp 65001 >nul
title Master ESP32 - COM6 Flash
echo ═══════════════════════════════════════════
echo   ESP-NOW MASTER - COM6 Firmware Yukle
echo ═══════════════════════════════════════════
echo.

cd /d "%~dp0"

set PIO=%USERPROFILE%\.platformio\penv\Scripts\pio.exe

if not exist "%PIO%" (
    echo [HATA] PlatformIO bulunamadi: %PIO%
    pause
    exit /b 1
)

echo [1/2] Derleniyor...
"%PIO%" run
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [HATA] Derleme basarisiz!
    pause
    exit /b 1
)

echo.
echo [2/2] COM6'ya yukleniyor...
"%PIO%" run --target upload --upload-port COM22
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [HATA] Yukleme basarisiz! COM6 bagli mi?
    pause
    exit /b 1
)

echo.
echo ═══════════════════════════════════════════
echo   BASARILI - Master firmware COM6'ya yuklendi
echo ═══════════════════════════════════════════
echo.
pause
