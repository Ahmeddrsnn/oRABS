@echo off
REM ═══════════════════════════════════════════════════════════════════
REM  Ultra GITS — Tek tıkla build + setup üretimi
REM  ────────────────────────────────────────────────────────────────
REM  Ne yapar:
REM    1) Eski dist\, build\, installer_output\ klasörlerini siler
REM    2) PyInstaller ile GloveTestSystem.spec derler → dist\GloveTestSystem\
REM    3) Inno Setup (ISCC.exe) ile installer.iss derler
REM       → installer_output\GloveTestSystem_v1.0.0_Setup.exe
REM    4) installer_output\ klasörünü Explorer'da açar
REM  ────────────────────────────────────────────────────────────────
REM  Ön koşullar:
REM    * Python (PATH'te)
REM    * PyInstaller (pip install pyinstaller — spec zaten hazır)
REM    * Inno Setup 6+ kurulu olmalı
REM      Varsayılan yol: C:\Program Files (x86)\Inno Setup 6\ISCC.exe
REM      Yoksa: https://jrsoftware.org/isdl.php
REM  ────────────────────────────────────────────────────────────────
REM  ÖNEMLİ — "sıfır durum" garantisi (dev verisi paketlenmez):
REM    * GloveTestSystem.spec  → assets/models/ (GLB) DAHIL EDILMEZ
REM    * installer.iss         → config/settings.json, database\*.db,
REM                              reports\*, batches\* PAKETE GİRMEZ
REM    * Uygulama ilk açılışta boş DB + admin/Admin123! üretir
REM      (bkz. src\core\database.py → _create_default_admin)
REM ═══════════════════════════════════════════════════════════════════

setlocal enableextensions
cd /d "%~dp0"

REM ── Değiştirilebilir sabitler ───────────────────────────────────
set "APP_NAME=GloveTestSystem"
set "VERSION=1.0.0"
REM ── Inno Setup ISCC.exe yolu (kuruluysa değiştirme gerekmez) ────
set "ISCC="
for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
    "%ProgramFiles%\Inno Setup 5\ISCC.exe"
    "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
    "%LocalAppData%\Microsoft\WinGet\Packages\JRSoftware.InnoSetup_Microsoft.Winget.Source_8wekyb3d8bbwe\ISCC.exe"
) do if not defined ISCC if exist %%P set "ISCC=%%~P"
if not defined ISCC (
    for /f "delims=" %%I in ('where iscc 2^>nul') do if not defined ISCC set "ISCC=%%I"
)

echo.
echo ================================================================
echo   Ultra GITS v%VERSION% - Build ^& Setup
echo ================================================================
echo.

REM ── 1) Temizlik ────────────────────────────────────────────────
echo [1/3] Eski build ciktilari + Python cache temizleniyor...
if exist "build"             rmdir /S /Q "build"
if exist "dist"              rmdir /S /Q "dist"
if exist "installer_output"  rmdir /S /Q "installer_output"
REM Python .pyc cache — PyInstaller bazen bayat .pyc dosyalari toplayabilir.
REM Bunlari da temizleyip src/ altindaki en guncel .py dosyalarinin
REM derlenmesini garanti altina aliyoruz.
for /d /r "src" %%D in (__pycache__) do if exist "%%D" rmdir /S /Q "%%D"
REM PyInstaller kendi cache dizini (%LocalAppData%\pyinstaller) — --clean
REM bayragi zaten temizler ama emin olmak icin manuel de sileriz.
if exist "%LocalAppData%\pyinstaller" rmdir /S /Q "%LocalAppData%\pyinstaller"
echo       OK
echo.

REM ── 2) PyInstaller ─────────────────────────────────────────────
echo [2/3] PyInstaller derleniyor... (birkac dakika surebilir)
python -m PyInstaller --clean --noconfirm GloveTestSystem.spec
if errorlevel 1 (
    echo       HATA: PyInstaller derleme basarisiz.
    goto :error
)
if not exist "dist\%APP_NAME%\%APP_NAME%.exe" (
    echo       HATA: Beklenen EXE bulunamadi:
    echo              dist\%APP_NAME%\%APP_NAME%.exe
    goto :error
)
echo       OK - dist\%APP_NAME%\%APP_NAME%.exe olusturuldu
echo.

REM ── 3) Inno Setup ──────────────────────────────────────────────
echo [3/3] Inno Setup ile installer derleniyor...
if not defined ISCC (
    echo       HATA: Inno Setup ISCC.exe bulunamadi.
    echo.
    echo       Kurmak icin PowerShell'de:
    echo           winget install JRSoftware.InnoSetup
    echo       veya manuel indir: https://jrsoftware.org/isdl.php
    echo.
    echo       Alternatif ^(Inno Setup gerekmez^):
    echo           python build_installer.py
    goto :error
)
echo       ISCC: %ISCC%
"%ISCC%" "installer.iss"
if errorlevel 1 (
    echo       HATA: Inno Setup derleme basarisiz.
    goto :error
)
echo       OK
echo.

REM ── Basari ozeti ───────────────────────────────────────────────
echo ================================================================
echo   BUILD TAMAMLANDI
echo ================================================================
for %%F in ("installer_output\*.exe") do (
    echo   Dosya: %%~fF
    for /f %%S in ('powershell -NoProfile -Command "[math]::Round((Get-Item '%%~fF').Length/1MB,1)"') do (
        echo   Boyut: %%S MB
    )
)
echo ================================================================
echo.

start "" explorer.exe "installer_output"
goto :end

:error
echo.
echo ================================================================
echo   BUILD BASARISIZ
echo ================================================================
pause
exit /b 1

:end
pause
exit /b 0
