"""
Glove Test Control System
21 CFR Part 11 Compliant Application
Main Entry Point
"""

import sys
import os
import ctypes
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QFont

# QtWebEngine MUST be imported before QApplication is created (PyQt5 rule).
# Wrapped in try/except so the app still launches if PyQtWebEngine is missing
# — Oraps viewer will then show a friendly fallback message.
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
try:
    from PyQt5 import QtWebEngineWidgets  # noqa: F401 — side-effect import
except ImportError:
    pass

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# ── Frozen (PyInstaller) support ──────────────────────────────────────
# When running as a compiled .exe, set CWD to the exe's own directory
# so that relative paths (database/, reports/, batches/) resolve correctly.
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from core.database import Database
from core.auth import AuthManager
from core.audit import AuditManager
from core.signature import SignatureManager
from core.esp32_comm import ESP32Communicator
from utils.pdf_generator import PDFReportGenerator
from utils.storage_config import (get_storage_base_path, get_database_path, get_reports_path,
                                    get_batches_path, _get_writable_data_dir,
                                    backup_database, restore_database_from_backup)
from utils.app_logger import get_logger
from gui.main_window import MainWindow
import traceback
from datetime import datetime

_logger = get_logger("main")

def exception_hook(exctype, value, tb):
    """Global exception handler to log crashes"""
    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    _logger.critical("Unhandled exception:\n%s", error_msg)
    
    # Write crash log to writable data dir (not CWD which may be Program Files)
    _data = _get_writable_data_dir()
    crash_path = os.path.join(_data, "crash_log.txt") if _data else "crash_log.txt"
    try:
        os.makedirs(os.path.dirname(crash_path) if os.path.dirname(crash_path) else '.', exist_ok=True)
    except OSError:
        pass
    
    with open(crash_path, "a", encoding="utf-8") as f:
        f.write(f"\n\n--- CRASH REPORT {datetime.now()} ---\n")
        f.write(error_msg)
    
    # Try to show message box if app is still running
    try:
        QMessageBox.critical(None, "Critical Error", 
                           f"Uygulama beklenmeyen bir hata nedeniyle kapandı.\nLog: crash_log.txt\nHata: {str(value)}")
    except:
        pass
    
    sys.exit(1)

sys.excepthook = exception_hook

# ── Single Instance Lock (Global Mutex — tüm Windows kullanıcıları için) ──
_mutex_handle = None

class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", ctypes.c_ulong),
                 ("lpSecurityDescriptor", ctypes.c_void_p),
                 ("bInheritHandle", ctypes.c_int)]

def _make_everyone_sa():
    """NULL DACL ile tüm kullanıcılara erişim veren SECURITY_ATTRIBUTES oluşturur."""
    advapi32 = ctypes.windll.advapi32
    sd = ctypes.create_string_buffer(64)
    # SECURITY_DESCRIPTOR_REVISION = 1
    if not advapi32.InitializeSecurityDescriptor(ctypes.byref(sd), 1):
        return None
    # NULL DACL → herkes erişebilir
    if not advapi32.SetSecurityDescriptorDacl(ctypes.byref(sd), True, None, False):
        return None
    sa = _SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(sa)
    sa.lpSecurityDescriptor = ctypes.addressof(sd)
    sa.bInheritHandle = 0
    return sa, sd  # sd'yi canlı tutmalıyız

_sa_ref = None  # prevent GC

def acquire_single_instance():
    """Windows Named Mutex ile tek instance kilidi. Başka kullanıcı da açamaz."""
    global _mutex_handle, _sa_ref
    kernel32 = ctypes.windll.kernel32
    MUTEX_NAME = "Global\\UltraGITS_SingleInstance_Lock"

    sa_result = _make_everyone_sa()
    if sa_result:
        sa, sd = sa_result
        _sa_ref = (sa, sd)
        _mutex_handle = kernel32.CreateMutexW(ctypes.byref(sa), False, MUTEX_NAME)
    else:
        _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)

    last_error = ctypes.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    ERROR_ACCESS_DENIED = 5
    if last_error in (ERROR_ALREADY_EXISTS, ERROR_ACCESS_DENIED):
        if _mutex_handle:
            kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None
        return False
    return True

def release_single_instance():
    """Mutex'i serbest bırak."""
    global _mutex_handle
    if _mutex_handle:
        ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None

def main():
    """Main application entry point"""
    
    # Create QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("Glove Test Control System")
    app.setStyle("Fusion")
    
    # ── Tek instance kontrolü ──
    if not acquire_single_instance():
        QMessageBox.warning(None, "Uygulama Zaten Açık",
                           "Ultra GITS başka bir kullanıcı tarafından zaten çalışıyor.\n"
                           "Aynı anda yalnızca bir oturum açılabilir.")
        sys.exit(0)
    
    # Set default font
    font = QFont()
    font.setFamily("Segoe UI")
    font.setPointSize(10)
    app.setFont(font)
    
    # Global Stylesheet for Tooltips (Fix for black-on-black issue)
    app.setStyleSheet("""
        QToolTip { 
            background-color: #F8F9FA; 
            color: #000000; 
            border: 1px solid #767676; 
            font-size: 12px; 
        }
    """)
    
    try:
        # ── Resolve storage paths from config ──
        base_path = get_storage_base_path()
        db_path = get_database_path(base_path if base_path else None)
        reports_path = get_reports_path(base_path if base_path else None)
        batches_path = get_batches_path(base_path if base_path else None)

        # ── DB yoksa yedekten geri yükle ──
        if restore_database_from_backup(db_path):
            _logger.info("Database restored from backup")

        # Initialize core components
        db = Database(db_path)

        # ── Her açılışta yedeği güncelle ──
        if backup_database(db_path):
            _logger.debug("Database backup updated")
        auth = AuthManager(db)
        audit = AuditManager(db, auth)
        auth.set_audit_manager(audit)
        sig_manager = SignatureManager(db, auth, audit)
        esp32 = ESP32Communicator()
        pdf_gen = PDFReportGenerator(db, reports_path, batches_path)
        
        # Log system startup
        audit.log_system_event("SYSTEM_STARTUP", "INFO", "Application started")
        
        # Create MainWindow HIDDEN — panels + callbacks ready, data flows immediately
        main_window = MainWindow(db, esp32, auth, audit, sig_manager, pdf_gen)

        # Faz-11: Uygulama ORABS Genel Bakış (kilitli/visitor) ile açılır,
        # login dialogu pencerenin ÜZERİNDE modal gelir — logout sonrası
        # görünümle birebir aynı UX. Login iptal edilirse pencere kilitli
        # kalır; '🔒 Giriş Yap' butonuyla tekrar denenebilir. Zorunlu şifre
        # değişikliği ve on_login_complete akışı _prompt_login_modal içinde.
        main_window.show_locked_startup()

        app.exec_()
        
        # Final cleanup
        if esp32.is_connected:
            esp32.disconnect()
        
        audit.log_system_event("SYSTEM_SHUTDOWN", "INFO", "Application closed normally")
        
        release_single_instance()
        sys.exit(0)
    
    except Exception as e:
        _logger.critical("Application startup error: %s", e, exc_info=True)
        QMessageBox.critical(None, "Application Error", 
                           f"A critical error occurred:\n{str(e)}\n\nThe application will now close.")
        release_single_instance()
        sys.exit(1)


if __name__ == "__main__":
    main()
