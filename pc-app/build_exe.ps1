# Ultra GITS - EXE & Installer Builder v1.0.0
# Kullanim: powershell -ExecutionPolicy Bypass -File build_exe.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$AppName     = "GloveTestSystem"
$DistDir     = "dist\$AppName"
$OutputDir   = "${AppName}_Setup"
$Version     = "1.0.0"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Ultra GITS v$Version - Builder" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. PyInstaller kontrolu
Write-Host "`n[1/6] PyInstaller kontrol ediliyor..." -ForegroundColor Yellow
$null = python -m pip show pyinstaller 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  PyInstaller yukleniyor..." -ForegroundColor Gray
    python -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { Write-Host "HATA: PyInstaller yuklenemedi!" -ForegroundColor Red; pause; exit 1 }
}
Write-Host "  OK - PyInstaller hazir" -ForegroundColor Green

# 2. Onceki derleme ciktilarini temizle
Write-Host "`n[2/6] Onceki build temizleniyor..." -ForegroundColor Yellow
if (Test-Path "build")    { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist")     { Remove-Item -Recurse -Force "dist"  }
if (Test-Path $OutputDir) { Remove-Item -Recurse -Force $OutputDir }
Write-Host "  OK - Temiz" -ForegroundColor Green

# 3. PyInstaller ile derle (onedir)
Write-Host "`n[3/6] EXE derleniyor..." -ForegroundColor Yellow
python -m PyInstaller --clean --noconfirm GloveTestSystem.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nHATA: PyInstaller basarisiz oldu!" -ForegroundColor Red
    Write-Host "Yukaridaki hata mesajlarini kontrol edin." -ForegroundColor Yellow
    pause; exit 1
}
Write-Host "  OK - EXE derlendi" -ForegroundColor Green

# 4. Dagitim klasoru olustur
Write-Host "`n[4/6] Dagitim klasoru hazirlaniyor..." -ForegroundColor Yellow

Copy-Item $DistDir -Destination $OutputDir -Recurse

# Veri klasorleri (bos - uygulama ilk acilista iclerini doldurur)
foreach ($dir in @("database", "reports", "batches", "logs", "config")) {
    New-Item -ItemType Directory -Path "$OutputDir\$dir" -Force | Out-Null
}

# Config dosyasini ekle (varsa)
if (Test-Path "config\settings.json") {
    Copy-Item "config\settings.json" -Destination "$OutputDir\config\"
}

# OKUBENI dosyasi
$readmeContent = @"
ULTRA GITS v$Version
21 CFR Part 11 Uyumlu Eldiven Test Sistemi

KURULUM
  1. Bu klasoru istediginiz konuma kopyalayin (orn: C:\Ultra GITS)
  2. GloveTestSystem.exe dosyasini calistirin
  3. Ilk acilista admin hesabi otomatik olusturulur
     Varsayilan giris: admin / Admin123!

KLASOR YAPISI
  GloveTestSystem.exe   Ana uygulama
  _internal\            Python kutuphaneleri (SILMEYIN)
  config\               Ayar dosyalari
  database\             SQLite veritabani (otomatik olusur)
  reports\              PDF raporlar
  batches\              Batch arsivleri
  logs\                 Gunluk dosyalari

SORUN GIDERME
  - Program acilmiyorsa: _internal klasorunun saglam oldugundan emin olun
  - Veritabani bozulduysa: database\glove_test.db dosyasini silin
  - Hata detayi: crash_log.txt dosyasina bakin
"@
$readmeContent | Out-File -FilePath "$OutputDir\OKUBENI.txt" -Encoding UTF8

# Kilavuzlari kopyala (varsa)
foreach ($doc in @("README.md", "ESP32_BAGLANTI_KLAVUZU.md")) {
    if (Test-Path $doc) { Copy-Item $doc -Destination $OutputDir }
}

Write-Host "  OK - Dagitim klasoru hazir" -ForegroundColor Green

# 5. ZIP olustur
Write-Host "`n[5/6] ZIP arsivi olusturuluyor..." -ForegroundColor Yellow
$zipPath = "${AppName}_v${Version}_Setup.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath }
Compress-Archive -Path $OutputDir -DestinationPath $zipPath -CompressionLevel Optimal
$zipSize = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "  OK - $zipPath ($zipSize MB)" -ForegroundColor Green

# 6. Inno Setup ile installer olustur (opsiyonel)
Write-Host "`n[6/6] Inno Setup installer kontrol ediliyor..." -ForegroundColor Yellow

$isccPaths = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 5\ISCC.exe"
)

$isccExe = $null
foreach ($p in $isccPaths) {
    if (Test-Path $p) { $isccExe = $p; break }
}

if ($isccExe) {
    Write-Host "  Inno Setup bulundu: $isccExe" -ForegroundColor Gray
    Write-Host "  Installer derleniyor..." -ForegroundColor Gray
    & $isccExe "installer.iss"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK - Setup EXE olusturuldu: installer_output\GloveTestSystem_v${Version}_Setup.exe" -ForegroundColor Green
    } else {
        Write-Host "  UYARI: Inno Setup derlemesi basarisiz oldu. ZIP dosyasini kullanabilirsiniz." -ForegroundColor Yellow
    }
} else {
    Write-Host "  UYARI: Inno Setup bulunamadi (kurulu degil)." -ForegroundColor Yellow
    Write-Host "    ZIP dosyasi zaten hazir: $zipPath" -ForegroundColor Gray
}

# Ozet
$exeSize = [math]::Round((Get-Item "$OutputDir\$AppName.exe").Length / 1MB, 1)
$totalSize = [math]::Round((Get-ChildItem $OutputDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB, 0)

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  DERLEME TAMAMLANDI!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  EXE boyutu    : $exeSize MB" -ForegroundColor White
Write-Host "  Toplam boyut  : $totalSize MB" -ForegroundColor White
Write-Host "  ZIP dosyasi   : $zipPath ($zipSize MB)" -ForegroundColor White
Write-Host ""
Write-Host "  Klasor : $ProjectRoot\$OutputDir"  -ForegroundColor Cyan
Write-Host "  ZIP    : $ProjectRoot\$zipPath"     -ForegroundColor Cyan

if ($isccExe -and (Test-Path "installer_output\GloveTestSystem_v${Version}_Setup.exe")) {
    $setupSize = [math]::Round((Get-Item "installer_output\GloveTestSystem_v${Version}_Setup.exe").Length / 1MB, 1)
    Write-Host "  Setup  : $ProjectRoot\installer_output\GloveTestSystem_v${Version}_Setup.exe ($setupSize MB)" -ForegroundColor Cyan
}

Write-Host ""
pause
