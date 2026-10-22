@echo off
chcp 65001 >nul
title Master ESP32 - COM4 Flash
echo ═══════════════════════════════════════════
echo   ESP-NOW MASTER - COM17 Firmware Yukle
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
echo [2/2] COM17'a yukleniyor...
"%PIO%" run --target upload --upload-port COM17
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [HATA] Yukleme basarisiz! COM4 bagli mi?
    pause
    exit /b 1
)

echo.
echo ═══════════════════════════════════════════
echo   BASARILI - Master firmware COM4'a yuklendi
echo ═══════════════════════════════════════════
echo.
pause
