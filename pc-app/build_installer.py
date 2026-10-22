"""Tek dosya UltraGITS_Setup.exe üretir.

Akış:
    1) Tkinter GUI installer stub'ı yazılır.
    2) PyInstaller --onefile ile stub + `dist/GloveTestSystem/` klasörü
       (--add-data ile gömülr) tek exe haline getirilir.
    3) Sonuç `installer_output/UltraGITS_Setup.exe` olarak çıkar.

    ZIP ara dosyası kullanılmaz — PyInstaller'ın kendi sıkıştırması yeterli.

Önkoşul:
    cd pc-app
    python -m PyInstaller --clean --noconfirm GloveTestSystem.spec
    python build_installer.py
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
DIST_APP_DIR = HERE / "dist" / "GloveTestSystem"
WORK_DIR = Path(r"C:\Temp\oraps_installer_build")
INSTALLER_OUTPUT_DIR = HERE / "installer_output"
OUT_EXE = INSTALLER_OUTPUT_DIR / "UltraGITS_Setup.exe"

APP_NAME = "Ultra GITS"
APP_VERSION = "1.0.0"
APP_PUBLISHER = "LCC"
APP_EXE_NAME = "GloveTestSystem.exe"
DEFAULT_INSTALL_DIR = r"C:\Ultra GITS"
ICON_FILE = HERE / "src" / "assets" / "app_icon.ico"


# ─────────────────────────────────────────────────────────────────────────────
# Stub installer kaynak kodu — UltraGITS_Setup.exe içine paketlenir
# ─────────────────────────────────────────────────────────────────────────────
STUB_BODY = r'''
"""Ultra GITS installer stub (gömülü program dosyalarını hedef klasöre kopyalar).

Argümanlar:
    (yok)            → GUI installer
    --uninstall PATH → Sessiz kaldırma (Uninstall.bat tarafından çağrılır)
"""
import os
import sys
import shutil
import subprocess
import threading
import tempfile
import winreg
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Build tarafından enjekte edilen sabitler (en üste)
# APP_NAME, APP_VERSION, APP_PUBLISHER, APP_EXE_NAME,
# DEFAULT_INSTALL_DIR yukarıda tanımlıdır.

REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\\" + APP_NAME.replace(" ", "")
DATA_DIRS = ("database", "reports", "batches", "logs", "config")
PAYLOAD_SUBDIR = "app"  # PyInstaller --add-data hedef dizini


def _bundle_dir() -> Path:
    """PyInstaller --onefile içindeki gömülü dosyaların yolu."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent


def _payload_root() -> Path:
    return _bundle_dir() / PAYLOAD_SUBDIR


