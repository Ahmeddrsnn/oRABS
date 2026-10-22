@echo off
echo =====================================
echo Glove Test Control System
echo 21 CFR Part 11 Compliant
echo =====================================
echo.

echo Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo X Python not found! Please install Python 3.8 or higher.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b
)

echo Starting application...
echo.
echo Default Login Credentials:
echo   Username: admin
echo   Password: Admin123!
echo.

cd src
python main.py

echo.
echo Application closed.
pause
