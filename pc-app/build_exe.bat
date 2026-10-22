@echo off
echo ========================================
echo  Ultra GITS v1.0.0 - EXE Builder
echo ========================================
echo.

echo [1/3] PyInstaller kontrol ediliyor...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo   PyInstaller bulunamadi. Yukleniyor...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo HATA: PyInstaller yuklenemedi!
        pause
        exit /b
    )
    echo   PyInstaller basariyla yuklendi!
) else (
    echo   PyInstaller zaten yuklu.
)

echo.
echo [2/3] EXE dosyasi olusturuluyor...
echo.

REM Onceki build temizle
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Build EXE
python -m PyInstaller --clean --noconfirm GloveTestSystem.spec

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo  EXE BASARIYLA OLUSTURULDU!
    echo ========================================
    echo.
    
    echo [3/3] Dagitim klasoru hazirlaniyor...
    
    REM Dagitim klasoru olustur
    if exist GloveTestSystem_Distribution rmdir /s /q GloveTestSystem_Distribution
    mkdir GloveTestSystem_Distribution
    
    REM EXE + runtime kopyala
    xcopy dist\GloveTestSystem\* GloveTestSystem_Distribution\ /E /I /Q
    
    REM Veri klasorleri
    mkdir GloveTestSystem_Distribution\database
    mkdir GloveTestSystem_Distribution\reports
    mkdir GloveTestSystem_Distribution\batches
    mkdir GloveTestSystem_Distribution\logs
    mkdir GloveTestSystem_Distribution\config
    
    REM Config
    if exist config\settings.json copy config\settings.json GloveTestSystem_Distribution\config\
    
    REM Dokumanlar
    if exist README.md copy README.md GloveTestSystem_Distribution\
    if exist ESP32_BAGLANTI_KLAVUZU.md copy ESP32_BAGLANTI_KLAVUZU.md GloveTestSystem_Distribution\
    
    echo.
    echo  Dagitim klasoru hazir:
    echo    %CD%\GloveTestSystem_Distribution
    echo.
    echo  NOT: Installer ^(Setup.exe^) olusturmak icin
    echo    powershell -ExecutionPolicy Bypass -File build_exe.ps1
    echo  komutunu calistirin.
) else (
    echo.
    echo HATA: EXE olusturulamadi!
    echo Lutfen hata mesajlarini kontrol edin.
)

echo.
pause
