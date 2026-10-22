; ╔══════════════════════════════════════════════════════════════════════╗
; ║  Ultra GITS — Inno Setup Installer Script                          ║
; ║  Glove Test Control System (21 CFR Part 11 Uyumlu)                 ║
; ║                                                                    ║
; ║  Sifir kurulum prensibi: Veritabani, raporlar, batch arsivleri     ║
; ║  dahil edilmez. Uygulama ilk acilista bunlari kendisi olusturur.   ║
; ║                                                                    ║
; ║  Derleme:  iscc.exe installer.iss                                  ║
; ╚══════════════════════════════════════════════════════════════════════╝

; ── Sabitler ─────────────────────────────────────────────────────────────
#define MyAppName      "Ultra GITS"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "LCC"
#define MyAppURL       ""
#define MyAppExeName   "GloveTestSystem.exe"
#define BuildOutput    "dist\GloveTestSystem"

; ── Genel Ayarlar ────────────────────────────────────────────────────────
[Setup]
AppId={{A7C3E8F2-5B4D-4E6A-9F1C-2D8B7A3E5F9D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
; ── Varsayılan kurulum yolu: C:\Ultra GITS ──
DefaultDirName=C:\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes
; ── Çıktı ──
OutputDir=installer_output
OutputBaseFilename=GloveTestSystem_v{#MyAppVersion}_Setup
; ── Sıkıştırma ──
Compression=lzma2/ultra64
SolidCompression=yes
; ── Görünüm ──
WizardStyle=modern
WizardSizePercent=110
SetupIconFile=src\assets\app_icon.ico
; ── Yetki ──
; "dialog" → başlangıçta "Tüm kullanıcılar / Sadece ben" sorusu çıkar
; "commandline" → /ALLUSERS veya /CURRENTUSER parametreleriyle sessiz kurulum destekler
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
; ── 64-bit ──
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; ── Loglama ──
SetupLogging=yes
; ── Upgrade desteği ──
UsePreviousAppDir=yes
; ── Uninstall bilgisi ──
UninstallDisplayName={#MyAppName} v{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}

; ── Diller ───────────────────────────────────────────────────────────────
[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

; ── Kurulum Görevleri ────────────────────────────────────────────────────
[Tasks]
Name: "desktopicon"; Description: "Masaüstü kısayolu oluştur"; GroupDescription: "Ek görevler:"

; ── Dosyalar ─────────────────────────────────────────────────────────────
[Files]
; Ana uygulama EXE
Source: "{#BuildOutput}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Python runtime + kütüphaneler (_internal klasörü)
Source: "{#BuildOutput}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; Visual C++ 2015-2022 Redistributable (x64) — Python 3.14 baglayacigi
; VCRUNTIME/UCRT DLL'leri için gerekli. Yalnızca eksikse kurulur
; (bkz. [Run] + VCRedistNeedsInstall). Kurulum sonrası {tmp}'den silinir.
Source: "redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
; ── NOT: config/settings.json, veritabanı, raporlar, batch arşivleri DAHİL EDİLMEZ ──
; Uygulama ilk açılışta boş veritabanı + varsayılan admin hesabını otomatik oluşturur.
; config/settings.json da uygulama tarafından gerektiğinde üretilir.

; ── Klasörler (yoksa oluştur, varsa dokunma) ─────────────────────────────
[Dirs]
Name: "{app}\database"; Flags: uninsneveruninstall
Name: "{app}\reports";  Flags: uninsneveruninstall
Name: "{app}\batches";  Flags: uninsneveruninstall
Name: "{app}\logs"
Name: "{app}\config";   Flags: uninsneveruninstall

; ── Kısayollar ───────────────────────────────────────────────────────────
[Icons]
; Start menü
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\app_icon.ico"
Name: "{group}\{#MyAppName} Kaldır"; Filename: "{uninstallexe}"
; Masaüstü (kullanıcı seçerse)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\app_icon.ico"; Tasks: desktopicon

; ── Kurulum sonrası ──────────────────────────────────────────────────────
[Run]
; VC++ 2015-2022 Redistributable (x64) — yalnızca hedef PC'de eksikse çalıştır.
; Sessiz kurulum, restart gerektirmez.
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; \
    StatusMsg: "Visual C++ 2015-2022 Runtime yükleniyor..."; \
    Check: VCRedistNeedsInstall; \
    Flags: waituntilterminated

Filename: "{app}\{#MyAppExeName}"; Description: "Uygulamayı şimdi başlat"; Flags: nowait postinstall skipifsilent unchecked

; ── Kaldırma kuralları ───────────────────────────────────────────────────
; Kullanıcı verileri (database, reports, batches, config) KESİNLİKLE SİLİNMEZ.
; Sadece log ve geçici dosyalar temizlenir.
[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\crash_log.txt"
Type: files; Name: "{app}\storage_config.json"
Type: files; Name: "{app}\app.log"
Type: files; Name: "{app}\output.log"

; ── Pascal Script ────────────────────────────────────────────────────────
[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
{ VC++ 2015-2022 Redistributable x64 kurulu mu? Registry'den kontrol.
  Anahtar: HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64
  "Installed" DWORD = 1 ise kurulu. True dönerse [Run] runtime'ı çağırır. }
function VCRedistNeedsInstall(): Boolean;
var
  Installed: Cardinal;
begin
  if RegQueryDWordValue(HKLM,
       'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
       'Installed', Installed) then
    Result := (Installed <> 1)
  else
    Result := True;  { Anahtar yok → kurulu değil }
end;
{ Kurulum yolu her zaman C:\Ultra GITS olsun — kullanıcı/admin fark etmez }
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    WizardForm.DirEdit.Text := ExpandConstant('C:\{#MyAppName}');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { Veri klasörlerini garanti altına al }
    if not DirExists(ExpandConstant('{app}\database')) then
      ForceDirectories(ExpandConstant('{app}\database'));
    if not DirExists(ExpandConstant('{app}\reports')) then
      ForceDirectories(ExpandConstant('{app}\reports'));
    if not DirExists(ExpandConstant('{app}\batches')) then
      ForceDirectories(ExpandConstant('{app}\batches'));
    if not DirExists(ExpandConstant('{app}\logs')) then
      ForceDirectories(ExpandConstant('{app}\logs'));
    if not DirExists(ExpandConstant('{app}\config')) then
      ForceDirectories(ExpandConstant('{app}\config'));
  end;
end;

{ Kaldırma sırasında kullanıcıyı uyar }
function InitializeUninstall(): Boolean;
begin
  Result := MsgBox(
    'Ultra GITS kaldırılacak.' + #13#10 + #13#10 +
    'Veritabanı, raporlar ve batch arşivleriniz SİLİNMEYECEK.' + #13#10 +
    'Bu dosyalar kurulum klasöründe kalacaktır.' + #13#10 + #13#10 +
    'Devam etmek istiyor musunuz?',
    mbConfirmation, MB_YESNO) = IDYES;
end;