# ── Uninstall mode ──────────────────────────────────────────────────────────
def run_uninstall(install_dir: str) -> int:
    install_dir = os.path.abspath(install_dir)
    try:
        # Çalışan kopyayı kapat
        subprocess.run(
            ["taskkill", "/F", "/IM", APP_EXE_NAME],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass

    # Kısayolları sil
    user = os.environ.get("USERPROFILE", "")
    appdata = os.environ.get("APPDATA", "")
    candidates = [
        os.path.join(user, "Desktop", f"{APP_NAME}.lnk"),
        os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", f"{APP_NAME}.lnk"),
        os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME, f"{APP_NAME}.lnk"),
        os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME, "Uninstall.lnk"),
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    # Başlat menüsü klasörü
    sm_folder = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME)
    if os.path.isdir(sm_folder):
        try:
            shutil.rmtree(sm_folder, ignore_errors=True)
        except Exception:
            pass

    # Registry kaydı
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
    except FileNotFoundError:
        pass
    except OSError:
        pass

    # Program dosyalarını sil (data klasörleri korunur)
    try:
        if os.path.isdir(install_dir):
            for entry in os.listdir(install_dir):
                full = os.path.join(install_dir, entry)
                if entry.lower() in DATA_DIRS:
                    continue
                try:
                    if os.path.isdir(full):
                        shutil.rmtree(full, ignore_errors=True)
                    else:
                        os.remove(full)
                except Exception:
                    pass
    except Exception:
        pass

    # Self-delete: Uninstall.bat'ı +program klasörünü sil → ayrı bir bat ile
    try:
        cleanup = tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="cp1254"
        )
        cleanup.write(
            f'@echo off\r\n'
            f'timeout /t 2 /nobreak >nul\r\n'
            f'rmdir /S /Q "{install_dir}" 2>nul\r\n'
            f'del "%~f0"\r\n'
        )
        cleanup.close()
        subprocess.Popen(
            ["cmd", "/c", cleanup.name],
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
    except Exception:
        pass
    return 0


# ── GUI installer ───────────────────────────────────────────────────────────
class InstallerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} Kurulum")
        self.root.geometry("560x470")
        self.root.resizable(False, False)
        try:
            self.root.iconbitmap(default="")  # exe ikonu kullanılır
        except Exception:
            pass

        self.install_dir = tk.StringVar(value=DEFAULT_INSTALL_DIR)
        self.shortcut_desktop = tk.BooleanVar(value=True)
        self.shortcut_startmenu = tk.BooleanVar(value=True)
        # Sıfırdan (fabrika) kurulum: veritabanı, ayarlar, batch'ler, raporlar,
        # loglar ve config dosyaları silinir. Yalnızca `admin/Admin123!`
        # kullanıcısı olan boş bir DB ilk açılışta yeniden üretilir.
        self.clean_install = tk.BooleanVar(value=True)
        self.launch_after = tk.BooleanVar(value=True)
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 14, "pady": 6}
        header = tk.Label(
            self.root,
            text=f"{APP_NAME}  v{APP_VERSION}",
            font=("Segoe UI", 16, "bold"),
            fg="#1f2937",
        )
        header.pack(anchor="w", padx=14, pady=(14, 0))
        sub = tk.Label(
            self.root,
            text="21 CFR Part 11 uyumlu eldiven test sistemi — kurulum sihirbazı",
            font=("Segoe UI", 9), fg="#6b7280",
        )
        sub.pack(anchor="w", padx=14, pady=(0, 12))

        # Kurulum klasörü
        frm = tk.LabelFrame(self.root, text="Kurulum klasörü", font=("Segoe UI", 9))
        frm.pack(fill="x", **pad)
        path_row = tk.Frame(frm)
        path_row.pack(fill="x", padx=8, pady=8)
        self.path_entry = tk.Entry(path_row, textvariable=self.install_dir, font=("Segoe UI", 10))
        self.path_entry.pack(side="left", fill="x", expand=True)
        tk.Button(path_row, text="Gözat…", width=10, command=self._on_browse).pack(side="left", padx=(6, 0))

        # Seçenekler
        opt = tk.LabelFrame(self.root, text="Kısayollar", font=("Segoe UI", 9))
        opt.pack(fill="x", **pad)
        tk.Checkbutton(opt, text="Masaüstüne kısayol ekle", variable=self.shortcut_desktop,
                       font=("Segoe UI", 10)).pack(anchor="w", padx=8, pady=(6, 0))
        tk.Checkbutton(opt, text="Başlat menüsüne kısayol ekle", variable=self.shortcut_startmenu,
                       font=("Segoe UI", 10)).pack(anchor="w", padx=8, pady=(0, 6))

        # Sıfırdan / fabrika kurulumu — DB + ayarlar + raporlar silinir
        clean = tk.LabelFrame(self.root, text="Kurulum tipi", font=("Segoe UI", 9))
        clean.pack(fill="x", **pad)
        tk.Checkbutton(
            clean,
            text="Sıfırdan (fabrika) kurulum — mevcut veritabanı, ayarlar ve raporlar silinir",
            variable=self.clean_install,
            font=("Segoe UI", 10), fg="#b91c1c",
            wraplength=520, justify="left",
        ).pack(anchor="w", padx=8, pady=(6, 0))
        tk.Label(
            clean,
            text=(
                "İlk açılışta yalnızca 'admin / Admin123!' kullanıcısı ve boş bir DB oluşur. "
                "3D GLB modeli tanımlı değildir — Ayarlar → ORAPS ekranından yüklenir."
            ),
            font=("Segoe UI", 8), fg="#6b7280",
            wraplength=520, justify="left",
        ).pack(anchor="w", padx=28, pady=(0, 6))

        # Progress
        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=14, pady=(14, 4))
        self.status = tk.Label(self.root, text="Kurmaya hazır.", font=("Segoe UI", 9), fg="#374151")
        self.status.pack(anchor="w", padx=14)

        # Butonlar
        btns = tk.Frame(self.root)
        btns.pack(fill="x", side="bottom", padx=14, pady=12)
        self.btn_install = tk.Button(
            btns, text="Kur", width=14, height=1,
            font=("Segoe UI", 10, "bold"),
            bg="#2563eb", fg="white", activebackground="#1d4ed8",
            relief="flat", command=self._on_install,
        )
        self.btn_install.pack(side="right")
        self.btn_cancel = tk.Button(
            btns, text="Vazgeç", width=10, command=self.root.destroy
        )
        self.btn_cancel.pack(side="right", padx=(0, 8))

    def _on_browse(self):
        d = filedialog.askdirectory(initialdir=self.install_dir.get() or "C:/")
        if d:
            self.install_dir.set(os.path.normpath(d))

    def _set_status(self, text: str, pct: float | None = None):
        self.status.config(text=text)
        if pct is not None:
            self.progress["value"] = pct
        self.root.update_idletasks()

    def _on_install(self):
        target = os.path.normpath(self.install_dir.get().strip())
        if not target:
            messagebox.showerror(APP_NAME, "Lütfen bir kurulum klasörü seçin.")
            return
        clean = bool(self.clean_install.get())
        if os.path.isdir(target) and os.listdir(target):
            if clean:
                if not messagebox.askyesno(
                    APP_NAME,
                    f"'{target}' boş değil ve SIFIRDAN KURULUM seçildi.\n\n"
                    "Mevcut program dosyalarının YANI SIRA veritabanı, ayarlar, "
                    "raporlar, batch'ler ve loglar da SİLİNECEK.\n\n"
                    "Bu işlem geri alınamaz. Devam edilsin mi?",
                    icon="warning",
                ):
                    return
            else:
                if not messagebox.askyesno(
                    APP_NAME,
                    f"'{target}' boş değil. Mevcut program dosyaları üzerine yazılacak.\n"
                    "(database / reports / batches / logs / config klasörleri korunur.)\n\n"
                    "Devam edilsin mi?",
                ):
                    return

        self.btn_install.config(state="disabled")
        self.btn_cancel.config(state="disabled")
        self.path_entry.config(state="disabled")

        threading.Thread(target=self._run_install, args=(target, clean), daemon=True).start()

    def _run_install(self, target: str, clean: bool = False):
        try:
            self._set_status("Klasör hazırlanıyor…", 2)
            os.makedirs(target, exist_ok=True)

            # Eski program dosyalarını temizle.
            # clean=True ise data klasörleri de dahil TÜM içerik silinir
            # (sıfırdan kurulum). clean=False ise DATA_DIRS korunur (upgrade).
            for entry in os.listdir(target):
                if not clean and entry.lower() in DATA_DIRS:
                    continue
                full = os.path.join(target, entry)
                try:
                    if os.path.isdir(full):
                        shutil.rmtree(full, ignore_errors=True)
                    else:
                        os.remove(full)
                except Exception:
                    pass

            self._set_status("Dosyalar açılıyor…", 8)
            src_root = _payload_root()
            if not src_root.exists():
                raise FileNotFoundError(f"Gömülü payload bulunamadı: {src_root}")

            # Tüm dosyaları listele (ilerleme için)
            all_files: list[Path] = []
            for r, _, files in os.walk(src_root):
                for fn in files:
                    all_files.append(Path(r) / fn)
            total = max(1, len(all_files))

            for i, full in enumerate(all_files, 1):
                rel = full.relative_to(src_root)
                out = Path(target) / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(full, out)
                except PermissionError:
                    # Hedef dosya kilitliyse geç
                    pass
                if i % 25 == 0 or i == total:
                    pct = 8 + (i / total) * 78  # 8 → 86
                    self._set_status(f"Kopyalanıyor… ({i}/{total})", pct)

            self._set_status("Veri klasörleri oluşturuluyor…", 88)
            for d in DATA_DIRS:
                os.makedirs(os.path.join(target, d), exist_ok=True)

            self._set_status("Kısayollar oluşturuluyor…", 92)
            target_exe = os.path.join(target, APP_EXE_NAME)
            self._make_uninstaller(target)
            if self.shortcut_desktop.get():
                self._make_shortcut(
                    os.path.join(os.environ["USERPROFILE"], "Desktop", f"{APP_NAME}.lnk"),
                    target_exe, target,
                )
            if self.shortcut_startmenu.get():
                sm_folder = os.path.join(
                    os.environ["APPDATA"], "Microsoft", "Windows",
                    "Start Menu", "Programs", APP_NAME,
                )
                os.makedirs(sm_folder, exist_ok=True)
                self._make_shortcut(
                    os.path.join(sm_folder, f"{APP_NAME}.lnk"),
                    target_exe, target,
                )
                self._make_shortcut(
                    os.path.join(sm_folder, "Uninstall.lnk"),
                    os.path.join(target, "Uninstall.bat"), target,
                )

            self._set_status("Sistem kaydı yapılıyor…", 96)
            self._write_registry(target)

            self._set_status("Kurulum tamamlandı.", 100)
            self.root.after(0, lambda: self._finish_dialog(target))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror(
                APP_NAME, f"Kurulum sırasında hata oluştu:\n\n{e}"
            ))
            self.root.after(0, lambda: self.btn_cancel.config(state="normal"))
            self.root.after(0, lambda: self.btn_install.config(state="normal"))
            self.root.after(0, lambda: self.path_entry.config(state="normal"))

    def _make_shortcut(self, link_path: str, target: str, workdir: str):
        ps = (
            "$ws = New-Object -ComObject WScript.Shell;"
            f"$s = $ws.CreateShortcut('{link_path}');"
            f"$s.TargetPath = '{target}';"
            f"$s.WorkingDirectory = '{workdir}';"
            f"$s.IconLocation = '{target},0';"
            "$s.Save()"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        except Exception:
            pass

    def _make_uninstaller(self, install_dir: str):
        bat = os.path.join(install_dir, "Uninstall.bat")
        # Stub kendi içinden uninstall yapar; UltraGITS_Setup.exe install_dir'a kopyalanır.
        self_exe = sys.executable if getattr(sys, "frozen", False) else None
        if self_exe:
            shutil.copy2(self_exe, os.path.join(install_dir, "UltraGITS_Uninstaller.exe"))
            with open(bat, "w", encoding="cp1254") as f:
                f.write(
                    "@echo off\r\n"
                    f'start "" "{os.path.join(install_dir, "UltraGITS_Uninstaller.exe")}" '
                    f'--uninstall "{install_dir}"\r\n'
                )
        else:
            # development run — basit klasör temizleme
            with open(bat, "w", encoding="cp1254") as f:
                f.write(
                    "@echo off\r\n"
                    f'rmdir /S /Q "{install_dir}"\r\n'
                )

    def _write_registry(self, install_dir: str):
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
                winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
                winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, APP_PUBLISHER)
                winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, install_dir)
                winreg.SetValueEx(
                    k, "UninstallString", 0, winreg.REG_SZ,
                    f'"{os.path.join(install_dir, "Uninstall.bat")}"',
                )
                winreg.SetValueEx(
                    k, "DisplayIcon", 0, winreg.REG_SZ,
                    os.path.join(install_dir, APP_EXE_NAME),
                )
                winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        except Exception:
            pass

    def _finish_dialog(self, target: str):
        win = tk.Toplevel(self.root)
        win.title(f"{APP_NAME} Kurulum")
        win.geometry("420x180")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text="✔ Kurulum tamamlandı",
                 font=("Segoe UI", 13, "bold"), fg="#059669").pack(pady=(20, 6))
        tk.Label(win, text=f"{APP_NAME} başarıyla kuruldu:\n{target}",
                 font=("Segoe UI", 9), fg="#374151", justify="center").pack(pady=(0, 12))
        tk.Checkbutton(win, text=f"{APP_NAME} uygulamasını şimdi başlat",
                       variable=self.launch_after, font=("Segoe UI", 9)).pack()
        def _close():
            try:
                if self.launch_after.get():
                    exe = os.path.join(target, APP_EXE_NAME)
                    subprocess.Popen([exe], cwd=target)
            finally:
                win.destroy()
                self.root.destroy()
        tk.Button(win, text="Bitir", width=12,
                  font=("Segoe UI", 10, "bold"),
                  bg="#2563eb", fg="white", activebackground="#1d4ed8",
                  relief="flat", command=_close).pack(pady=14)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--uninstall":
        target = args[1] if len(args) >= 2 else os.path.dirname(sys.executable)
        sys.exit(run_uninstall(target))

    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
