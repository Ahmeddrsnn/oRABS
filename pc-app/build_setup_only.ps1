# Ultra GITS - Sadece Setup EXE Builder (ZIP atlanır)
# Faz-9: kullanıcı ZIP istemediği için build_exe.ps1'in kısaltılmış varyantı.
# Kullanim: powershell -ExecutionPolicy Bypass -File build_setup_only.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$AppName   = "GloveTestSystem"
$DistDir   = "dist\$AppName"
$OutputDir = "${AppName}_Setup"
$Version   = "1.0.0"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Ultra GITS v$Version - Setup Builder" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. PyInstaller kontrolü
Write-Host "`n[1/5] PyInstaller kontrol ediliyor..." -ForegroundColor Yellow
$null = python -m pip show pyinstaller 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  PyInstaller yukleniyor..." -ForegroundColor Gray
    python -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "HATA: PyInstaller yuklenemedi!" -ForegroundColor Red
        exit 1
    }
}
Write-Host "  OK - PyInstaller hazir" -ForegroundColor Green

# 2. Eski build çıktılarını temizle
Write-Host "`n[2/5] Onceki build temizleniyor..." -ForegroundColor Yellow
if (Test-Path "build")    { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist")     { Remove-Item -Recurse -Force "dist"  }
if (Test-Path $OutputDir) { Remove-Item -Recurse -Force $OutputDir }
Write-Host "  OK - Temiz" -ForegroundColor Green

# 3. PyInstaller ile derle
Write-Host "`n[3/5] EXE derleniyor... (birkac dakika surebilir)" -ForegroundColor Yellow
python -m PyInstaller --clean --noconfirm GloveTestSystem.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nHATA: PyInstaller basarisiz oldu!" -ForegroundColor Red
    exit 1
}
Write-Host "  OK - EXE derlendi" -ForegroundColor Green

# 4. Dağıtım klasörü hazırlığı (Inno Setup buradan okur)
Write-Host "`n[4/5] Dagitim klasoru hazirlaniyor..." -ForegroundColor Yellow
Copy-Item $DistDir -Destination $OutputDir -Recurse
foreach ($dir in @("database", "reports", "batches", "logs", "config")) {
    New-Item -ItemType Directory -Path "$OutputDir\$dir" -Force | Out-Null
}
if (Test-Path "config\settings.json") {
    Copy-Item "config\settings.json" -Destination "$OutputDir\config\"
}
$readme = @"
ULTRA GITS v$Version - 21 CFR Part 11 Uyumlu Eldiven Test Sistemi

KURULUM
  1. Bu klasoru istediginiz konuma kopyalayin
  2. GloveTestSystem.exe dosyasini calistirin
  3. Ilk acilista: admin / Admin123!
"@
$readme | Out-File -FilePath "$OutputDir\OKUBENI.txt" -Encoding UTF8
foreach ($doc in @("README.md", "ESP32_BAGLANTI_KLAVUZU.md")) {
    if (Test-Path $doc) { Copy-Item $doc -Destination $OutputDir }
}
Write-Host "  OK - Dagitim klasoru hazir" -ForegroundColor Green

# 5. Inno Setup ile installer EXE üret (ZIP YOK)
Write-Host "`n[5/5] Inno Setup ile Setup EXE derleniyor..." -ForegroundColor Yellow
$isccPaths = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 5\ISCC.exe"
)
$isccExe = $null
foreach ($p in $isccPaths) { if (Test-Path $p) { $isccExe = $p; break } }

if (-not $isccExe) {
    Write-Host "HATA: Inno Setup kurulu degil. https://jrsoftware.org/isdl.php" -ForegroundColor Red
    exit 1
}
Write-Host "  Inno Setup: $isccExe" -ForegroundColor Gray
& $isccExe "installer.iss"
if ($LASTEXITCODE -ne 0) {
    Write-Host "HATA: Inno Setup derlemesi basarisiz!" -ForegroundColor Red
    exit 1
}

# Setup EXE bul
$setupExe = Get-ChildItem "installer_output" -Filter "*.exe" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  SETUP EXE HAZIR!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
if ($setupExe) {
    $sizeMB = [math]::Round($setupExe.Length / 1MB, 1)
    Write-Host "  Dosya: $($setupExe.FullName)" -ForegroundColor White
    Write-Host "  Boyut: $sizeMB MB" -ForegroundColor White
}
Write-Host ""
