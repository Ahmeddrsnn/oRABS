"""
Main Application Window
Central interface integrating all components
"""

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTabWidget, QMenuBar, QMenu, QAction, QStatusBar,
                             QLabel, QMessageBox, QDialog, QFormLayout, QLineEdit,
                             QComboBox, QDialogButtonBox, QPushButton)
from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtGui import QIcon, QFont, QPixmap
import os
import sys
import struct
import zlib
from datetime import datetime
from utils.translations import Translations
from utils.app_logger import get_logger

_logger = get_logger("main_window")

ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
def get_icon(name):
    return QIcon(os.path.join(ICON_DIR, f"{name}.svg"))


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self, database, esp32_comm, auth_manager, audit_manager, 
                 signature_manager, pdf_generator):
        super().__init__()
        # Frameless: title bar (küçült/büyüt/kapat) gizli. Bu flag
        # pencere oluşturulmadan ÖNCE set edildiği için runtime'da
        # setWindowFlags çağrısına gerek kalmaz → siyah flicker olmaz.
        # Admin/Supervisor/Operator hepsi frameless; üst header bar'da
        # zaten "Çıkış Yap" butonu mevcut.
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinMaxButtonsHint
        )
        
        self.db = database
        self.esp32 = esp32_comm
        self.auth = auth_manager
        self.audit = audit_manager
        self.sig_manager = signature_manager
        self.pdf_gen = pdf_generator
        
        # Logout requested flag
        self.logout_requested = False
        # Session-lock state (auto-logout uygulamayı kapatmaz; kilitler).
        self._locked = False
        self._lock_overlay = None
        
        # Idle timer for auto-logout
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.check_session_timeout)
        self.last_activity = datetime.now()
        
        # Install event filter on QApplication to capture ALL user activity globally
        from PyQt5.QtWidgets import QApplication
        QApplication.instance().installEventFilter(self)
        
        self.init_ui()
        
        # Ensure all active users have unique PINs assigned
        try:
            self.db.ensure_all_users_have_pins()
        except Exception as e:
            _logger.error("ensure_all_users_have_pins error: %s", e)
        
        # Register Callbacks — panels live forever, never destroyed
        self.esp32.set_crc_callback(self.handle_crc_report)
        if hasattr(self, 'layout_panel'):
            print("DEBUG: Registering New RFID Callback to LayoutPanel")
            self.esp32.set_new_rfid_callback(self.layout_panel.on_new_rfid_detected)

        # ── Bariyer sensör dinleyicisi (Faz-7) ─────────────────
        # Master USB CDC → BarrierListener QThread → BarrierManager (ana thread)
        # → oraps port motion event → 3D viewer mavi + audit.
        self.barrier_manager = None
        self.barrier_listener = None
        try:
            from core.barrier_listener import BarrierListener, BarrierManager
            self.barrier_manager = BarrierManager(
                self.db,
                self.oraps_panel.overview.bm,   # batch_manager
                self.audit,
                parent=self,
            )
            self.barrier_listener = BarrierListener(parent=self)
            # Sinyal → slot (ana thread'e queue'lanır otomatik)
            self.barrier_listener.barrier_event.connect(
                self.barrier_manager.handle_event
            )
            # Bağlantı durumunu log'a düşür → auto-discover başarısız/başarılı
            # olduğunda teşhis kolaylaşır (Faz-8).
            def _on_barrier_conn(ok, msg, _log=_logger):
                if ok:
                    _log.info("BarrierListener bağlandı: %s", msg)
                else:
                    _log.warning("BarrierListener bağlanamadı: %s", msg)
            try:
                self.barrier_listener.connection_status.connect(_on_barrier_conn)
            except Exception:
                pass
            # Overview motion güncellemesini yakala (5sn hold + expire için)
            try:
                self.barrier_manager.port_motion_from_barrier.connect(
                    self.oraps_panel.overview.on_barrier_port_motion
                )
            except Exception:
                pass
            # Ayarlardan COM portunu al (boşsa auto-discover)
            try:
                _com = (self.db.get_setting('barrier_com_port', '') or '').strip()
                self.barrier_listener.set_port(_com)
            except Exception:
                pass
            self.barrier_listener.start()
            _logger.info("BarrierListener başlatıldı")
        except Exception as _e:
            _logger.warning("BarrierListener başlatılamadı: %s", _e)
    
    def init_ui(self):
        """Initialize UI components"""
        self.current_lang = self.db.get_language()
        self.translate_window_title()
        self.setMinimumSize(1200, 800)
        
        # Create central widget with tabs
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # ── Header widget'ları (outer sekme bar'ının corner'larına yerleştirilecek)
        # Sol corner: LCC logosu (kompakt). Sağ corner: kullanıcı + Pin/Şifre/Çıkış.
        # Alan tasarrufu için tek satırda dururlar; sekme yüksekliği 40px.
        self.header_logo = QLabel()
        logo_v2 = os.path.join(os.path.dirname(__file__), "..", "assets", "logo_v2.png")
        if os.path.exists(logo_v2):
            pixmap = QPixmap(logo_v2)
            # Corner widget: sekme yüksekliğine (40px) sığması için küçük ölçek
            self.header_logo.setPixmap(pixmap.scaled(180, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.header_logo.setContentsMargins(6, 0, 8, 0)

        self._session_corner = QWidget()
        session_layout = QHBoxLayout(self._session_corner)
        session_layout.setContentsMargins(0, 0, 8, 0)
        session_layout.setSpacing(8)
        
        self.user_label = QLabel()
        self.user_label.setStyleSheet("font-weight: 600; color: #374151; font-family: 'Segoe UI'; font-size: 13px;")
        session_layout.addWidget(self.user_label)

        self.pin_btn = QPushButton("🔑 Pin Görüntüle")
        self.pin_btn.setCursor(Qt.PointingHandCursor)
        self.pin_btn.setStyleSheet("""
            QPushButton {
                background-color: #EFF6FF;
                color: #1D4ED8;
                border: 1px solid #BFDBFE;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #DBEAFE;
            }
            QPushButton:disabled {
                background-color: #F3F4F6;
                color: #9CA3AF;
                border-color: #E5E7EB;
            }
        """)
        self.pin_btn.clicked.connect(self.show_pin_dialog)
        session_layout.addWidget(self.pin_btn)

        self.change_pass_btn = QPushButton("🔒 Şifre Değiştir")
        self.change_pass_btn.setCursor(Qt.PointingHandCursor)
        self.change_pass_btn.setStyleSheet("""
            QPushButton {
                background-color: #FEF3C7;
                color: #92400E;
                border: 1px solid #FCD34D;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #FDE68A;
            }
            QPushButton:disabled {
                background-color: #F3F4F6;
                color: #9CA3AF;
                border-color: #E5E7EB;
            }
        """)
        self.change_pass_btn.clicked.connect(self.change_own_password)
        session_layout.addWidget(self.change_pass_btn)

        # Çıkış Yap / Giriş Yap butonu — kilit durumuna göre metin+renk değişir.
        # Aktif oturum: kırmızı "Çıkış Yap". Kilitli: yeşil "Giriş Yap".
        self.logout_btn = QPushButton()
        self.logout_btn.setCursor(Qt.PointingHandCursor)
        self.logout_btn.clicked.connect(self._on_logout_or_login_clicked)
        session_layout.addWidget(self.logout_btn)

        # ── Pencere kontrol butonları (Admin/Supervisor'a görünür) ─────
        # Frameless pencerede eksik olan minimize/restore/close karşılığı.
        # Operator/Viewer kiosk modunda gizlenir (bkz. _apply_window_mode_for_role).
        _WIN_CTRL_STYLE = """
            QPushButton {
                background-color: #F3F4F6;
                color: #374151;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 2px 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #E5E7EB;
            }
        """
        _WIN_CLOSE_STYLE = """
            QPushButton {
                background-color: #FEE2E2;
                color: #B91C1C;
                border: 1px solid #FCA5A5;
                border-radius: 6px;
                padding: 2px 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #EF4444;
                color: white;
            }
        """
        self.window_min_btn = QPushButton("🗕")
        self.window_min_btn.setToolTip("Küçült")
        self.window_min_btn.setCursor(Qt.PointingHandCursor)
        self.window_min_btn.setFixedSize(36, 28)
        self.window_min_btn.setStyleSheet(_WIN_CTRL_STYLE)
        self.window_min_btn.clicked.connect(self.showMinimized)
        session_layout.addWidget(self.window_min_btn)

        self.window_max_btn = QPushButton("🗗")
        self.window_max_btn.setToolTip("Pencere / Tam Ekran")
        self.window_max_btn.setCursor(Qt.PointingHandCursor)
        self.window_max_btn.setFixedSize(36, 28)
        self.window_max_btn.setStyleSheet(_WIN_CTRL_STYLE)
        self.window_max_btn.clicked.connect(self._toggle_window_maximized)
        session_layout.addWidget(self.window_max_btn)

        self.window_close_btn = QPushButton("✕")
        self.window_close_btn.setToolTip("Kapat")
        self.window_close_btn.setCursor(Qt.PointingHandCursor)
        self.window_close_btn.setFixedSize(36, 28)
        self.window_close_btn.setStyleSheet(_WIN_CLOSE_STYLE)
        self.window_close_btn.clicked.connect(self.close)
        session_layout.addWidget(self.window_close_btn)

        # Başlangıçta gizli — _apply_window_mode_for_role rol'e göre açar.
        self.window_min_btn.setVisible(False)
        self.window_max_btn.setVisible(False)
        self.window_close_btn.setVisible(False)

        # ── INNER tabs (GLT application) ─────────────────────────────
        # Holds all original GLT panels. Wrapped inside outer GLT tab.
        self.glt_tabs = QTabWidget()
        
        # Import GUI components
        from gui.esp_now_control import ESPNOWMasterPanel
        from gui.monitoring_panel import MonitoringPanel
        from gui.report_viewer import ReportViewer
        from gui.user_management import UserManagementPanel
        from gui.recipe_management import RecipeManagementPanel
        from gui.layout_panel import LayoutPanel
        from gui.batch_panel import BatchPanel
        from gui.rfid_panel import RFIDPanel
        from gui.settings_panel import SettingsPanel
        from gui.log_panel import LogPanel
        from oraps import OrapsMain
        from gui.audit_trail_panel import AuditTrailPanel
        
        # 1. Cihazlar (Devices)
        self.esp_now_control = ESPNOWMasterPanel(
            self.esp32, self.db, self.auth, self.audit
        )
        self.glt_tabs.addTab(self.esp_now_control, get_icon("cpu"), "") # Text set in update_ui_language
        
        # 2. Eldiven Portu (Glove Port)
        self.layout_panel = LayoutPanel(self.db, self.auth, self.esp32, self.audit)
        # Connect log signal to central logger
        self.layout_panel.log_signal.connect(self.esp_now_control.log)
        # Link for direct data push
        self.esp_now_control.set_layout_panel(self.layout_panel)
        self.glt_tabs.addTab(self.layout_panel, get_icon("hand"), "")

        # 3. Toplu Test (Batch)
        self.batch_panel = BatchPanel(self.db, self.esp32, self.auth, self.audit)
        self.batch_panel.set_pdf_generator(self.pdf_gen)
        self.esp_now_control.set_batch_panel(self.batch_panel)
        self.esp_now_control.set_pdf_generator(self.pdf_gen)
        self.glt_tabs.addTab(self.batch_panel, get_icon("play"), "")
        
        # 4. Reçete (Recipes)
        self.recipes = RecipeManagementPanel(
            self.db, self.esp32, self.auth, self.audit
        )
        self.glt_tabs.addTab(self.recipes, get_icon("file-text"), "")
        
        # 5. Rapor (Reports)
        self.reports = ReportViewer(
            self.db, self.pdf_gen, self.sig_manager, self.auth
        )
        self.glt_tabs.addTab(self.reports, get_icon("bar-chart"), "")
        
        # 6. Kayıtlar (Records/Logs) — Audit Trail görüntüleyici.
        # Şuanlık sekme gizli (kullanıcı isteği 2026-06-29); panel
        # instance'ı yine oluşturuluyor ki audit kayıtları zaten
        # AuditManager üzerinden yazılmaya devam etsin ve outer
        # 'Audit Trail' sekmesi tek görünür ekran olsun.
        self.logs = LogPanel(self.audit, self.pdf_gen)
        # self.glt_tabs.addTab(self.logs, get_icon("clipboard"), "")
        
        # 7. GLT Ayarlar (only GLT-specific settings: Logo/branding)
        # Faz-3 revised: GLT settings live inside the GLT app, not in outer.
        self.glt_settings = SettingsPanel(
            self.auth, self.db,
            visible_groups={'branding'},
            custom_header={'tr': 'GLT Ayarları', 'en': 'GLT Settings'},
            custom_subtitle={
                'tr': 'GLT uygulamasına özel ayarlar',
                'en': 'Settings specific to the GLT application',
            },
            audit_manager=self.audit,
        )
        self.glt_tabs.addTab(self.glt_settings, get_icon("settings"), "")
        self._glt_settings_added = True  # Track inner GLT Ayarlar tab (admin-only)
        
        # ── Shared application panels (moved to OUTER tabs) ──────────
        # Kullanıcı (Users) — Admin only, inserted dynamically into OUTER tabs
        self.user_mgmt = UserManagementPanel(
            self.db, self.auth, self.audit
        )
        self._user_mgmt_added = False  # Track if tab is currently visible
            
        # Ayarlar (Settings) — outer tab (general only).
        # Faz-3 revised: outer Ayarlar only hosts cross-application Genel
        # settings. GLT-specific ones live in glt_settings (GLT inner tab);
        # Oraps-specific ones will live inside the Oraps app (Faz-4+).
        # Faz-9: 'tab_visibility' grubu → Sekme Görünürlüğü kartı.
        self.settings_panel = SettingsPanel(
            self.auth, self.db,
            visible_groups={'general', 'storage', 'security',
                            'compliance', 'sysinfo', 'tab_visibility'},
            audit_manager=self.audit,
        )
        self.settings_panel.language_changed.connect(self.update_ui_language)
        # Faz-9: sekme görünürlüğü save sonrası uygula.
        try:
            self.settings_panel.tab_visibility_changed.connect(
                self._apply_tab_visibility_from_settings
            )
        except Exception:
            pass
        
        # Oraps application (Faz-4): 4 inner tabs in its own QTabWidget
        self.oraps_panel = OrapsMain(
            self.db, self.auth, self.audit, self.pdf_gen,
            esp32_comm=self.esp32,
            esp_now_control=self.esp_now_control,
        )
        # ORAPS Overview → GLT ana ekran navigasyonu
        self.oraps_panel.glt_card_clicked.connect(self._on_overview_glt_card_clicked)

        # ESP-NOW Master'dan RFID algılama/uzaklaşma → ORAPS 3D viewer'da
        # eşleşen glove port mesh'ini yeşil/nötr renklendir.
        try:
            self.esp_now_control.rfid_state_changed.connect(
                self.oraps_panel.overview.on_rfid_state_changed
            )
        except Exception:
            pass

        # Central Audit Trail panel (Faz-2, cross-application)
        self.audit_panel = AuditTrailPanel(self.audit, self.pdf_gen)
        
        # Common tab style
        _tab_style = """
            QTabBar::tab {
                height: 40px;
                padding: 0 20px;
                margin-right: 2px;
                font-family: 'Segoe UI';
                font-size: 14px;
                color: #4B5563;
                background: #F3F4F6;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                color: #2563EB;
                border-bottom: 2px solid #2563EB;
                font-weight: 600;
            }
            QTabBar::tab:hover {
                background: #E5E7EB;
            }
            QTabWidget::pane {
                border: none;
                background: #FFFFFF;
            }
        """
        self.glt_tabs.setStyleSheet(_tab_style)
        
        # Inner tab change signal (preserves original refresh behavior)
        self.glt_tabs.currentChanged.connect(self.on_inner_tab_changed)
        
        # ── OUTER tabs (application shell) ───────────────────────────
        # Order: [GLT] [ORAPS] [KULLANICILAR* (Admin only)] [AYARLAR]
        # Outer tabs share the same compact look as inner but a touch wider
        # so short labels like "ORAPS" don't feel cramped.
        _outer_tab_style = """
            QTabWidget::pane {
                border: none;
                background: #FFFFFF;
            }
            QTabBar::tab {
                min-width: 110px;
                height: 40px;
                padding: 0 22px;
                margin-right: 2px;
                font-family: 'Segoe UI';
                font-size: 14px;
                color: #4B5563;
                background: #F3F4F6;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                color: #2563EB;
                border-bottom: 2px solid #2563EB;
                font-weight: 600;
            }
            QTabBar::tab:hover {
                background: #E5E7EB;
            }
        """
        self.outer_tabs = QTabWidget()
        self.outer_tabs.addTab(self.oraps_panel, "")           # 0: ORABS (ana uygulama)
        self.outer_tabs.addTab(self.glt_tabs, "")              # 1: GLT (yardımcı)
        # 2: KULLANICI (Admin only, inserted dynamically into outer_tabs
        #     immediately before the Audit Trail tab on login_complete)
        self.outer_tabs.addTab(self.audit_panel,
                               get_icon("clipboard"), "")      # 2/3: AUDIT TRAIL
        self.outer_tabs.addTab(self.settings_panel,
                               get_icon("settings"), "")       # 3/4: AYARLAR
        self.outer_tabs.setStyleSheet(_outer_tab_style)
        self.outer_tabs.currentChanged.connect(self.on_outer_tab_changed)
        # Header header_container yerine sekme bar corner'ları:
        # sol: LCC logosu, sağ: kullanıcı bilgisi + Pin/Şifre/Çıkış (Giriş).
        self.outer_tabs.setCornerWidget(self.header_logo, Qt.TopLeftCorner)
        self.outer_tabs.setCornerWidget(self._session_corner, Qt.TopRightCorner)
        
        layout.addWidget(self.outer_tabs)
        
        central_widget.setLayout(layout)
        
        self.update_ui_language(self.current_lang) # Finalize text
        
        # Create status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

        # IO modül bağlantı LED'i (status bar sağ tarafı)
        self.wm_status_lbl = QLabel("● IO modül kontrol ediliyor…")
        self.wm_status_lbl.setStyleSheet(
            "color:#9ca3af;font-weight:600;font-size:12px;"
            "padding:2px 10px;background:#f3f4f6;border-radius:10px;"
        )
        self.wm_status_lbl.setToolTip("IO modülleri sorgulanıyor…")
        self._status_bar.addPermanentWidget(self.wm_status_lbl)

        # WeidmullerManager lazy-init (DB ready, audit ready)
        try:
            from core.weidmuller_manager import WeidmullerManager
            self._wm_manager = WeidmullerManager(self.db, self.auth, self.audit)
        except Exception as e:
            self._wm_manager = None
            _logger.warning(f"WeidmullerManager init failed: {e}")

        self._wm_timer = QTimer(self)
        self._wm_timer.setInterval(10_000)
        self._wm_timer.timeout.connect(self._refresh_wm_status)
        self._wm_timer.start()
        QTimer.singleShot(800, self._refresh_wm_status)

        # ESP32 connection status removed as per user request
        # self.esp32_status_label = QLabel("ESP32: Disconnected")
        # self.esp32_status_label.setStyleSheet("color: red;")
        # self.statusBar.addPermanentWidget(self.esp32_status_label)

    def _refresh_wm_status(self):
        """Yapılandırılmış Weidmüller IO modüllerini DB'den oku, ilk gerçek
        modüle hızlı TCP probe at, sonucu status bar LED'ine yansıt."""
        import socket as _sock
        wm = getattr(self, '_wm_manager', None)
        if wm is None:
            self._set_wm_status(False, "WeidmullerManager başlatılamadı.")
            return
        try:
            mods = wm.list_modules(only_active=True)
        except Exception as e:
            self._set_wm_status(False, f"Modül listesi okunamadı: {e}")
            return
        if not mods:
            self._set_wm_status(
                False,
                "Ayarlar → ORAPS → Weidmüller IO Modüllerini Düzenle "
                "menüsünden bir modül ekleyin.",
            )
            return
        target = mods[0]
        host = target['host']
        port = int(target['port'])
        ok = False
        try:
            with _sock.create_connection((host, port), timeout=0.6):
                ok = True
        except OSError:
            ok = False
        if ok:
            self._set_wm_status(
                True,
                f"{target['name']} @ {host}:{port} erişilebilir. "
                f"({len(mods)} modül)",
            )
        else:
            self._set_wm_status(
                False,
                f"{target['name']} @ {host}:{port} TCP bağlantısı kurulamadı.",
            )

    def _set_wm_status(self, connected: bool, hint: str = ''):
        if not hasattr(self, 'wm_status_lbl') or self.wm_status_lbl is None:
            return
        if connected:
            text = "● IO modül bağlı"
            color = "#16a34a"
        else:
            text = "● IO modül bağlı değil"
            color = "#dc2626"
        self.wm_status_lbl.setText(text)
        self.wm_status_lbl.setStyleSheet(
            f"color:{color};font-weight:600;font-size:12px;"
            f"padding:2px 10px;background:#f3f4f6;border-radius:10px;"
        )
        self.wm_status_lbl.setToolTip(hint or '')

    def _on_overview_glt_card_clicked(self, device_name: str):
        """ORAPS Overview'da bir GLT cihaz kartına tıklandığında SADECE
        GLT ana sekmesine geç (outer'da GLT'nin güncel indeksi + glt_tabs 0
        ESP-NOW Master). Cihaz seçimi / detay diyaloğu açılmaz — kullanıcı
        orada manuel seçer."""
        try:
            glt_idx = self.outer_tabs.indexOf(self.glt_tabs)
            if glt_idx >= 0:
                self.outer_tabs.setCurrentIndex(glt_idx)
            self.glt_tabs.setCurrentIndex(0)           # ESP-NOW Master
        except Exception:
            pass

    def translate_window_title(self):
        self.setWindowTitle("Ultra GITS - 21 CFR Part 11")
        # Window icon
        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "lccLogo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def update_ui_language(self, lang_code):
        """Update all main window text to target language"""
        self.current_lang = lang_code
        self.translate_window_title()
        
        # Session labels (with None check for login screen)
        prefix = "Oturum" if lang_code == 'tr' else "Session"
        if self.auth.current_user:
            self.user_label.setText(f"{prefix}: {self.auth.current_user['full_name']} ({self.auth.current_user['role']})")
        else:
            self.user_label.setText(f"{prefix}: Not Logged In")
        # Kilitliyken buton "Giriş Yap" olarak kalır; dil değişikliği geçmez.
        if not getattr(self, '_locked', False):
            self.logout_btn.setText(Translations.t('logout', lang_code))
        
        # Tab names (Iterate by index to be safe)
        tab_keys = [
            'tab_dashboard',
            'tab_layout',
            'tab_recipes',
            'tab_reports', # Need to add this to translations
            'tab_logs',
            'tab_users',   # Need to add this to translations
            'tab_settings'
        ]
        
        # Note: Tab count might differ if user is admin. 
        # Map widgets to keys for robustness
        inner_tab_map = {
            self.esp_now_control: 'tab_dashboard',
            self.layout_panel: 'tab_layout',
            self.batch_panel: 'tab_batch',
            self.recipes: 'tab_recipes',
            self.reports: 'tab_reports',
            self.logs: 'tab_logs',
            self.glt_settings: 'tab_settings',
        }
        for i in range(self.glt_tabs.count()):
            widget = self.glt_tabs.widget(i)
            if widget in inner_tab_map:
                key = inner_tab_map[widget]
                self.glt_tabs.setTabText(i, Translations.t(key, lang_code))
        
        # Outer tabs (application shell)
        outer_tab_map = {
            self.glt_tabs: 'tab_glt',
            self.oraps_panel: 'tab_oraps',
            self.audit_panel: 'tab_audit',
            self.settings_panel: 'tab_settings',
        }
        if hasattr(self, 'user_mgmt'):
            outer_tab_map[self.user_mgmt] = 'tab_users'
        for i in range(self.outer_tabs.count()):
            widget = self.outer_tabs.widget(i)
            if widget in outer_tab_map:
                key = outer_tab_map[widget]
                self.outer_tabs.setTabText(i, Translations.t(key, lang_code))

        # Push language into panels that own internal text
        if hasattr(self, 'audit_panel'):
            self.audit_panel.apply_language(lang_code)
        # Sync GLT inner settings page (its hidden language combo + label texts)
        if hasattr(self, 'glt_settings') and self.glt_settings.current_lang != lang_code:
            self.glt_settings.current_lang = lang_code
            try:
                idx = self.glt_settings.lang_combo.findData(lang_code)
                if idx >= 0:
                    self.glt_settings.lang_combo.blockSignals(True)
                    self.glt_settings.lang_combo.setCurrentIndex(idx)
                    self.glt_settings.lang_combo.blockSignals(False)
            except Exception:
                pass
            self.glt_settings.translate_ui()

    def on_inner_tab_changed(self, index):
        """Handle GLT inner tab rotation/refresh"""
        widget = self.glt_tabs.widget(index)
        if hasattr(widget, 'refresh_logs'):
            widget.refresh_logs()
        elif hasattr(widget, 'refresh_map'):
            widget.refresh_map()
        elif hasattr(widget, 'load_test_records'):
            widget.load_test_records()

    def on_outer_tab_changed(self, index):
        """Handle outer application tab change (ORABS/GLT/Users/Audit/Settings)"""
        try:
            widget = self.outer_tabs.widget(index)
        except Exception:
            widget = None
        # ORABS sekmesine her girişte Genel Bakış (Overview) iç sekmesine dön.
        if widget is getattr(self, 'oraps_panel', None):
            try:
                self.oraps_panel.tabs.setCurrentIndex(0)
            except Exception:
                pass
    
    def create_menu_bar(self):
        """Create application menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        logout_action = QAction("&Logout", self)
        logout_action.setShortcut("Ctrl+L")
        logout_action.triggered.connect(self.logout)
        file_menu.addAction(logout_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Device menu
        device_menu = menubar.addMenu("&Device")
        
        connect_action = QAction("&Connect to ESP32", self)
        connect_action.triggered.connect(self.connect_device)
        device_menu.addAction(connect_action)
        
        disconnect_action = QAction("&Disconnect", self)
        disconnect_action.triggered.connect(self.disconnect_device)
        device_menu.addAction(disconnect_action)
        
        # Admin menu
        admin_menu = menubar.addMenu("&Admin")
        
        create_user_action = QAction("Create &User", self)
        create_user_action.triggered.connect(self.create_user)
        admin_menu.addAction(create_user_action)
        
        view_audit_action = QAction("View &Audit Trail", self)
        view_audit_action.triggered.connect(self.view_audit_trail)
        admin_menu.addAction(view_audit_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        compliance_action = QAction("&21 CFR Part 11 Info", self)
        compliance_action.triggered.connect(self.show_compliance_info)
        help_menu.addAction(compliance_action)
    
    def connect_device(self):
        """Connect to ESP32 device"""
        # This is handled in test control panel
        glt_idx = self.outer_tabs.indexOf(self.glt_tabs)
        if glt_idx >= 0:
            self.outer_tabs.setCurrentIndex(glt_idx)
        self.glt_tabs.setCurrentIndex(0)
        QMessageBox.information(self, "Device Connection", 
                              "Use the Test Control tab to connect to ESP32 device.")
    
    def disconnect_device(self):
        """Disconnect from ESP32 device"""
        if self.esp32.is_connected:
            self.esp32.disconnect()
            QMessageBox.information(self, "Disconnected", "ESP32 device disconnected.")
    
    def create_user(self):
        """Create new user (Admin only)"""
        if not self.auth.has_permission('Admin'):
            QMessageBox.critical(self, "Permission Denied", 
                               "Only administrators can create users.")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Create New User")
        dialog.setModal(True)
        
        layout = QFormLayout()
        
        username_input = QLineEdit()
        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.Password)
        fullname_input = QLineEdit()
        email_input = QLineEdit()
        role_combo = QComboBox()
        role_combo.addItems(['Viewer', 'Operator', 'Supervisor', 'Admin'])
        
        layout.addRow("Username:", username_input)
        layout.addRow("Password:", password_input)
        layout.addRow("Full Name:", fullname_input)
        layout.addRow("Email:", email_input)
        layout.addRow("Role:", role_combo)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addRow(button_box)
        
        dialog.setLayout(layout)
        
        if dialog.exec_() == QDialog.Accepted:
            success, message = self.auth.create_user(
                username_input.text(),
                password_input.text(),
                fullname_input.text(),
                role_combo.currentText(),
                email_input.text()
            )
            
            if success:
                QMessageBox.information(self, "Success", message)
            else:
                QMessageBox.critical(self, "Error", message)
    
    def view_audit_trail(self):
        """View complete audit trail"""
        audit_records = self.audit.get_audit_trail()
        
        message = f"Total Audit Records: {len(audit_records)}\n\n"
        message += "Most Recent 10 Records:\n"
        message += "-" * 50 + "\n"
        
        for record in audit_records[:10]:
            message += f"{record['timestamp'][:19]} | {record['username']} | {record['action_type']}\n"
            message += f"   {record['description']}\n"
        
        QMessageBox.information(self, "Audit Trail", message)
    
    def show_about(self):
        """Show about dialog"""
        about_text = """
        <h2>Glove Test Control System</h2>
        <p><b>Version:</b> 1.0.0</p>
        <p><b>21 CFR Part 11 Compliant</b></p>
        <br>
        <p>This software provides comprehensive control and reporting
        for glove testing devices with ESP32 communication.</p>
        <br>
        <p><b>Features:</b></p>
        <ul>
        <li>User authentication and role-based access control</li>
        <li>Electronic signatures</li>
        <li>Complete audit trails</li>
        <li>Data integrity verification</li>
        <li>ESP32 serial communication</li>
        <li>PDF report generation</li>
        </ul>
        """
        QMessageBox.about(self, "About", about_text)
    
    def show_compliance_info(self):
        """Show 21 CFR Part 11 compliance information"""
        compliance_text = """
        <h2>21 CFR Part 11 Compliance</h2>
        
        <p>This system implements the following 21 CFR Part 11 requirements:</p>
        
        <h3>Electronic Records (§ 11.10)</h3>
        <ul>
        <li>Validation of system</li>
        <li>Audit trails for all operations</li>
        <li>Authority checks for system access</li>
        <li>Data integrity verification (SHA-256)</li>
        <li>Secure, time-stamped audit trails</li>
        </ul>
        
        <h3>Electronic Signatures (§ 11.50, § 11.70)</h3>
        <ul>
        <li>Two-component signatures (username + password)</li>
        <li>Signature meaning association</li>
        <li>Cryptographic binding to signed data</li>
        <li>Non-repudiation</li>
        </ul>
        
        <h3>Security Features</h3>
        <ul>
        <li>Password complexity requirements</li>
        <li>Account lockout after failed attempts</li>
        <li>Role-based access control</li>
        <li>Session management</li>
        </ul>
        """
        QMessageBox.information(self, "21 CFR Part 11 Compliance", compliance_text)
    
    def on_login_complete(self):
        """Called after successful login — update UI for current user"""
        # Kilitli durumdan çıkışta buton/overlay resetle.
        self._exit_locked_state()
        # Update session label
        self.update_ui_language(self.current_lang)

        # Role-based outer tab visibility:
        #   Operator   -> sadece ORABS
        #   Supervisor -> ORABS + GLT + AUDIT + AYARLAR
        #   Admin      -> hepsi (KULLANICI dahil)
        self._apply_outer_tab_visibility()

        # Faz-9: Ayar-bazlı sekme gizleme (rol-bazlı üzerine sadece gizleme
        # yönünde uygulanır).
        self._apply_tab_visibility_from_settings()

        # Refresh settings panel admin-only elements
        if hasattr(self, 'settings_panel'):
            self.settings_panel.refresh_admin_visibility()
        if hasattr(self, 'glt_settings'):
            self.glt_settings.refresh_admin_visibility()

        # GLT iç Ayarlar sekmesini sadece admin görsün (operatöre gizli).
        self._apply_glt_settings_visibility()

        # Notify Oraps app of login (refreshes its batch panel + settings)
        if hasattr(self, 'oraps_panel') and hasattr(self.oraps_panel, 'on_login_complete'):
            self.oraps_panel.on_login_complete()

        # Update layout panel permissions for this user
        if hasattr(self, 'layout_panel'):
            self.layout_panel.apply_permissions()

        # Update recipe panel permissions for this user
        if hasattr(self, 'recipes'):
            self.recipes.apply_permissions()
        
        # Start idle timer for this session
        self.start_idle_timer()
        
        # Default seeded tabs after login: outer=ORABS (index 0), GLT inner=Devices
        self.outer_tabs.setCurrentIndex(0)
        self.glt_tabs.setCurrentIndex(0)

        # Operator / Viewer → tam ekran (task bar gizli). Admin/Supervisor → maximized.
        # Kiosk-zorlaması yok; kullanıcı Alt+Tab / Alt+F4 kullanabilir.
        self._apply_window_mode_for_role()

    def _apply_window_mode_for_role(self):
        """Rol'e göre pencere modu — FLICKER-FREE.

        Temel prensip: runtime'da setWindowFlags / showFullScreen /
        showNormal / showMaximized ÇAĞRILMAZ. Bu fonksiyonlar pencereyi
        yıkıp yeniden oluşturur → siyah flash.

        Tek kullanılan: setGeometry() + show(). FramelessWindowHint
        __init__'te bir kez set edildi, bir daha dokunulmaz.

        Operator/Viewer: setGeometry(screen.geometry()) → task bar dahil tüm ekran.
                         Win32 task bar auto-hide → fare en alta gelmedikçe gizli.
        Admin/Supervisor: setGeometry(screen.availableGeometry()) → task bar hariç alan.
                         Task bar görünür kalır.
        """
        try:
            role = self.auth.get_current_user_role()
        except Exception:
            role = None
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if not screen:
            if not self.isVisible():
                self.show()
            return

        # Pencere kontrol butonları sadece Admin/Supervisor'da görünür.
        show_win_ctrls = role in ('Admin', 'Supervisor')
        for _btn_name in ('window_min_btn', 'window_max_btn', 'window_close_btn'):
            _btn = getattr(self, _btn_name, None)
            if _btn is not None:
                _btn.setVisible(show_win_ctrls)

        if role in ('Operator', 'Viewer'):
            try:
                self._status_bar.setVisible(False)
            except Exception:
                pass
            self._set_taskbar_autohide(True)
            # DWM "exclusive fullscreen" algılamasını atlatmak için pencere
            # ekrandan 1 px BÜYÜK yapılır. Frameless pencere ekranın tam
            # boyutunu kapladığında Windows compositor bypass yapar →
            # tıklamalarda siyah flash. +1px ile DWM composition'da kalır;
            # taşan piksel görünmez (ekran dışında).
            g = screen.geometry()
            self.setGeometry(g.x(), g.y(), g.width(), g.height() + 1)
        else:
            try:
                self._status_bar.setVisible(True)
            except Exception:
                pass
            self._set_taskbar_autohide(False)
            # availableGeometry = task bar alanı hariç.
            self.setGeometry(screen.availableGeometry())

        if not self.isVisible():
            self.show()

    def _toggle_window_maximized(self):
        """Admin/Supervisor pencere kontrolü — 🗗 butonu.

        Flicker-free ilkeye sadık: showMaximized/showNormal kullanılmaz,
        yalnızca setGeometry ile mode toggle:
          - Maximized (≈ availableGeometry) ise → 1400×900 ortalanmış pencere.
          - Aksi halde → availableGeometry (task bar hariç).
        """
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if not screen:
            return
        avail = screen.availableGeometry()
        cur = self.geometry()
        is_max = (abs(cur.width() - avail.width()) < 20 and
                  abs(cur.height() - avail.height()) < 20)
        if is_max:
            w = min(1400, max(800, avail.width() - 200))
            h = min(900, max(600, avail.height() - 150))
            x = avail.x() + (avail.width() - w) // 2
            y = avail.y() + (avail.height() - h) // 2
            self.setGeometry(x, y, w, h)
        else:
            self.setGeometry(avail)

    def _set_full_geometry(self, screen):
        """Kullanılmıyor — geriye uyum için bırakıldı."""
        pass

    def _set_taskbar_autohide(self, hide: bool):
        """Windows task bar'ı auto-hide moduna al/geri getir (Win32 API).
        hide=True → task bar otomatik gizlenir (fare en alta gelince görünür).
        hide=False → task bar her zaman görünür (varsayılan Windows ayarı)."""
        try:
            import ctypes
            import ctypes.wintypes as wt

            ABM_GETSTATE = 0x04
            ABM_SETSTATE = 0x0A
            ABS_AUTOHIDE = 0x01
            ABS_ALWAYSONTOP = 0x02

            class APPBARDATA(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wt.DWORD),
                    ("hWnd", wt.HWND),
                    ("uCallbackMessage", wt.UINT),
                    ("uEdge", wt.UINT),
                    ("rc", wt.RECT),
                    ("lParam", ctypes.c_long),
                ]

            abd = APPBARDATA()
            abd.cbSize = ctypes.sizeof(APPBARDATA)

            shell32 = ctypes.windll.shell32

            if hide:
                # Mevcut durumu sakla (geri yüklemek için)
                if not hasattr(self, '_taskbar_was_autohide'):
                    state = shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd))
                    self._taskbar_was_autohide = bool(state & ABS_AUTOHIDE)
                abd.lParam = ABS_AUTOHIDE
                shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(abd))
            else:
                # Sadece biz değiştirmişsek geri al
                was_auto = getattr(self, '_taskbar_was_autohide', False)
                if not was_auto:
                    abd.lParam = ABS_ALWAYSONTOP
                    shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(abd))
        except Exception:
            pass

    def _apply_outer_tab_visibility(self):
        """Outer sekmeleri (GLT / KULLANICI / AUDIT / AYARLAR) role'e göre
        görünür/gizli kılar. ORABS daima görünür (index 0).

        Operator   -> sadece ORABS
        Supervisor -> ORABS + GLT + AUDIT + AYARLAR (KULLANICI gizli)
        Admin      -> hepsi
        Visitor    -> sadece ORABS (login öncesi defansif)

        Widget'lar canlı kalır (sinyal bağlantıları bozulmaz); sadece
        QTabWidget'a ekli olup olmadıkları değişir. Sıra: ORABS, GLT,
        KULLANICI, AUDIT, AYARLAR.
        """
        role = self.auth.get_current_user_role()
        is_admin = (role == 'Admin')
        is_operator = (role == 'Operator')
        show_main_set = role in ('Admin', 'Supervisor')  # GLT/AUDIT/AYARLAR

        # 1) Tüm dinamik tab'ları kaldır (ORABS sabit @ 0, dokunmuyoruz).
        for widget in (self.user_mgmt, self.glt_tabs,
                       self.audit_panel, self.settings_panel):
            idx = self.outer_tabs.indexOf(widget)
            if idx >= 0:
                self.outer_tabs.removeTab(idx)

        # 2) Role'e göre doğru sırada yeniden ekle.
        if show_main_set:
            self.outer_tabs.addTab(self.glt_tabs, "")
        if is_admin:
            self.outer_tabs.addTab(self.user_mgmt, get_icon("users"), "")
        if show_main_set:
            self.outer_tabs.addTab(self.audit_panel,
                                   get_icon("clipboard"), "")
            self.outer_tabs.addTab(self.settings_panel,
                                   get_icon("settings"), "")

        # 3) State flag'leri güncelle.
        self._user_mgmt_added = is_admin

        # 4) Tab başlıklarını re-translate et (sıra değişti).
        self.update_ui_language(self.current_lang)

    # Faz-9 ────────────────────────────────────────────────────────────
    def _apply_tab_visibility_from_settings(self):
        """DB'deki `tab_visible_*` ayarlarını uygula.

        Rol-bazlı `_apply_outer_tab_visibility` sekmeleri fiziksel olarak
        ekliyor/kaldırıyor; bu metod rol'e göre eklenmiş sekmelerden ayarda
        '0' olanları `setTabVisible(False)` ile gizler. Eklenmemiş
        sekmelere etki etmez (rol yetkisi override edilmez).
        """
        # Outer sekmeler
        outer_map = {
            'tab_visible_orabs': getattr(self, 'oraps_panel', None),
            'tab_visible_glt':   getattr(self, 'glt_tabs', None),
            'tab_visible_user':  getattr(self, 'user_mgmt', None),
            'tab_visible_audit': getattr(self, 'audit_panel', None),
        }
        for key, widget in outer_map.items():
            if widget is None:
                continue
            try:
                raw = str(self.db.get_setting(key, '1') or '1').strip()
                want = raw not in ('0', 'false', 'False')
                idx = self.outer_tabs.indexOf(widget)
                if idx >= 0:
                    self.outer_tabs.setTabVisible(idx, want)
            except Exception:
                pass
        # ORABS iç sekmeleri (oraps_main'e delegasyon)
        if hasattr(self, 'oraps_panel') and hasattr(
            self.oraps_panel, 'apply_tab_visibility'
        ):
            try:
                self.oraps_panel.apply_tab_visibility()
            except Exception:
                pass

    def _apply_glt_settings_visibility(self):
        """GLT iç 'Ayarlar' sekmesini sadece admin'e göster, operatöre gizle.

        Widget her zaman canlı kalır (`refresh_admin_visibility` ve language
        refresh çağrıları bozulmasın); sadece QTabWidget'a ekli olup olmaması
        değişir. Sekme her zaman GLT inner tabs'in en sağında kalır.
        """
        is_admin = self.auth.get_current_user_role() == 'Admin'
        currently_added = getattr(self, '_glt_settings_added', False)
        if is_admin and not currently_added:
            self.glt_tabs.addTab(self.glt_settings, get_icon("settings"), "")
            self._glt_settings_added = True
            # Tab başlığını yeniden çevir
            self.update_ui_language(self.current_lang)
        elif not is_admin and currently_added:
            idx = self.glt_tabs.indexOf(self.glt_settings)
            if idx >= 0:
                self.glt_tabs.removeTab(idx)
            self._glt_settings_added = False

    def logout(self):
        """Logout current user — hide window, return to login"""
        reply = QMessageBox.question(self, "Logout", 
                                    "Are you sure you want to logout?",
                                    QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.idle_timer.stop()
            self.auth.logout()

            # Outer tab'ları Visitor durumuna (sadece ORABS) sfırla.
            self._apply_outer_tab_visibility()

            # GLT iç Ayarlar sekmesini de kaldır (sonraki login'de
            # _apply_glt_settings_visibility uygun şekilde kontrol edecek).
            if getattr(self, '_glt_settings_added', False):
                idx = self.glt_tabs.indexOf(self.glt_settings)
                if idx >= 0:
                    self.glt_tabs.removeTab(idx)
                self._glt_settings_added = False

            # Lock layout panel buttons (no user = no admin)
            if hasattr(self, 'layout_panel'):
                self.layout_panel.apply_permissions()

            # Pencere aynı sekmede kalır — sadece kilit moduna geç. Butonlar
            # devre dışı, sağ üstte "🔒 Giriş Yap" butonu belirir. ORABS
            # canlı verisi güncellenmeye devam eder; kullanıcı aksiyonları
            # overlay ile engellenir.
            self.user_label.setText("Oturum yok · kilitli")
            self._enter_locked_state()

    def change_own_password(self):
        """Kullanıcının kendi şifresini değiştirmesi için dialog"""
        if not self.auth.current_user:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Şifre Değiştir")
        dlg.setFixedWidth(350)
        dlg.setStyleSheet("background-color: #F9FAFB;")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        form = QFormLayout()
        old_pass = QLineEdit()
        old_pass.setEchoMode(QLineEdit.Password)
        old_pass.setPlaceholderText("Mevcut şifreniz")
        form.addRow("Eski Şifre:", old_pass)

        new_pass = QLineEdit()
        new_pass.setEchoMode(QLineEdit.Password)
        new_pass.setPlaceholderText("Yeni şifre")
        form.addRow("Yeni Şifre:", new_pass)

        confirm_pass = QLineEdit()
        confirm_pass.setEchoMode(QLineEdit.Password)
        confirm_pass.setPlaceholderText("Yeni şifre tekrar")
        form.addRow("Tekrar:", confirm_pass)
        layout.addLayout(form)

        policy_lbl = QLabel("Şifre en az 8 karakter; büyük harf, küçük harf,\nrakam ve özel karakter içermelidir.")
        policy_lbl.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(policy_lbl)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText("Kaydet")
        btn_box.button(QDialogButtonBox.Cancel).setText("İptal")
        layout.addWidget(btn_box)
        btn_box.rejected.connect(dlg.reject)

        def on_save():
            old = old_pass.text()
            new = new_pass.text()
            confirm = confirm_pass.text()

            if not old or not new or not confirm:
                QMessageBox.warning(dlg, "Hata", "Tüm alanları doldurun.")
                return

            if not self.auth.verify_password(old, self.auth.current_user['password_hash']):
                QMessageBox.warning(dlg, "Hata", "Eski şifre yanlış.")
                return

            if new != confirm:
                QMessageBox.warning(dlg, "Hata", "Yeni şifreler eşleşmiyor.")
                return

            valid, msg = self.auth.validate_password_policy(new)
            if not valid:
                QMessageBox.warning(dlg, "Zayıf Şifre", msg)
                return

            if self.auth.verify_password(new, self.auth.current_user['password_hash']):
                QMessageBox.warning(dlg, "Hata", "Yeni şifre eski şifre ile aynı olamaz.")
                return

            user_id = self.auth.current_user['id']
            success, result = self.db.update_user(user_id, {'password': new})
            if success:
                # Refresh current_user password_hash
                updated = self.db.get_user_by_username(self.auth.current_user['username'])
                if updated:
                    self.auth.current_user['password_hash'] = updated['password_hash']
                QMessageBox.information(dlg, "Başarılı", "Şifreniz değiştirildi.")
                dlg.accept()
            else:
                QMessageBox.critical(dlg, "Hata", f"Şifre değiştirilemedi:\n{result}")

        btn_box.accepted.connect(on_save)
        dlg.exec_()

    def show_pin_dialog(self):
        """Show current user's PIN and allow regeneration"""
        try:
            user_id = self.auth.current_user.get('id')
            current_pin = self.db.get_user_pin(user_id) or "??????"

            dlg = QDialog(self)
            dlg.setWindowTitle("PIN Bilgisi")
            dlg.setFixedSize(300, 170)
            dlg.setStyleSheet("background-color: #F9FAFB;")

            layout = QVBoxLayout(dlg)
            layout.setContentsMargins(24, 20, 24, 20)
            layout.setSpacing(12)

            lbl_title = QLabel("Operatör PIN Kodunuz")
            lbl_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #374151;")
            lbl_title.setAlignment(Qt.AlignCenter)
            layout.addWidget(lbl_title)

            self._pin_display = QLabel(current_pin)
            self._pin_display.setAlignment(Qt.AlignCenter)
            self._pin_display.setStyleSheet("""
                font-size: 36px;
                font-weight: bold;
                color: #1D4ED8;
                letter-spacing: 8px;
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 8px;
                padding: 6px;
            """)
            layout.addWidget(self._pin_display)

            btn_layout = QHBoxLayout()
            update_btn = QPushButton("🔄 Güncelle")
            update_btn.setStyleSheet("""
                QPushButton {
                    background-color: #DBEAFE;
                    color: #1D4ED8;
                    border: 1px solid #93C5FD;
                    border-radius: 6px;
                    padding: 6px 14px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #BFDBFE; }
            """)
            close_btn = QPushButton("Kapat")
            close_btn.setStyleSheet("""
                QPushButton {
                    background-color: #F3F4F6;
                    color: #374151;
                    border: 1px solid #D1D5DB;
                    border-radius: 6px;
                    padding: 6px 14px;
                }
                QPushButton:hover { background-color: #E5E7EB; }
            """)
            close_btn.clicked.connect(dlg.accept)

            def regenerate_pin():
                try:
                    new_pin = self.db.generate_unique_pin()
                    self.db.update_user_pin(user_id, new_pin)
                    self._pin_display.setText(new_pin)
                    # Broadcast updated pins to all slaves
                    if hasattr(self, 'esp_now_control'):
                        self.esp_now_control.broadcast_user_pins()
                except Exception as ex:
                    QMessageBox.warning(dlg, "Hata", f"PIN güncellenemedi: {ex}")

            update_btn.clicked.connect(regenerate_pin)

            btn_layout.addWidget(update_btn)
            btn_layout.addWidget(close_btn)
            layout.addLayout(btn_layout)

            dlg.exec_()
        except Exception as e:
            QMessageBox.warning(self, "Hata", f"PIN dialog hatası: {e}")
    
    def start_idle_timer(self):
        """Start or restart the idle timer"""
        self.idle_timer.start(10000)  # Check every 10 seconds
        self.reset_idle_timer()

    def reset_idle_timer(self):
        """Reset activity timestamp"""
        self.last_activity = datetime.now()

    def eventFilter(self, obj, event):
        """Monitor user interaction to reset idle timer.

        Kilitli modda: aktif sekme İÇERİĞİNE (oraps_panel vb. tab page)
        yapılan mouse tıklamalarını yut ve kısa uyarı overlay'ini göster.
        Corner widget'lar (sağ üst 'Giriş Yap' vs.) ve tab bar tıklanabilir
        kalır (çünkü currentWidget() olan tab page onları içermez).
        """
        et = event.type()
        if et in (QEvent.MouseButtonPress, QEvent.KeyPress):
            self.reset_idle_timer()
            if et == QEvent.MouseButtonPress and getattr(self, '_locked', False):
                from PyQt5.QtWidgets import QWidget as _QW
                if isinstance(obj, _QW) and hasattr(self, 'outer_tabs'):
                    cur = self.outer_tabs.currentWidget()
                    if cur is not None and (obj is cur or cur.isAncestorOf(obj)):
                        self._flash_lock_overlay()
                        return True   # tıklamayı yut
        return super().eventFilter(obj, event)

    def check_session_timeout(self):
        """Check if user has been idle too long"""
        try:
            if not self.auth.current_user:
                self.idle_timer.stop()
                return
            timeout_str = self.db.get_setting('auto_logout_minutes', '15')
            timeout_mins = int(timeout_str)
            idle_delta = datetime.now() - self.last_activity
            
            if idle_delta.total_seconds() > (timeout_mins * 60):
                self.idle_timer.stop()
                self.handle_auto_logout()
        except Exception as e:
            _logger.error("Timeout check error: %s", e)

    def handle_auto_logout(self):
        """Otomatik oturum kilidi: uygulamayı KAPATMAZ, sadece kilitler.
        ORABS canlı verisi güncellenmeye devam eder; kullanıcı aksiyonları
        overlay ile engellenir. 'Giriş Yap'a basınca dialog aynı pencerenin
        üzerinde modal olarak açılır (parent=self)."""
        self.idle_timer.stop()
        self.auth.logout()
        self.user_label.setText("Oturum yok · kilitli")
        self._apply_outer_tab_visibility()   # rol yok → sadece ORABS görünür
        self._enter_locked_state()
        # Kilit sonrası uyarı (modal ama uygulamayı kapatmaz).
        QMessageBox.warning(
            self, "Oturum Kilitlendi",
            "Uzun süredir işlem yapmadığınız için oturumunuz kilitlendi.\n"
            f"({datetime.now().strftime('%d.%m.%Y %H:%M:%S')})\n\n"
            "Devam etmek için sağ üstteki 🔒 Giriş Yap butonuna basın."
        )

    def _on_logout_or_login_clicked(self):
        """Kilit durumuna göre çift işlev: aktif oturumda 'Çıkış Yap',
        kilitliyken 'Giriş Yap' (modal dialog açar)."""
        if getattr(self, '_locked', False):
            self._prompt_login_modal()
        else:
            self.logout()

    def _prompt_login_modal(self):
        """Kilitli durumda 'Giriş Yap' → LoginDialog'u bu pencerenin üstünde
        modal aç. Başarılıysa kilidi kaldır (ana sayfa altta kalır, kaybolmaz)."""
        try:
            from gui.login_dialog import LoginDialog
        except Exception:
            return
        dlg = LoginDialog(self.auth, parent=self)
        dlg.setWindowModality(Qt.ApplicationModal)
        if dlg.exec_() != dlg.Accepted:
            return
        # Zorunlu şifre değişikliği kontrolü (main.py'daki akışla aynı).
        cu = self.auth.current_user
        if cu and cu.get('must_change_password'):
            try:
                from gui.force_password_dialog import ForcePasswordChangeDialog
                if ForcePasswordChangeDialog(self.auth, parent=self).exec_() \
                        != ForcePasswordChangeDialog.Accepted:
                    self.auth.logout()   # kilit devam etsin
                    return
            except Exception:
                pass
        self._exit_locked_state()
        self.on_login_complete()

    def show_locked_startup(self):
        """Faz-11: Uygulama ORABS Genel Bakış ile (rol yok → kilitli/visitor
        görünüm) açılır; login dialogu pencere çizildikten hemen sonra
        üzerinde modal gelir — logout sonrası UX ile birebir aynı.
        Login iptal edilirse pencere kilitli kalır; kullanıcı sağ üstteki
        '🔒 Giriş Yap' butonuyla tekrar deneyebilir."""
        self.user_label.setText("Oturum yok · kilitli")
        self._apply_outer_tab_visibility()   # rol yok → sadece ORABS
        self._enter_locked_state()
        self.outer_tabs.setCurrentIndex(0)   # ORABS Genel Bakış
        self._apply_window_mode_for_role()   # rol yok → normal geometri + show
        # Login'i event loop başladıktan sonra aç → ana sayfa arkada çizilmiş
        # olur, dialog üstte modal belirir.
        QTimer.singleShot(0, self._prompt_login_modal)

    # ── Session lock (auto-logout kilidi) ────────────────────────
    def _enter_locked_state(self):
        """Kilit modu: butonlar disabled + logout butonu 'Giriş Yap' olur.
        Overlay HER ZAMAN GÖRÜNMEZ; kullanıcı kilitli sekme içeriğine tıklarsa
        2 saniyeliğine kısa uyarı olarak belirir. Sağ üst köşe (Giriş Yap
        vs.) her zaman tıklanabilir kalır. ORABS canlı verisi güncellenmeye
        devam eder."""
        self._locked = True
        self.pin_btn.setEnabled(False)
        self.change_pass_btn.setEnabled(False)
        self._set_logout_btn_locked_style()
        # Overlay yaratılır ama gizli kalır — sadece tıklamaya tepki verir.
        if not hasattr(self, '_lock_overlay') or self._lock_overlay is None:
            self._lock_overlay = QWidget(self.outer_tabs)
            self._lock_overlay.setStyleSheet(
                "background: rgba(15,23,42,0.55);"
            )
            _ol = QVBoxLayout(self._lock_overlay)
            _ol.setAlignment(Qt.AlignCenter)
            _lbl = QLabel(
                "🔒  Oturum Kilitli\n"
                "Devam etmek için sağ üstteki 'Giriş Yap' butonuna basın."
            )
            _lbl.setAlignment(Qt.AlignCenter)
            _lbl.setStyleSheet(
                "color:white;font-family:'Segoe UI';font-size:18px;"
                "font-weight:700;background:transparent;padding:24px;"
            )
            _ol.addWidget(_lbl)
            self._lock_overlay_timer = QTimer(self)
            self._lock_overlay_timer.setSingleShot(True)
            self._lock_overlay_timer.timeout.connect(self._lock_overlay.hide)
        self._lock_overlay.hide()

    def _flash_lock_overlay(self):
        """Kilitli sekme içeriğine tıklanınca 2 saniye görünen uyarı."""
        if not getattr(self, '_locked', False):
            return
        if not hasattr(self, '_lock_overlay') or self._lock_overlay is None:
            return
        cur = self.outer_tabs.currentWidget()
        if cur is not None:
            # Overlay'i aktif sekmenin üzerine yerleştir (corner widget'lar
            # etkilenmez → sağ üst hep tıklanabilir kalır).
            self._lock_overlay.setParent(cur)
            self._lock_overlay.setGeometry(cur.rect())
        self._lock_overlay.raise_()
        self._lock_overlay.show()
        self._lock_overlay_timer.start(2000)

    def _exit_locked_state(self):
        """Kilidi kaldır — butonlar aktif olur, overlay ve timer kapanır."""
        self._locked = False
        self.pin_btn.setEnabled(True)
        self.change_pass_btn.setEnabled(True)
        self._set_logout_btn_unlocked_style()
        if hasattr(self, '_lock_overlay_timer') and self._lock_overlay_timer is not None:
            try:
                self._lock_overlay_timer.stop()
            except Exception:
                pass
        if hasattr(self, '_lock_overlay') and self._lock_overlay is not None:
            self._lock_overlay.hide()

    def _set_logout_btn_locked_style(self):
        """Kilitliyken buton yeşil '🔒 Giriş Yap' olur."""
        self.logout_btn.setText("🔒 Giriş Yap")
        self.logout_btn.setStyleSheet("""
            QPushButton {
                background-color: #DCFCE7;
                color: #166534;
                border: 1px solid #86EFAC;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #BBF7D0; }
        """)

    def _set_logout_btn_unlocked_style(self):
        """Aktif oturumda buton kırmızı '🔓 Çıkış Yap'."""
        # update_ui_language etiketi tekrar çevirebilir; burada default TR.
        try:
            from utils.translations import Translations
            txt = Translations.t('logout_button', getattr(self, 'current_lang', 'tr'))
        except Exception:
            txt = "🔓 Çıkış Yap"
        self.logout_btn.setText(txt)
        self.logout_btn.setStyleSheet("""
            QPushButton {
                background-color: #FEE2E2;
                color: #B91C1C;
                border: 1px solid #FCA5A5;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #FECACA; }
        """)

    def resizeEvent(self, event):
        """Kilit overlay görünürse aktif sekme boyutuna eşitle."""
        try:
            if getattr(self, '_lock_overlay', None) is not None \
                    and self._lock_overlay.isVisible():
                cur = self.outer_tabs.currentWidget()
                if cur is not None:
                    self._lock_overlay.setGeometry(cur.rect())
        except Exception:
            pass
        super().resizeEvent(event)

    def closeEvent(self, event):
        """Handle window close event"""
        # Task bar'ı her durumda geri getir (operatör modu auto-hide yapmış olabilir).
        try:
            self._set_taskbar_autohide(False)
        except Exception:
            pass
        if self.logout_requested:
            # Logout — just hide, don't disconnect COM
            event.accept()
            return
        
        # Real close (X button) — disconnect and exit
        if self.esp32.is_connected:
            self.esp32.disconnect()

        # Bariyer dinleyicisini kapat (QThread güvenli).
        try:
            if getattr(self, 'barrier_listener', None) is not None:
                self.barrier_listener.stop()
                self.barrier_listener.wait(2000)
        except Exception:
            pass

        # Shut down Oraps background workers (LAF serial polling thread)
        if hasattr(self, 'oraps_panel') and hasattr(self.oraps_panel, 'shutdown'):
            try:
                self.oraps_panel.shutdown()
            except Exception:
                pass

        self.audit.log_action('SYSTEM_SHUTDOWN', description='Application closed')
        event.accept()

    def calculate_local_config_crc(self):
        """Calculate CRC32 of local settings to match Firmware"""
        try:
            # Recipe (p1-p8)
            p1 = int(self.db.get_setting('p1', 10))
            p2 = int(self.db.get_setting('p2', 3000))
            p3 = int(self.db.get_setting('p3', 5))
            p4 = int(self.db.get_setting('p4', 2800))
            p5 = int(self.db.get_setting('p5', 3))
            p6 = int(self.db.get_setting('p6', 2000))
            p7 = int(self.db.get_setting('p7', 10))
            p8 = int(self.db.get_setting('p8', 200))
            
            # Calibration (c1-c4)
            c1 = float(self.db.get_setting('c1', 0.0))
            c2 = float(self.db.get_setting('c2', 100.0))
            c3 = float(self.db.get_setting('c3', 0.0))
            c4 = float(self.db.get_setting('c4', 100.0))
            
            # Pack: 8 ints, 4 floats (Little Endian)
            data = struct.pack('<8i4f', p1, p2, p3, p4, p5, p6, p7, p8, c1, c2, c3, c4)
            return zlib.crc32(data)
        except Exception as e:
            _logger.error("CRC Calc Error: %s", e)
            return 0

    def handle_crc_report(self, data):
        """Handle CRC report from device and trigger sync if needed"""
        print(f"DEBUG: handle_crc_report ENTERED with data: {data}")
        device_name = data.get('name')
        if not device_name: 
            print("ERROR: Device name missing in CRC report")
            return
        
        remote_cfg_crc = int(data.get('crc_cfg', 0))
        remote_rfid_crc = int(data.get('crc_rfid', 0))
        
        # Log to GUI (Blue for Info)
        # self.esp_now_control.log(f"[{device_name}] CRC Raporu: CFG={remote_cfg_crc}, RFID={remote_rfid_crc}", color="blue")
        
        # 1. Config Sync Check
        local_cfg_crc = self.calculate_local_config_crc()
        if remote_cfg_crc != local_cfg_crc:
            self.esp_now_control.log(f"[{device_name}] Ayar Uyuşmazlığı (Yerel: {local_cfg_crc}). Ayarlar gönderiliyor...", color="orange")
            
            # Get Params
            params = {
                'p1': int(self.db.get_setting('p1', 10)),
                'p2': int(self.db.get_setting('p2', 3000)),
                'p3': int(self.db.get_setting('p3', 5)),
                'p4': int(self.db.get_setting('p4', 2800)),
                'p5': int(self.db.get_setting('p5', 3)),
                'p6': int(self.db.get_setting('p6', 2000)),
                'p7': int(self.db.get_setting('p7', 10)),
                'p8': int(self.db.get_setting('p8', 200)),
                'c1': float(self.db.get_setting('c1', 0.0)),
                'c2': float(self.db.get_setting('c2', 100.0)),
                'c3': float(self.db.get_setting('c3', 0.0)),
                'c4': float(self.db.get_setting('c4', 100.0))
            }
            # Use name as target
            self.esp32.push_device_config(device_name, params)
        else:
            self.esp_now_control.log(f"[{device_name}] Ayarlar Güncel.", color="green")
            pass

        # 2. RFID Sync Check
        # Compare with last seen CRC for this device
        last_rfid_crc = int(self.db.get_setting(f"crc_rfid_{device_name}", "0"))
        
        if remote_rfid_crc != last_rfid_crc:
            self.esp_now_control.log(f"[{device_name}] RFID Değişikliği (Eski CRC: {last_rfid_crc}). Güncelleniyor...", color="orange")
            self.esp32.request_full_rfid_sync(device_name)
            
            # Update local known CRC (assume sync will succeed, or update on success)
            # For simplicity, update now so we don't loop forever if sync fails silently
            # But correct way is to update only if 'SYNC_COMPLETE' received.
            # However, we rely on reconnection for retry.
            self.db.set_setting(f"crc_rfid_{device_name}", str(remote_rfid_crc))
        else:
            self.esp_now_control.log(f"[{device_name}] RFID Listesi Güncel.", color="green")