'''


def _write_stub(work_dir: Path) -> Path:
    """Stub kaynak dosyasını sabitler ile birlikte work_dir/stub.py'a yazar."""
    header = (
        f'APP_NAME = "{APP_NAME}"\n'
        f'APP_VERSION = "{APP_VERSION}"\n'
        f'APP_PUBLISHER = "{APP_PUBLISHER}"\n'
        f'APP_EXE_NAME = "{APP_EXE_NAME}"\n'
        f'DEFAULT_INSTALL_DIR = r"{DEFAULT_INSTALL_DIR}"\n'
    )
    stub = work_dir / "stub.py"
    stub.write_text(header + STUB_BODY, encoding="utf-8")
    return stub


def main() -> int:
    if not DIST_APP_DIR.exists():
        print(f"[HATA] PyInstaller cikti klasoru bulunamadi: {DIST_APP_DIR}")
        print("       Once: python -m PyInstaller --clean --noconfirm GloveTestSystem.spec")
        return 1

    print(f"[1/4] Calisma klasoru hazirlaniyor: {WORK_DIR}")
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    print("[2/4] Stub installer yaziliyor")
    stub = _write_stub(WORK_DIR)

    print("[3/4] PyInstaller --onefile calisiyor (5–10 dk surebilir)")
    pyi_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--clean",
        "--noconfirm",
        "--name", "UltraGITS_Setup",
        # Tüm dist/GloveTestSystem klasörünü 'app' altına göm
        "--add-data", f"{DIST_APP_DIR};app",
        "--distpath", str(WORK_DIR / "dist"),
        "--workpath", str(WORK_DIR / "build"),
        "--specpath", str(WORK_DIR),
    ]
    if ICON_FILE.exists():
        pyi_cmd += ["--icon", str(ICON_FILE)]
    pyi_cmd.append(str(stub))

    res = subprocess.run(pyi_cmd, cwd=WORK_DIR)
    if res.returncode != 0:
        print(f"[HATA] PyInstaller hatasi (exit={res.returncode})")
        return res.returncode

    built = WORK_DIR / "dist" / "UltraGITS_Setup.exe"
    if not built.exists():
        print(f"[HATA] Beklenen exe uretilmedi: {built}")
        return 2

    print(f"[4/4] Cikti kopyalaniyor: {OUT_EXE}")
    INSTALLER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUT_EXE.exists():
        try:
            OUT_EXE.unlink()
        except PermissionError:
            print("      ! Eski UltraGITS_Setup.exe kilitli, kopyalama basarisiz olabilir.")
    shutil.copy2(built, OUT_EXE)

    final_mb = OUT_EXE.stat().st_size / (1024 * 1024)
    print()
    print("=" * 56)
    print(f"  HAZIR: {OUT_EXE}")
    print(f"  Boyut: {final_mb:.1f} MB")
    print("=" * 56)
    print()
    print("Bu dosyayi hedef PC'ye kopyalayip cift tiklayarak kurabilirsiniz.")
    print("Kurulum sonrasi: C:\\Ultra GITS\\GloveTestSystem.exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
