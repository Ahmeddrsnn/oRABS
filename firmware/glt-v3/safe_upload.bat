@echo off
REM Bulundugu klasorden dinamik calisir
set "SCRIPT_DIR=%~dp0"
set "PC_DIR=%SCRIPT_DIR%..\..\pc-app"

echo [SAFE UPLOAD] Paneli bilgilendiriyorum (Disconnect)...
type nul > "%PC_DIR%\upload_mode.flag"

echo [SAFE UPLOAD] 1 saniye bekleniyor...
timeout /t 1 /nobreak >nul

echo [SAFE UPLOAD] Upload baslatiliyor...
cd /d "%SCRIPT_DIR%"
"%USERPROFILE%\.platformio\penv\Scripts\pio.exe" run -t upload

echo [SAFE UPLOAD] Panel bilgilendiriliyor (Reconnect)...
del "%PC_DIR%\upload_mode.flag"

echo [SAFE UPLOAD] Islem tamamlandi!
pause
