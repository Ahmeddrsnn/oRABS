@echo off
cd /D "%~dp0"
echo BASLIYOR %DATE% %TIME% > build_log.txt
python -m PyInstaller --clean --noconfirm GloveTestSystem.spec >> build_log.txt 2>&1
set RC=%ERRORLEVEL%
echo BITTI %DATE% %TIME% EXIT=%RC% >> build_log.txt
if exist dist\GloveTestSystem\GloveTestSystem.exe (
    echo EXE_VAR >> build_log.txt
) else (
    echo EXE_YOK >> build_log.txt
)
exit /B %RC%
