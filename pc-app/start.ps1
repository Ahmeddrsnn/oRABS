# Glove Test System - Startup Script
# Quick start script for the application

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Glove Test Control System" -ForegroundColor Cyan
Write-Host "21 CFR Part 11 Compliant" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Check Python installation
Write-Host "Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Python found: $pythonVersion" -ForegroundColor Green
}
catch {
    Write-Host "✗ Python not found! Please install Python 3.8 or higher." -ForegroundColor Red
    Write-Host "Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    pause
    exit
}

Write-Host ""
Write-Host "Checking dependencies..." -ForegroundColor Yellow

# Check if dependencies are installed
$pipList = pip list 2>&1
if ($pipList -match "PyQt5") {
    Write-Host "✓ Dependencies appear to be installed" -ForegroundColor Green
}
else {
    Write-Host "! Dependencies not found. Installing..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

Write-Host ""
Write-Host "Starting application..." -ForegroundColor Green
Write-Host ""
Write-Host "Default Login Credentials:" -ForegroundColor Yellow
Write-Host "  Username: admin" -ForegroundColor White
Write-Host "  Password: Admin123!" -ForegroundColor White
Write-Host ""

# Run the application
cd src
python main.py

Write-Host ""
Write-Host "Application closed." -ForegroundColor Cyan
pause
