# -*- mode: python ; coding: utf-8 -*-
# GloveTestSystem PyInstaller Spec File
# Proje kökünden çalıştır:  pyinstaller --clean --noconfirm GloveTestSystem.spec
#
# Bu spec hem GLT (klasik test akışı) hem de ORAPS (3D viewer + LAF +
# Weidmüller IO) modüllerini tek bir onedir paketinde toplar.

import os

from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
    collect_dynamic_libs,
)

block_cipher = None

# ── Toplanan varlıklar ──────────────────────────────────────────────────
# Hedef yollar _internal/ dizinine göre çözülür.
# Kodda  os.path.dirname(__file__) + "/../assets/"  kalıbı kullanılıyor;
# PyInstaller onedir modunda __file__  = _internal/<package>/mod.pyc
# olduğundan, assets -> _internal/assets  şeklinde eşleştiriyoruz.

_assets = os.path.join('src', 'assets')
_icons  = os.path.join(_assets, 'icons')
_viewer = os.path.join(_assets, 'viewer')
# NOT: ORAPS GLB modelleri (assets/models/) installer'a DAHIL EDILMEZ.
# "Sifir kurulum" prensibi: kullanici kendi GLB dosyasini Ayarlar > ORAPS
# ekraninda yukler. Pakete varsayilan model gomulmemelidir.

datas_list = [
    # Logolar & resimler
    (os.path.join(_assets, 'logo.jpg'),    'assets'),
    (os.path.join(_assets, 'logo.png'),    'assets'),
    (os.path.join(_assets, 'logo_v2.png'), 'assets'),
    (os.path.join(_assets, '1234.png'),    'assets'),
    (os.path.join(_assets, 'lccLogo.png'), 'assets'),
    (os.path.join(_assets, 'app_icon.ico'), 'assets'),
    # SVG ikonlar (tüm klasör)
    (_icons, os.path.join('assets', 'icons')),
    # ORAPS 3D viewer (three.js + HTML + JS bridge)
    (_viewer, os.path.join('assets', 'viewer')),
]

# ── QtWebEngine için ek data + ikili dosyalar ─────────────────────────────
# PyInstaller PyQt5 hook'u QtWebEngineProcess.exe, translations, locales ve
# resources/*.pak dosyalarını genelde otomatik toplar; yine de açıkça
# çağırarak garanti altına alıyoruz.
try:
    datas_list += collect_data_files('PyQt5.QtWebEngineWidgets')
    datas_list += collect_data_files('PyQt5.QtWebEngineCore')
    datas_list += collect_data_files('PyQt5.QtWebChannel')
except Exception:
    pass

webengine_binaries = []
try:
    webengine_binaries += collect_dynamic_libs('PyQt5.QtWebEngineWidgets')
    webengine_binaries += collect_dynamic_libs('PyQt5.QtWebEngineCore')
except Exception:
    pass

# ── Hidden imports ──────────────────────────────────────────────────────
hidden = [
    # PyQt5 core
    'PyQt5.sip',
    'PyQt5.QtPrintSupport',
    'PyQt5.QtSvg',
    # PyQt5 WebEngine (ORAPS 3D viewer)
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtWebEngineCore',
    'PyQt5.QtWebChannel',
    'PyQt5.QtNetwork',
    # Serial
    'serial',
    'serial.tools',
    'serial.tools.list_ports',
    'serial.tools.list_ports_windows',
    # bcrypt
    'bcrypt',
    'bcrypt._bcrypt',
    # Matplotlib (Qt5 backend)
    'matplotlib',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_agg',
    'matplotlib.pyplot',
    'matplotlib.lines',
    'matplotlib.figure',
    # Cryptography
    'cryptography',
    'cryptography.fernet',
    'cryptography.hazmat.backends',
    'cryptography.hazmat.backends.openssl',
    'cryptography.hazmat.primitives.kdf.pbkdf2',
    'cryptography.hazmat.primitives.serialization',
    'cryptography.hazmat.primitives.hashes',
    'cryptography.hazmat.primitives.ciphers',
    # ReportLab
    'reportlab',
    'reportlab.lib.pagesizes',
    'reportlab.lib.units',
    'reportlab.platypus',
    # Pillow
    'PIL',
    'PIL._tkinter_finder',
    # Standart kütüphane
    'json', 'sqlite3', 'threading', 'datetime', 'csv', 'io',
]

# pymodbus (Weidmüller IO) — sürüm 3.x submodülleri dinamik yüklendiği için
# tüm paketi toplamak en güvenlisi.
try:
    hidden += collect_submodules('pymodbus')
except Exception:
    pass

# ORAPS paketi (oraps.*) — main.py'dan transitif import yetersiz kalabilir
# (bazı submodüller koşullu yükleniyor); submodülleri açıkça toplamak
# çakışma riskini sıfırlar.
try:
    hidden += collect_submodules('oraps')
except Exception:
    pass

# ── Analysis ─────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join('src', 'main.py')],
    pathex=['src'],
    binaries=webengine_binaries,
    datas=datas_list,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',
        'test',
        'xmlrpc', 'pydoc',
        'IPython', 'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── Build ────────────────────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,       # onedir modu
    name='GloveTestSystem',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,               # GUI — konsol penceresi yok
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join('src', 'assets', 'app_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    # WebEngine ikilileri UPX ile bozulabiliyor — sıkıştırma dışı bırak.
    upx_exclude=[
        'QtWebEngineProcess.exe',
        'qtwebengineprocess.exe',
        'd3dcompiler_47.dll',
        'libGLESv2.dll',
        'libEGL.dll',
        'opengl32sw.dll',
        'icudtl.dat',
    ],
    name='GloveTestSystem',
)
