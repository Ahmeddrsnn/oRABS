"""
Settings Panel - Modern Visual Design
System configuration and information with enhanced UI
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QLabel, QPushButton, QScrollArea, QFormLayout,
                             QSpinBox, QFileDialog, QMessageBox, QComboBox,
                             QFrame, QLineEdit, QRadioButton, QButtonGroup,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QDialog, QDialogButtonBox, QCheckBox, QApplication)
from PyQt5.QtGui import QFont, QIcon, QPixmap, QColor
from PyQt5.QtCore import Qt, pyqtSignal
import os
import shutil
from utils.translations import Translations
from utils.storage_config import get_storage_base_path, set_storage_base_path


class _NoWheelSpinBox(QSpinBox):
    """SpinBox subclass — wheel event sayfa scroll'a aktarılır, değer değişmez."""
    def wheelEvent(self, event):
        event.ignore()


class _NoWheelComboBox(QComboBox):
    """ComboBox subclass — wheel event sayfa scroll'a aktarılır, seçim değişmez."""
    def wheelEvent(self, event):
        event.ignore()


class SettingsPanel(QWidget):
    """
    Panel for system-wide settings and information.
    Enhanced with modern visual design, icons, and better organization.
    """
    
    language_changed = pyqtSignal(str) # Emits new language code
    oraps_settings_changed = pyqtSignal()  # Emits after Oraps settings save
    laf_settings_changed = pyqtSignal()    # Emits after LAF settings/sensors save
    weidmuller_settings_changed = pyqtSignal()  # Emits after Weidmüller modules/points edit
    tab_visibility_changed = pyqtSignal()  # Faz-9: sekme görünürlüğü save sonrası
    
    def __init__(self, auth_manager, database, parent=None,
                 visible_groups=None, custom_header=None, custom_subtitle=None,
                 audit_manager=None):
        super().__init__(parent)
        self.auth = auth_manager
        self.db = database
        self._audit_manager = audit_manager
        self.current_lang = self.db.get_language()
        # Faz-3 split: optional set/list of group keys to keep visible.
        # None = legacy behaviour (show everything). Recognised keys:
        #   'general', 'storage', 'security', 'branding', 'compliance', 'sysinfo'
        self._visible_groups = (
            set(visible_groups) if visible_groups is not None else None
        )
        self._custom_header = custom_header
        self._custom_subtitle = custom_subtitle
        
        self.init_ui()
        self.apply_styles()
        self.load_settings()
        
    def init_ui(self):
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(25, 25, 25, 25)
        self.main_layout.setSpacing(0)
        
        # Main header with icon
        header_container = QHBoxLayout()
        header_container.setSpacing(15)
        
        # Icon
        icon_label = QLabel()
        icon_pixmap = QPixmap("assets/icons/settings.svg")
        if not icon_pixmap.isNull():
            icon_label.setPixmap(icon_pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon_label.setFixedSize(32, 32)
        
        self.header = QLabel()
        self.header.setStyleSheet("font-size: 28px; font-weight: 600; color: #1F2937;")
        
        header_container.addWidget(icon_label)
        header_container.addWidget(self.header)
        header_container.addStretch()
        
        self.main_layout.addLayout(header_container)
        
        # Subtitle
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet("font-size: 14px; color: #6B7280; margin-top: 5px; margin-bottom: 20px;")
        self.main_layout.addWidget(self.subtitle)
        
        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("background-color: #E5E7EB; margin-top: 10px; margin-bottom: 20px;")
        divider.setFixedHeight(1)
        self.main_layout.addWidget(divider)
        
        # Content Scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background-color: transparent;")
        
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(20)
        self.content_layout.setContentsMargins(0, 0, 10, 0)
        
        # 1. General Settings (Language) - Modern card design
        self.gen_group = self._create_setting_card("🌐", "")
        gen_layout = QFormLayout()
        gen_layout.setSpacing(12)
        gen_layout.setContentsMargins(20, 15, 20, 20)
        
        self.lang_label = QLabel()
        self.lang_label.setStyleSheet("font-weight: 500; color: #374151;")
        
        self.lang_combo = _NoWheelComboBox()
        self.lang_combo.addItem("🇹🇷 Türkçe", "tr")
        self.lang_combo.addItem("🇬🇧 English", "en")
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        
        gen_layout.addRow(self.lang_label, self.lang_combo)
        self.gen_group.setLayout(gen_layout)
        self.content_layout.addWidget(self.gen_group)
        
        # 1b. Storage Settings (Admin Only) - Folder picker card
        self.storage_group = self._create_setting_card("📁", "")
        storage_layout = QVBoxLayout()
        storage_layout.setSpacing(10)
        storage_layout.setContentsMargins(20, 15, 20, 20)
        
        self.storage_label = QLabel()
        self.storage_label.setStyleSheet("font-weight: 500; color: #374151;")
        storage_layout.addWidget(self.storage_label)
        
        # Path row: readonly line edit + browse button
        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        
        from PyQt5.QtWidgets import QLineEdit
        self.storage_path_edit = QLineEdit()
        self.storage_path_edit.setReadOnly(True)
        self.storage_path_edit.setPlaceholderText("...")
        self.storage_path_edit.setMaximumWidth(600)
        self.storage_path_edit.setCursor(Qt.PointingHandCursor)
        self.storage_path_edit.mousePressEvent = lambda e: self._on_browse_storage()
        self.storage_path_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D1D5DB; border-radius: 8px;
                padding: 8px 12px; background: #F9FAFB;
                color: #1F2937; font-size: 13px;
            }
            QLineEdit:hover {
                border-color: #3B82F6;
            }
        """)
        
        self.storage_browse_btn = QPushButton("📂")
        self.storage_browse_btn.setObjectName("storageBrowseBtn")
        self.storage_browse_btn.setFixedSize(44, 38)
        self.storage_browse_btn.setCursor(Qt.PointingHandCursor)
        self.storage_browse_btn.clicked.connect(self._on_browse_storage)
        
        path_row.addWidget(self.storage_path_edit)
        path_row.addWidget(self.storage_browse_btn)
        path_row.addStretch()
        storage_layout.addLayout(path_row)
        
        self.storage_hint_label = QLabel()
        self.storage_hint_label.setWordWrap(True)
        self.storage_hint_label.setStyleSheet("color: #6B7280; font-size: 11px; margin-top: 2px;")
        storage_layout.addWidget(self.storage_hint_label)
        
        self.storage_group.setLayout(storage_layout)
        self.content_layout.addWidget(self.storage_group)
        
        if self.auth.get_current_user_role() != 'Admin':
            self.storage_group.hide()

        # 2. System Settings (Admin Only - Security) - Enhanced card
        self.sys_group = self._create_setting_card("🔒", "")
        sys_inner = QVBoxLayout()
        sys_inner.setSpacing(12)
        sys_inner.setContentsMargins(20, 15, 20, 20)
        
        self.logout_label = QLabel()
        self.logout_label.setStyleSheet("font-weight: 500; color: #374151;")
        sys_inner.addWidget(self.logout_label)
        
        timeout_row = QHBoxLayout()
        timeout_row.setSpacing(10)
        
        self.logout_spin = _NoWheelSpinBox()
        self.logout_spin.setRange(1, 120)
        
        self.timeout_save_btn = QPushButton("💾 Kaydet")
        self.timeout_save_btn.setObjectName("timeoutSaveBtn")
        self.timeout_save_btn.setFixedSize(120, 38)
        self.timeout_save_btn.setCursor(Qt.PointingHandCursor)
        self.timeout_save_btn.clicked.connect(self._on_save_timeout)
        
        timeout_row.addWidget(self.logout_spin)
        timeout_row.addWidget(self.timeout_save_btn)
        timeout_row.addStretch()
        sys_inner.addLayout(timeout_row)

        # ── Periyodik şifre değiştirme sıklığı ──────────────────
        # Tüm kullanıcılar için geçerli. Şifresini `password_changed_at`
        # tarihinden bu ay sayısı kadar süre önce değiştirmiş kullanıcı
        # login olduğunda ForcePasswordChangeDialog gösterilir.
        self.pwd_interval_label = QLabel(
            "Periyodik şifre değiştirme sıklığı"
        )
        self.pwd_interval_label.setStyleSheet(
            "font-weight: 500; color: #374151;"
        )
        sys_inner.addWidget(self.pwd_interval_label)

        pwd_row = QHBoxLayout()
        pwd_row.setSpacing(10)
        self.pwd_interval_combo = _NoWheelComboBox()
        # (label, months) — DB'de string olarak saklanır ("3","6","9","12").
        for label, months in (
            ("3 ay",  "3"),
            ("6 ay",  "6"),
            ("9 ay",  "9"),
            ("12 ay", "12"),
        ):
            self.pwd_interval_combo.addItem(label, months)
        self.pwd_interval_combo.setFixedWidth(160)
        self.pwd_interval_combo.currentIndexChanged.connect(
            self._on_pwd_interval_changed
        )
        pwd_row.addWidget(self.pwd_interval_combo)
        pwd_row.addStretch()
        sys_inner.addLayout(pwd_row)

        # ── Rapor Ayarları butonu ────────────────────────────────
        self.btn_report_settings = QPushButton("📋 Rapor Ayarları")
        self.btn_report_settings.setCursor(Qt.PointingHandCursor)
        self.btn_report_settings.setStyleSheet(
            "QPushButton { padding:10px 20px; border:1px solid #d1d5db;"
            " background:#ffffff; border-radius:7px; font-weight:700;"
            " font-size:14px; color:#1f2937; }"
            " QPushButton:hover { background:#f3f4f6; }"
        )
        self.btn_report_settings.clicked.connect(self._on_report_settings)
        sys_inner.addWidget(self.btn_report_settings)

        self.sys_group.setLayout(sys_inner)
        self.content_layout.addWidget(self.sys_group)
        
        if self.auth.get_current_user_role() != 'Admin':
            self.sys_group.hide()

        # 3. Branding (Corporate Identity) - Premium design
        self.brand_group = self._create_setting_card("🎨", "")
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(15)
        brand_layout.setContentsMargins(20, 15, 20, 20)
        
        self.logo_label = QLabel()
        self.logo_label.setStyleSheet("font-weight: 500; color: #374151; font-size: 13px;")
        brand_layout.addWidget(self.logo_label)
        
        # Logo preview with modern layout
        logo_container = QHBoxLayout()
        logo_container.setSpacing(15)
        
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(180, 100)
        self.logo_preview.setScaledContents(True)
        self.logo_preview.setAlignment(Qt.AlignCenter)
        self.logo_preview.setStyleSheet("""
            border: 2px dashed #D1D5DB; 
            background: #F9FAFB; 
            border-radius: 8px;
        """)
        
        upload_container = QVBoxLayout()
        upload_container.setSpacing(8)
        
        self.upload_btn = QPushButton("📤 Logo Değiştir")
        self.upload_btn.setObjectName("uploadLogoBtn")
        self.upload_btn.setFixedSize(180, 40)
        self.upload_btn.clicked.connect(self.upload_logo)
        self.upload_btn.setCursor(Qt.PointingHandCursor)
        
        upload_hint = QLabel()
        upload_hint.setText("PNG, JPG • Max 5MB")
        upload_hint.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        
        upload_container.addWidget(self.upload_btn)
        upload_container.addWidget(upload_hint)
        upload_container.addStretch()
        
        logo_container.addWidget(self.logo_preview)
        logo_container.addLayout(upload_container)
        logo_container.addStretch()
        
        brand_layout.addLayout(logo_container)
        self.brand_group.setLayout(brand_layout)
        self.content_layout.addWidget(self.brand_group)
        
        if self.auth.get_current_user_role() != 'Admin':
            self.upload_btn.hide()

        # 4. Compliance Info - Information card
        self.comp_group = self._create_setting_card("✓", "")
        comp_layout = QVBoxLayout()
        comp_layout.setContentsMargins(20, 15, 20, 20)
        
        self.comp_text = QLabel()
        self.comp_text.setTextFormat(Qt.RichText)
        self.comp_text.setWordWrap(True)
        self.comp_text.setStyleSheet("""
            color: #4B5563; 
            line-height: 1.6; 
            font-size: 13px;
            background-color: #F0F9FF;
            padding: 15px;
            border-radius: 6px;
            border-left: 3px solid #3B82F6;
        """)
        comp_layout.addWidget(self.comp_text)
        self.comp_group.setLayout(comp_layout)
        self.content_layout.addWidget(self.comp_group)
        
        # 5. System Info - Stats card with gradient
        self.info_group = self._create_setting_card("ℹ️", "")
        info_layout = QVBoxLayout()
        info_layout.setSpacing(12)
        info_layout.setContentsMargins(20, 15, 20, 20)
        
        # Info items
        self.app_label = QLabel()
        self.app_val = QLabel("Glove Test Control System")
        self.app_val.setStyleSheet("font-weight: 600; color: #1F2937; font-size: 14px;")
        
        self.ver_label = QLabel()
        self.ver_val = QLabel("1.0.0")
        self.ver_val.setStyleSheet("font-family: 'Courier New'; color: #059669; font-weight: 600;")
        
        self.std_label = QLabel()
        self.std_val = QLabel("21 CFR Part 11 Compliant")
        self.std_val.setStyleSheet("color: #3B82F6; font-weight: 600;")
        
        # Create info rows
        info_layout.addWidget(self._create_info_row(self.app_label, self.app_val))
        info_layout.addWidget(self._create_info_row(self.ver_label, self.ver_val))
        info_layout.addWidget(self._create_info_row(self.std_label, self.std_val))
        
        self.info_group.setLayout(info_layout)
        self.content_layout.addWidget(self.info_group)

        # 6. Oraps Settings (Faz-4) - Admin-only configuration card
        self._build_oraps_group()
        self.content_layout.addWidget(self.oraps_group)

        # 7. Sekme Görünürlüğü (Faz-9) — Admin ana sekmeleri gizleyip
        # gösterebilir. Ayarlar sekmeleri her zaman görünür kalır.
        self._build_tab_visibility_group()
        self.content_layout.addWidget(self.tab_visibility_group)

        # Bottom padding
        self.content_layout.addStretch()
        
        scroll.setWidget(content)
        self.main_layout.addWidget(scroll)
        self.setLayout(self.main_layout)
        
        # Apply visible-groups filter (Faz-3 split). When a set is supplied
        # only the listed group keys remain visible; admin-gated groups
        # additionally check role inside refresh_admin_visibility().
        if self._visible_groups is not None:
            group_keys = {
                'general':    self.gen_group,
                'storage':    self.storage_group,
                'security':   self.sys_group,
                'branding':   self.brand_group,
                'compliance': self.comp_group,
                'sysinfo':    self.info_group,
                'oraps':      self.oraps_group,
            }
            for key, widget in group_keys.items():
                if key not in self._visible_groups:
                    widget.hide()
        
        self.translate_ui()
    
    def _create_setting_card(self, icon_emoji, title):
        """Create a modern card-style group box with icon"""
        card = QGroupBox()
        card.setObjectName("settingCard")
        return card
    
    def _create_info_row(self, label_widget, value_widget):
        """Create an info row with label and value"""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 8, 0, 8)
        row_layout.setSpacing(10)
        
        label_widget.setStyleSheet("color: #6B7280; font-size: 13px;")
        
        row_layout.addWidget(label_widget)
        row_layout.addStretch()
        row_layout.addWidget(value_widget)
        
        return row

    def translate_ui(self):
        """Update all labels based on current language"""
        L = self.current_lang
        if self._custom_header is not None:
            self.header.setText(self._custom_header.get(L, self._custom_header.get('tr', '')))
        else:
            self.header.setText(Translations.t('settings_header', L))
        
        if self._custom_subtitle is not None:
            self.subtitle.setText(self._custom_subtitle.get(L, self._custom_subtitle.get('tr', '')))
        elif L == 'tr':
            self.subtitle.setText("Sistem ayarlarını ve bilgilerini yönetin")
        else:
            self.subtitle.setText("Manage system settings and information")
        
        self.gen_group.setTitle(Translations.t('group_general', L))
        self.storage_group.setTitle(Translations.t('group_storage', L))
        self.sys_group.setTitle(Translations.t('group_security', L))
        self.brand_group.setTitle(Translations.t('group_branding', L))
        self.info_group.setTitle(Translations.t('group_sysinfo', L))
        self.comp_group.setTitle(Translations.t('label_compliance', L))
        if hasattr(self, 'oraps_group'):
            self.oraps_group.setTitle(Translations.t('group_oraps', L))
        
        self.storage_label.setText(Translations.t('label_storage_path', L))
        self.storage_browse_btn.setToolTip(Translations.t('btn_select_folder', L))
        self.storage_hint_label.setText(Translations.t('storage_hint', L))
        
        self.lang_label.setText(Translations.t('label_lang', L))
        self.logout_label.setText(Translations.t('label_timeout', L))
        self.logo_label.setText(Translations.t('label_logo', L))
        self.upload_btn.setText(f"📤 {Translations.t('btn_upload_logo', L)}")
        self.app_label.setText(Translations.t('label_app', L))
        self.ver_label.setText(Translations.t('label_version', L))
        self.std_label.setText(Translations.t('label_standard', L))
        
        self.comp_text.setText(Translations.t('compliance_text', L))
        self.logout_spin.setSuffix(f" {Translations.t('minute', L)}")
        
        # Update combo index without triggering signal
        self.lang_combo.blockSignals(True)
        idx = self.lang_combo.findData(L)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.blockSignals(False)

    def refresh_admin_visibility(self):
        """Show/hide admin-only elements based on current user role.
        Must be called after login since the panel is created before login."""
        is_admin = self.auth.get_current_user_role() == 'Admin'

        def _visible(key, default=True):
            """Respect the Faz-3 visible_groups filter when present."""
            if self._visible_groups is None:
                return default
            return key in self._visible_groups

        # Storage settings — admin only AND must be in visible_groups
        self.storage_group.setVisible(is_admin and _visible('storage'))
        # Security settings — admin only AND must be in visible_groups
        self.sys_group.setVisible(is_admin and _visible('security'))
        # Logo upload button — admin only (brand_group container visibility
        # itself is controlled by the visible_groups filter)
        if _visible('branding'):
            self.upload_btn.setVisible(is_admin)
        # Oraps inputs — visible always when group is shown, but disabled
        # for non-admins (so they can still see current values).
        if _visible('oraps') and hasattr(self, 'oraps_group'):
            self.refresh_oraps_editable()

        # Faz-9: Sekme Görünürlüğü kartı — admin only + visible_groups filter.
        if hasattr(self, 'tab_visibility_group'):
            self.tab_visibility_group.setVisible(
                is_admin and _visible('tab_visibility')
            )

    def on_language_changed(self, index):
        """Handle language switch"""
        new_lang = self.lang_combo.currentData()
        if new_lang != self.current_lang:
            self.current_lang = new_lang
            self.db.set_language(new_lang)
            self.translate_ui()
            self.language_changed.emit(new_lang)

    def load_settings(self):
        """Load values from DB"""
        # Session Timeout
        minutes = self.db.get_setting('auto_logout_minutes', '15')
        self.logout_spin.setValue(int(minutes))

        # Periyodik şifre değiştirme sıklığı (ay). Varsayılan 3 ay.
        try:
            pwd_months = str(
                self.db.get_setting('password_change_interval_months', '3')
            ).strip() or '3'
        except Exception:
            pwd_months = '3'
        if pwd_months not in ('3', '6', '9', '12'):
            pwd_months = '3'
        idx = self.pwd_interval_combo.findData(pwd_months)
        if idx >= 0:
            self.pwd_interval_combo.blockSignals(True)
            self.pwd_interval_combo.setCurrentIndex(idx)
            self.pwd_interval_combo.blockSignals(False)
        
        # Storage path
        current_path = get_storage_base_path()
        if current_path:
            self.storage_path_edit.setText(current_path)
        else:
            # Varsayılan: uygulamanın çalıştığı gerçek dizin
            from utils.storage_config import _get_writable_data_dir
            actual_dir = _get_writable_data_dir()
            if not actual_dir:
                actual_dir = os.path.abspath(os.getcwd())
            self.storage_path_edit.setText(actual_dir)
        
        # Logo
        self.update_logo_preview()

        # Faz-9: Sekme görünürlüğü checkbox'ları
        self._load_tab_visibility()

    def _resolve_logo_path(self, logo_path: str) -> str:
        """Resolve logo path - try absolute, then relative to src/assets"""
        if os.path.isabs(logo_path) and os.path.exists(logo_path):
            return logo_path
        if os.path.exists(logo_path):
            return os.path.abspath(logo_path)
        # Try relative to src directory
        src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        abs_path = os.path.join(src_dir, logo_path)
        if os.path.exists(abs_path):
            return abs_path
        return logo_path

    def update_logo_preview(self):
        """Update the logo preview thumbnail"""
        logo_path = self.db.get_setting('company_logo_path', 'assets/logo.png')
        resolved = self._resolve_logo_path(logo_path)
        if os.path.exists(resolved):
            pixmap = QPixmap(resolved)
            self.logo_preview.setPixmap(pixmap)
            self.logo_preview.setStyleSheet("""
                border: 2px dashed #D1D5DB; 
                background: #F9FAFB; 
                border-radius: 8px;
            """)
        else:
            self.logo_preview.setText("📷\nNo Logo")
            self.logo_preview.setStyleSheet("""
                border: 2px dashed #D1D5DB; 
                background: #F9FAFB; 
                border-radius: 8px;
                color: #9CA3AF;
                font-size: 12px;
            """)

    def save_logout_time(self, value):
        self.db.set_setting('auto_logout_minutes', str(value))

    def _on_save_timeout(self):
        """Kaydet butonuna basılınca zaman aşımı değerini DB'ye yaz"""
        value = self.logout_spin.value()
        self.db.set_setting('auto_logout_minutes', str(value))
        QMessageBox.information(self, "Kaydedildi", f"Oturum zaman aşımı {value} dakika olarak kaydedildi.")

    def _on_pwd_interval_changed(self, _index):
        """Periyodik şifre değiştirme sıklığı combobox → DB'ye anında yaz."""
        months = self.pwd_interval_combo.currentData()
        if months not in ('3', '6', '9', '12'):
            return
        try:
            self.db.set_setting('password_change_interval_months', str(months))
        except Exception as e:
            QMessageBox.warning(
                self, "Kaydedilemedi",
                f"Şifre değiştirme sıklığı kaydedilemedi:\n{e}"
            )

    def _on_report_settings(self):
        """Rapor Ayarları diyaloğu — 3 rapor türü için başlık + logo."""
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
                                     QLineEdit, QDialogButtonBox, QTabWidget,
                                     QWidget, QHBoxLayout, QFileDialog)
        from PyQt5.QtGui import QPixmap

        # Mevcut ayarları DB'den oku
        _keys = {
            'report_company_name': 'Bilim İlaç Sanayi ve Ticaret A.Ş.',
            'report_glt_title': 'Eldiven Sızdırmazlık Test Sonuç Raporu',
            'report_batch_title': 'Batch Özet Raporu',
            'report_summary_title': 'Batch Alarm ve Sonuç Özet Raporu',
            'report_audit_title': 'Audit Trail Raporu',
            'report_logo_path': self.db.get_setting('company_logo_path', 'assets/logo.png'),
        }
        current = {}
        for k, default in _keys.items():
            try:
                v = self.db.get_setting(k, default)
                current[k] = v if v else default
            except Exception:
                current[k] = default

        dlg = QDialog(self)
        dlg.setWindowTitle("📋 Rapor Ayarları")
        dlg.setMinimumWidth(550)
        root = QVBoxLayout(dlg)
        root.setSpacing(14)
        root.setContentsMargins(20, 20, 20, 16)

        info = QLabel(
            "PDF raporlarında görünecek şirket adı, rapor başlıkları ve logoyu "
            "buradan ayarlayabilirsiniz."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#6b7280; font-size:12px;")
        root.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)

        # Şirket adı
        company_edit = QLineEdit(current['report_company_name'])
        company_edit.setPlaceholderText("Rapor üst başlığında görünen şirket adı")
        form.addRow("Şirket Adı:", company_edit)

        # Rapor başlıkları
        glt_title_edit = QLineEdit(current['report_glt_title'])
        glt_title_edit.setPlaceholderText("GLT test raporu başlığı")
        form.addRow("GLT Rapor Başlığı:", glt_title_edit)

        batch_title_edit = QLineEdit(current['report_batch_title'])
        batch_title_edit.setPlaceholderText("Batch özet raporu başlığı")
        form.addRow("Batch Rapor Başlığı:", batch_title_edit)

        summary_title_edit = QLineEdit(current['report_summary_title'])
        summary_title_edit.setPlaceholderText(
            "Kompakt özet rapor başlığı (yalnız alarm + port sonuçları)")
        form.addRow("Özet Rapor Başlığı:", summary_title_edit)

        audit_title_edit = QLineEdit(current['report_audit_title'])
        audit_title_edit.setPlaceholderText("Audit trail raporu başlığı")
        form.addRow("Audit Rapor Başlığı:", audit_title_edit)

        root.addLayout(form)

        # ── Rapor içeriği (Faz-13b): bölümleri ekle/çıkar ──────────
        from PyQt5.QtWidgets import QCheckBox as _QCheckBox
        content_lbl = QLabel("<b>Batch raporu içeriği</b>")
        content_lbl.setStyleSheet("color:#374151; font-size:12px; margin-top:4px;")
        root.addWidget(content_lbl)
        laf_chk = _QCheckBox("LAF alarm tablosunu rapora dahil et")
        laf_chk.setCursor(Qt.PointingHandCursor)
        laf_chk.setChecked(
            str(self.db.get_setting('report_include_laf', '1')).strip() != '0')
        root.addWidget(laf_chk)
        pm_chk = _QCheckBox("Port hareket sensörü kayıtlarını rapora dahil et")
        pm_chk.setCursor(Qt.PointingHandCursor)
        pm_chk.setChecked(
            str(self.db.get_setting('report_include_port_motion', '1')).strip() != '0')
        root.addWidget(pm_chk)
        auto_sum_chk = _QCheckBox(
            "Batch bitince özet raporu (alarm + port sonuçları) otomatik oluştur")
        auto_sum_chk.setCursor(Qt.PointingHandCursor)
        auto_sum_chk.setChecked(
            str(self.db.get_setting('report_auto_summary', '1')).strip() != '0')
        root.addWidget(auto_sum_chk)
        content_hint = QLabel(
            "İşareti kaldırılan bölüm bir sonraki batch özet raporunda yer almaz "
            "(LAF: alarm tablosu; port hareketi: hareket tablosundaki port "
            "satırları + denetim izindeki port hareket kayıtları)."
        )
        content_hint.setWordWrap(True)
        content_hint.setStyleSheet("color:#6b7280; font-size:11px;")
        root.addWidget(content_hint)

        # Logo seçimi
        logo_frame = QHBoxLayout()
        logo_frame.setSpacing(12)
        logo_preview = QLabel()
        logo_preview.setFixedSize(160, 80)
        logo_preview.setScaledContents(True)
        logo_preview.setStyleSheet(
            "border:2px dashed #d1d5db; background:#f9fafb; border-radius:6px;"
        )
        _logo_path = [current['report_logo_path']]
        try:
            resolved = self._resolve_logo_path(_logo_path[0])
            if os.path.exists(resolved):
                logo_preview.setPixmap(QPixmap(resolved))
        except Exception:
            pass
        logo_frame.addWidget(logo_preview)

        def _on_browse_logo():
            path, _ = QFileDialog.getOpenFileName(
                dlg, "Logo Seç", "",
                "Resim (*.png *.jpg *.jpeg *.bmp);;Tüm dosyalar (*)"
            )
            if path:
                _logo_path[0] = path
                logo_preview.setPixmap(QPixmap(path))

        btn_logo = QPushButton("📂 Logo Değiştir")
        btn_logo.setCursor(Qt.PointingHandCursor)
        btn_logo.setStyleSheet(
            "padding:8px 14px; border:1px solid #d1d5db;"
            " border-radius:6px; background:#ffffff; font-size:12px;"
        )
        btn_logo.clicked.connect(_on_browse_logo)
        logo_frame.addWidget(btn_logo)
        logo_frame.addStretch()
        root.addLayout(logo_frame)

        # Butonlar
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("💾 Kaydet")
        buttons.button(QDialogButtonBox.Cancel).setText("İptal")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        root.addWidget(buttons)

        if dlg.exec_() != QDialog.Accepted:
            return

        # Kaydet
        new_vals = {
            'report_company_name': company_edit.text().strip(),
            'report_glt_title': glt_title_edit.text().strip(),
            'report_batch_title': batch_title_edit.text().strip(),
            'report_summary_title': summary_title_edit.text().strip(),
            'report_audit_title': audit_title_edit.text().strip(),
            'report_include_laf': '1' if laf_chk.isChecked() else '0',
            'report_include_port_motion': '1' if pm_chk.isChecked() else '0',
            'report_auto_summary': '1' if auto_sum_chk.isChecked() else '0',
        }
        # Logo dosyasını assets'e kopyala (farklı seçildiyse)
        new_logo = _logo_path[0]
        if new_logo and new_logo != current['report_logo_path']:
            try:
                import shutil
                src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                dest = os.path.join(src_dir, 'assets', 'report_logo' + os.path.splitext(new_logo)[1])
                shutil.copy2(new_logo, dest)
                new_vals['report_logo_path'] = dest
            except Exception as e:
                QMessageBox.warning(dlg, "Logo", f"Logo kopyalanamadı:\n{e}")
                new_vals['report_logo_path'] = new_logo
        for k, v in new_vals.items():
            if v:
                try:
                    self.db.set_setting(k, v)
                except Exception:
                    pass
        QMessageBox.information(self, "Kaydedildi",
                                "Rapor ayarları başarıyla kaydedildi.\n"
                                "Yeni ayarlar bir sonraki PDF üretiminde geçerli olacak.")

    def _on_browse_storage(self):
        """Open folder picker for storage base path."""
        L = self.current_lang
        current = get_storage_base_path()
        start_dir = current if current and os.path.isdir(current) else ""
        
        folder = QFileDialog.getExistingDirectory(
            self,
            Translations.t('btn_select_folder', L),
            start_dir
        )
        if not folder:
            return
        
        # Save to config file
        set_storage_base_path(folder)
        self.storage_path_edit.setText(folder)
        
        # Create sub-folders immediately so user sees the structure
        for sub in ("database", "reports", "batches"):
            os.makedirs(os.path.join(folder, sub), exist_ok=True)
        
        QMessageBox.information(
            self,
            Translations.t('storage_restart_title', L),
            Translations.t('storage_updated', L)
        )

    def upload_logo(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Logo Seç", "", "Images (*.png *.jpg *.jpeg)")
        if file_path:
            try:
                # 5MB boyut kontrolü
                file_size = os.path.getsize(file_path)
                if file_size > 5 * 1024 * 1024:
                    QMessageBox.warning(self, "Uyarı", "Dosya boyutu 5MB'den büyük olamaz.")
                    return

                # Yazılabilir dizine kaydet (frozen: %LOCALAPPDATA%, dev: src/assets)
                from utils.storage_config import _get_writable_data_dir
                _data = _get_writable_data_dir()
                if _data:
                    dest_dir = os.path.join(_data, "assets")
                else:
                    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    dest_dir = os.path.join(src_dir, "assets")
                os.makedirs(dest_dir, exist_ok=True)
                ext = os.path.splitext(file_path)[1].lower()
                dest_path = os.path.join(dest_dir, f"logo{ext}")
                shutil.copy(file_path, dest_path)
                self.db.set_setting('company_logo_path', dest_path)
                self.update_logo_preview()
                QMessageBox.information(self, Translations.t('success', self.current_lang), 
                                        Translations.t('logo_updated', self.current_lang))
            except Exception as e:
                QMessageBox.critical(self, Translations.t('error', self.current_lang), str(e))

    # ── Oraps settings group (Faz-4) ─────────────────────────────
    def _build_oraps_group(self):
        """Build the Oraps settings card. Admin-only inputs + door labels editor."""
        self.oraps_group = self._create_setting_card("🔧", "")
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(20, 15, 20, 20)

        # Admin warning banner (visible only to non-admins)
        self.oraps_warning = QLabel(
            "⚠ Bu ayarları yalnızca admin değiştirebilir. Görüntüleme modundasınız."
        )
        self.oraps_warning.setStyleSheet(
            "background:#fef3c7;color:#92400e;padding:10px;"
            "border-radius:6px;font-size:12px;border:1px solid #fcd34d;"
        )
        self.oraps_warning.setVisible(False)
        layout.addWidget(self.oraps_warning)

        # ── 3D Model ──
        layout.addWidget(self._oraps_section_label("🖼  3D Model Dosyası (GLB)"))
        glb_row = QHBoxLayout()
        self.oraps_glb_edit = QLineEdit()
        self.oraps_glb_edit.setReadOnly(True)
        self.oraps_glb_edit.setStyleSheet(self._oraps_input_qss())
        self.oraps_glb_btn = QPushButton("📂 Gözat")
        self.oraps_glb_btn.setCursor(Qt.PointingHandCursor)
        self.oraps_glb_btn.clicked.connect(self._on_browse_glb)
        glb_row.addWidget(self.oraps_glb_edit)
        glb_row.addWidget(self.oraps_glb_btn)
        layout.addLayout(glb_row)
        hint = QLabel("Sadece .glb veya .gltf dosyaları desteklenir.")
        hint.setStyleSheet("color:#6b7280;font-size:11px;")
        layout.addWidget(hint)

        # Unit selector
        unit_row = QHBoxLayout()
        unit_row.addWidget(self._oraps_section_label("Model Birimi:"))
        self.oraps_unit_group = QButtonGroup(self)
        self.oraps_unit_buttons = {}
        for code, label in (('mm', 'Milimetre'), ('cm', 'Santimetre'), ('m', 'Metre')):
            rb = QRadioButton(label)
            rb.setCursor(Qt.PointingHandCursor)
            self.oraps_unit_group.addButton(rb)
            self.oraps_unit_buttons[code] = rb
            unit_row.addWidget(rb)
        unit_row.addStretch()
        layout.addLayout(unit_row)

        # ── Overview views (which sides are shown on the Genel Bakış tab) ──
        layout.addWidget(self._oraps_section_label(
            "🧭 Genel Bakış Görünümleri (Oraps ana sekme)"
        ))
        views_row = QHBoxLayout()
        self.oraps_view_checks = {}
        for code, label in (
            ('front', 'Ön'),
            ('back',  'Arka'),
            ('left',  'Sol'),
            ('right', 'Sağ'),
        ):
            cb = QCheckBox(label)
            cb.setCursor(Qt.PointingHandCursor)
            self.oraps_view_checks[code] = cb
            views_row.addWidget(cb)
        views_row.addStretch()
        layout.addLayout(views_row)
        views_hint = QLabel(
            "İşaretli yüzeyler Genel Bakış sekmesinde gösterilir. "
            "2 yüzey seçilirse görseller daha büyük gösterilir."
        )
        views_hint.setStyleSheet("color:#6b7280;font-size:11px;")
        views_hint.setWordWrap(True)
        layout.addWidget(views_hint)

        # Faz-9: Genel Bakış'ta LAF Ünitesi kartını göster/gizle.
        # Kapatılınca orta kolonda Son Olayların altındaki LAF kartı
        # gizlenir (yer kaplamaz). Ayar `overview_show_laf` = '0'/'1'.
        self.oraps_show_laf_chk = QCheckBox(
            "LAF Ünitesi kartını Genel Bakış'ta göster"
        )
        self.oraps_show_laf_chk.setCursor(Qt.PointingHandCursor)
        self.oraps_show_laf_chk.setChecked(True)
        layout.addWidget(self.oraps_show_laf_chk)

        # Faz-12: ORABS aşaması çalışmıyorken machine_stop rölelerine sürekli
        # DUR (DO=1) gönder. Supervisor + Admin değiştirebilir.
        self.oraps_ms_idle_chk = QCheckBox(
            "🛑 ORABS batch'i dışında makineyi her zaman durdur"
        )
        self.oraps_ms_idle_chk.setCursor(Qt.PointingHandCursor)
        self.oraps_ms_idle_chk.setToolTip(
            "Açıkken: batch yokken, batch bittikten sonra ve GLT aşamasında "
            "machine_stop rolündeki tüm rölelere sürekli DUR (DO=1) yazılır. "
            "Makine yalnızca ORABS aşaması çalışırken başlayabilir."
        )
        self.oraps_ms_idle_chk.setChecked(False)
        layout.addWidget(self.oraps_ms_idle_chk)

        # ── Weidmüller ──
        layout.addWidget(self._oraps_divider())
        layout.addWidget(self._oraps_section_label("🔌 Weidmüller Modbus TCP"))
        form_w = QFormLayout()
        form_w.setSpacing(8)
        form_w.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.oraps_ip_edit = QLineEdit()
        self.oraps_ip_edit.setPlaceholderText("192.168.1.100")
        self.oraps_ip_edit.setStyleSheet(self._oraps_input_qss())
        self.oraps_ip_edit.setMaximumWidth(180)
        self.oraps_port_spin = _NoWheelSpinBox()
        self.oraps_port_spin.setRange(1, 65535)
        self.oraps_port_spin.setValue(502)
        self.oraps_port_spin.setMaximumWidth(120)
        self.oraps_poll_spin = _NoWheelSpinBox()
        self.oraps_poll_spin.setRange(1, 5000)
        self.oraps_poll_spin.setSuffix(" ms")
        self.oraps_poll_spin.setValue(100)
        self.oraps_poll_spin.setMaximumWidth(120)
        form_w.addRow("IP Adresi:", self.oraps_ip_edit)
        form_w.addRow("Port:", self.oraps_port_spin)
        form_w.addRow("Polling:", self.oraps_poll_spin)
        layout.addLayout(form_w)

        # ── Mapping file ──
        layout.addWidget(self._oraps_divider())
        layout.addWidget(self._oraps_section_label("🗺  IO Eşleme Dosyası (Faz-5)"))
        map_row = QHBoxLayout()
        self.oraps_map_edit = QLineEdit()
        self.oraps_map_edit.setStyleSheet(self._oraps_input_qss())
        self.oraps_map_btn = QPushButton("📂 Gözat")
        self.oraps_map_btn.setCursor(Qt.PointingHandCursor)
        self.oraps_map_btn.clicked.connect(self._on_browse_mapping)
        map_row.addWidget(self.oraps_map_edit)
        map_row.addWidget(self.oraps_map_btn)
        layout.addLayout(map_row)

        # ── Port labels + motion sensor editor ──
        layout.addWidget(self._oraps_divider())
        layout.addWidget(self._oraps_section_label("🧤 Eldiven Portları (14 port + hareket sensörü)"))
        self.oraps_ports_btn = QPushButton("✏ Port İsimleri / Hareket Sensörü…")
        self.oraps_ports_btn.setCursor(Qt.PointingHandCursor)
        self.oraps_ports_btn.setStyleSheet(
            "QPushButton { background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe;"
            " border-radius:6px; padding:8px 14px; font-weight:600; }"
            " QPushButton:hover { background:#dbeafe; }"
        )
        self.oraps_ports_btn.clicked.connect(self._on_edit_port_labels)
        layout.addWidget(self.oraps_ports_btn, alignment=Qt.AlignLeft)

        # ── Light barriers (Faz-6c) ──
        layout.addWidget(self._oraps_section_label("💡 Işık Bariyerleri (kapılar arası)"))
        self.oraps_barriers_btn = QPushButton("✏ Işık Bariyerlerini Düzenle…")
        self.oraps_barriers_btn.setCursor(Qt.PointingHandCursor)
        self.oraps_barriers_btn.setStyleSheet(self.oraps_ports_btn.styleSheet())
        self.oraps_barriers_btn.clicked.connect(self._on_edit_barriers)
        layout.addWidget(self.oraps_barriers_btn, alignment=Qt.AlignLeft)

        # ── Kablosuz IR bariyer sensörleri (Faz-7) ──
        layout.addWidget(self._oraps_section_label("📡 Kablosuz Bariyer Sensörleri (port hareket)"))
        self.barrier_sensors_btn = QPushButton("✏ Bariyer Sensörlerini Düzenle…")
        self.barrier_sensors_btn.setCursor(Qt.PointingHandCursor)
        self.barrier_sensors_btn.setStyleSheet(self.oraps_ports_btn.styleSheet())
        self.barrier_sensors_btn.clicked.connect(self._on_edit_barrier_sensors)
        layout.addWidget(self.barrier_sensors_btn, alignment=Qt.AlignLeft)

        # ── LAF (Faz-5) — USB→Modbus RTU clean room monitor ──
        layout.addWidget(self._oraps_divider())
        layout.addWidget(self._oraps_section_label("🌬 LAF (Laminar Air Flow) — USB Modbus RTU"))
        form_l = QFormLayout()
        form_l.setSpacing(8)
        form_l.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.laf_port_edit = QLineEdit()
        self.laf_port_edit.setPlaceholderText("COM5")
        self.laf_port_edit.setStyleSheet(self._oraps_input_qss())
        self.laf_port_edit.setMaximumWidth(180)
        self.laf_baud_combo = _NoWheelComboBox()
        for b in ('9600', '19200', '38400', '57600', '115200'):
            self.laf_baud_combo.addItem(b, b)
        self.laf_baud_combo.setMaximumWidth(120)
        self.laf_slave_spin = _NoWheelSpinBox()
        self.laf_slave_spin.setRange(1, 247)
        self.laf_slave_spin.setMaximumWidth(120)
        self.laf_poll_spin = _NoWheelSpinBox()
        self.laf_poll_spin.setRange(1, 60)
        self.laf_poll_spin.setSuffix(" sn")
        self.laf_poll_spin.setMaximumWidth(120)
        self.laf_snap_spin = _NoWheelSpinBox()
        self.laf_snap_spin.setRange(60, 3600)
        self.laf_snap_spin.setSuffix(" sn")
        self.laf_snap_spin.setSingleStep(60)
        self.laf_snap_spin.setMaximumWidth(120)
        form_l.addRow("COM Portu:", self.laf_port_edit)
        form_l.addRow("Baud:", self.laf_baud_combo)
        form_l.addRow("Slave ID:", self.laf_slave_spin)
        form_l.addRow("Polling:", self.laf_poll_spin)
        form_l.addRow("Snapshot periyodu:", self.laf_snap_spin)
        layout.addLayout(form_l)
        self.laf_sensors_btn = QPushButton("✏ LAF Sensörlerini Düzenle…")
        self.laf_sensors_btn.setCursor(Qt.PointingHandCursor)
        self.laf_sensors_btn.setStyleSheet(self.oraps_ports_btn.styleSheet())
        self.laf_sensors_btn.clicked.connect(self._on_edit_laf_sensors)
        layout.addWidget(self.laf_sensors_btn, alignment=Qt.AlignLeft)

        self.weidmuller_modules_btn = QPushButton("🔌 IO Modüllerini Düzenle…")
        self.weidmuller_modules_btn.setCursor(Qt.PointingHandCursor)
        self.weidmuller_modules_btn.setStyleSheet(self.oraps_ports_btn.styleSheet())
        self.weidmuller_modules_btn.clicked.connect(self._on_edit_weidmuller_modules)
        layout.addWidget(self.weidmuller_modules_btn, alignment=Qt.AlignLeft)

        # ── Action buttons ──
        actions = QHBoxLayout()
        actions.addStretch()
        self.oraps_reset_btn = QPushButton("Sıfırla")
        self.oraps_reset_btn.setCursor(Qt.PointingHandCursor)
        self.oraps_reset_btn.clicked.connect(self._load_oraps_settings)
        self.oraps_save_btn = QPushButton("💾 Kaydet")
        self.oraps_save_btn.setCursor(Qt.PointingHandCursor)
        self.oraps_save_btn.setStyleSheet(
            "QPushButton { background:#2563eb;color:white;border:none;"
            " padding:9px 22px;border-radius:6px;font-weight:600;}"
            " QPushButton:hover { background:#1d4ed8;}"
        )
        self.oraps_save_btn.clicked.connect(self._on_save_oraps)
        actions.addWidget(self.oraps_reset_btn)
        actions.addWidget(self.oraps_save_btn)
        layout.addLayout(actions)

        self.oraps_group.setLayout(layout)
        self._load_oraps_settings()
        self.refresh_oraps_editable()

    @staticmethod
    def _oraps_section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight:600;color:#374151;font-size:13px;")
        return lbl

    @staticmethod
    def _oraps_divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background:#e5e7eb;")
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _oraps_input_qss() -> str:
        return (
            "QLineEdit { border:1px solid #d1d5db; border-radius:6px;"
            " padding:7px 10px; background:#ffffff; font-size:13px; }"
            " QLineEdit:focus { border-color:#3b82f6; }"
            " QLineEdit:disabled { background:#f3f4f6; color:#6b7280; }"
        )

    def _load_oraps_settings(self):
        """Read Oraps settings from DB into the form."""
        if not hasattr(self, 'oraps_group'):
            return
        self.oraps_glb_edit.setText(
            self.db.get_setting('oraps_glb_path', '')
        )
        unit = self.db.get_setting('oraps_glb_unit', 'cm')
        if unit in self.oraps_unit_buttons:
            self.oraps_unit_buttons[unit].setChecked(True)
        else:
            self.oraps_unit_buttons['cm'].setChecked(True)
        # Overview enabled views
        raw_views = self.db.get_setting(
            'oraps_overview_views', 'front,back,left,right'
        ) or ''
        enabled = {v.strip().lower() for v in raw_views.split(',') if v.strip()}
        if not enabled:
            enabled = {'front', 'back', 'left', 'right'}
        for code, cb in self.oraps_view_checks.items():
            cb.setChecked(code in enabled)
        # Faz-9: LAF kartı görünürlüğü
        try:
            _show_laf = str(self.db.get_setting(
                'overview_show_laf', '1'
            )).strip() not in ('0', 'false', 'False')
            if hasattr(self, 'oraps_show_laf_chk'):
                self.oraps_show_laf_chk.setChecked(_show_laf)
        except Exception:
            pass
        try:
            if hasattr(self, 'oraps_ms_idle_chk'):
                self.oraps_ms_idle_chk.setChecked(
                    str(self.db.get_setting(
                        'oraps_machine_stop_idle', '0')).strip() == '1'
                )
        except Exception:
            pass
        self.oraps_ip_edit.setText(self.db.get_setting('oraps_weidmuller_ip', '192.168.1.100'))
        try:
            self.oraps_port_spin.setValue(int(self.db.get_setting('oraps_weidmuller_port', '502')))
        except ValueError:
            self.oraps_port_spin.setValue(502)
        try:
            self.oraps_poll_spin.setValue(int(self.db.get_setting('oraps_polling_ms', '100')))
        except ValueError:
            self.oraps_poll_spin.setValue(100)
        self.oraps_map_edit.setText(self.db.get_setting('oraps_mapping_path', ''))

        # LAF
        self.laf_port_edit.setText(self.db.get_setting('laf_com_port', ''))
        baud = self.db.get_setting('laf_baud', '19200')
        idx = self.laf_baud_combo.findData(baud)
        self.laf_baud_combo.setCurrentIndex(idx if idx >= 0 else 0)
        try:
            self.laf_slave_spin.setValue(int(self.db.get_setting('laf_slave_id', '1')))
        except ValueError:
            self.laf_slave_spin.setValue(1)
        try:
            self.laf_poll_spin.setValue(int(self.db.get_setting('laf_poll_sec', '5')))
        except ValueError:
            self.laf_poll_spin.setValue(5)
        try:
            self.laf_snap_spin.setValue(int(self.db.get_setting('laf_snapshot_sec', '300')))
        except ValueError:
            self.laf_snap_spin.setValue(300)

    def refresh_oraps_editable(self):
        """Toggle Oraps inputs based on role.

        Admin: tüm Oraps/LAF/Weidmüller ayarları editlenebilir.
        Supervisor: yalnız port/kapı/bariyer etiket editörleri açılır;
                    sistem ayarları (IP, GLB, mapping, LAF, Weidmüller
                    modülleri) read-only.
        """
        if not hasattr(self, 'oraps_group'):
            return
        role = self.auth.get_current_user_role()
        is_admin = role == 'Admin'
        can_manage = role in ('Admin', 'Supervisor')
        # Admin-only: sistem yapılandırması (donanım/bağlantı/IO)
        for w in (self.oraps_glb_edit, self.oraps_glb_btn,
                  self.oraps_ip_edit, self.oraps_port_spin,
                  self.oraps_poll_spin, self.oraps_map_edit,
                  self.oraps_map_btn, self.oraps_save_btn,
                  self.oraps_reset_btn,
                  self.laf_port_edit, self.laf_baud_combo, self.laf_slave_spin,
                  self.laf_poll_spin, self.laf_snap_spin,
                  self.laf_sensors_btn,
                  self.weidmuller_modules_btn):
            w.setEnabled(is_admin)
        # Admin + Supervisor: batch şablonu / etiket düzenleyiciler
        self.oraps_ports_btn.setEnabled(can_manage)
        # Faz-12: makine durdurma idle ayarı Supervisor + Admin.
        if hasattr(self, 'oraps_ms_idle_chk'):
            self.oraps_ms_idle_chk.setEnabled(can_manage)
        for rb in self.oraps_unit_buttons.values():
            rb.setEnabled(is_admin)
        for cb in self.oraps_view_checks.values():
            cb.setEnabled(is_admin)
        self.oraps_warning.setVisible(not is_admin)

    def _on_browse_glb(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "3D Model Seç", "",
            "3D Model (*.glb *.gltf);;Tüm Dosyalar (*)"
        )
        if path:
            self.oraps_glb_edit.setText(path)

    def _on_browse_mapping(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Eşleme Dosyası", "",
            "JSON (*.json);;Tüm Dosyalar (*)"
        )
        if path:
            self.oraps_map_edit.setText(path)

    def _on_save_oraps(self):
        if self.auth.get_current_user_role() != 'Admin':
            QMessageBox.warning(self, "Yetki Yok",
                                "Oraps ayarlarını sadece admin değiştirebilir.")
            return

        # Collect new values
        new_unit = next(
            (code for code, rb in self.oraps_unit_buttons.items() if rb.isChecked()),
            'cm',
        )
        # Overview views: keep canonical order so the stored string is stable
        view_order = ('front', 'back', 'left', 'right')
        enabled_views = [c for c in view_order
                         if self.oraps_view_checks[c].isChecked()]
        if not enabled_views:
            # Guard against "all unchecked" — fall back to all four
            enabled_views = list(view_order)
            for c in view_order:
                self.oraps_view_checks[c].setChecked(True)
        new_vals = {
            'oraps_glb_path':        self.oraps_glb_edit.text().strip(),
            'oraps_glb_unit':        new_unit,
            'oraps_overview_views':  ','.join(enabled_views),
            'overview_show_laf':     '1' if (
                hasattr(self, 'oraps_show_laf_chk')
                and self.oraps_show_laf_chk.isChecked()
            ) else '0',
            'oraps_machine_stop_idle': '1' if (
                hasattr(self, 'oraps_ms_idle_chk')
                and self.oraps_ms_idle_chk.isChecked()
            ) else '0',
            'oraps_weidmuller_ip':   self.oraps_ip_edit.text().strip(),
            'oraps_weidmuller_port': str(self.oraps_port_spin.value()),
            'oraps_polling_ms':      str(self.oraps_poll_spin.value()),
            'oraps_mapping_path':    self.oraps_map_edit.text().strip(),
            'laf_com_port':          self.laf_port_edit.text().strip(),
            'laf_baud':              self.laf_baud_combo.currentData() or '19200',
            'laf_slave_id':          str(self.laf_slave_spin.value()),
            'laf_poll_sec':          str(self.laf_poll_spin.value()),
            'laf_snapshot_sec':      str(self.laf_snap_spin.value()),
        }

        # Persist + audit (compare with old values for diff trail)
        changed = []
        laf_changed = False
        for k, v in new_vals.items():
            old = self.db.get_setting(k, '')
            if str(old) != str(v):
                self.db.set_setting(k, v)
                changed.append((k, old, v))
                if k.startswith('laf_'):
                    laf_changed = True

        # Audit (one entry per changed key, ORAPS or LAF category)
        if changed and self._audit_manager is not None:
            for k, old, new in changed:
                cat = 'LAF' if k.startswith('laf_') else 'ORAPS'
                try:
                    self._audit_manager.log_action(
                        action_type='SETTINGS_CHANGED',
                        table_name='system_settings',
                        field_name=k,
                        old_value=str(old),
                        new_value=str(new),
                        description=f"{cat} ayarı değişti: {k}",
                        category=cat,
                    )
                except Exception:
                    pass

        # Weidmüller Modbus TCP: system_settings'te tutulan IP/Port/Poll
        # yalnızca UI etiketi; worker'ların gerçekten bağlandığı adres
        # `weidmuller_modules` tablosundadır. Kullanıcının kafasında bu
        # tek IP kutusu = "cihazın IP'si" olduğu için değişikliği tüm
        # modüllere yansıt ve worker'ları yeniden başlat.
        changed_keys = {k for k, _, _ in changed}
        io_keys = {'oraps_weidmuller_ip',
                   'oraps_weidmuller_port',
                   'oraps_polling_ms'}
        io_changed = bool(changed_keys & io_keys)
        # Faz-12: makine durdurma idle ayarı değiştiyse bridge'in
        # machine_stop rölelerini hemen yeniden hesaplamasını sağla.
        if 'oraps_machine_stop_idle' in changed_keys:
            try:
                _bridge = getattr(
                    getattr(self.window(), 'oraps_panel', None),
                    'io_bridge', None)
                if _bridge is not None:
                    _bridge._update_machine_stop_dos()
            except Exception:
                pass
        if io_changed:
            try:
                from core.weidmuller_manager import WeidmullerManager
                wm = WeidmullerManager(self.db, self.auth,
                                       self._audit_manager)
                modules = wm.list_modules()
                new_host = new_vals['oraps_weidmuller_ip']
                new_port = int(new_vals['oraps_weidmuller_port'])
                new_poll = int(new_vals['oraps_polling_ms'])
                for m in modules:
                    fields = {}
                    if 'oraps_weidmuller_ip' in changed_keys \
                            and str(m.get('host', '')) != new_host:
                        fields['host'] = new_host
                    if 'oraps_weidmuller_port' in changed_keys \
                            and int(m.get('port', 0)) != new_port:
                        fields['port'] = new_port
                    if 'oraps_polling_ms' in changed_keys \
                            and int(m.get('poll_ms', 0)) != new_poll:
                        fields['poll_ms'] = new_poll
                    if fields:
                        wm.update_module(m['id'], **fields)
            except Exception:
                import traceback
                traceback.print_exc()

        self.oraps_settings_changed.emit()
        if io_changed:
            # Worker'ları yeni host/port/poll ile restart (oraps_main
            # `_on_io_settings_changed` bu sinyale bağlı).
            self.weidmuller_settings_changed.emit()
        if laf_changed:
            self.laf_settings_changed.emit()
        QMessageBox.information(self, "Kaydedildi",
                                f"Ayarlar kaydedildi ({len(changed)} değişiklik).")

    # ── Faz-9: Sekme Görünürlüğü kartı ──────────────────────────
    # Toggle edilebilir sekmeler + DB anahtarları. Ayarlar sekmeleri
    # bu listede YOK (her zaman görünür kalır).
    _TAB_VISIBILITY_ITEMS = (
        # (setting_key, display_label, section)
        ('tab_visible_orabs',           'ORABS (ana sekme)',      'Ana Sekmeler'),
        ('tab_visible_glt',             'GLT (ana sekme)',        'Ana Sekmeler'),
        ('tab_visible_user',            'Kullanıcı (ana sekme)',  'Ana Sekmeler'),
        ('tab_visible_audit',           'Audit Trail',            'Ana Sekmeler'),
        ('tab_visible_orabs_overview',  'Genel Bakış',            'ORABS Alt Sekmeleri'),
        ('tab_visible_orabs_batch',     'Batch',                  'ORABS Alt Sekmeleri'),
        ('tab_visible_orabs_laf',       'LAF',                    'ORABS Alt Sekmeleri'),
        ('tab_visible_orabs_io',        'IO',                     'ORABS Alt Sekmeleri'),
    )

    def _build_tab_visibility_group(self):
        """🗂 Sekme Görünürlüğü kartı — admin ana + ORABS alt sekmelerini
        gösterip gizleyebilir. Ayarlar sekmeleri her zaman görünür kalır."""
        self.tab_visibility_group = self._create_setting_card(
            "🗂", "Sekme Görünürlüğü"
        )
        layout = QVBoxLayout()
        layout.setSpacing(8)

        hint = QLabel(
            "İşaretini kaldırdığınız sekmeler uygulamada gizlenir. "
            "Ayarlar sekmeleri her zaman görünür kalır."
        )
        hint.setStyleSheet("color:#6b7280;font-size:11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.tab_visibility_checks: dict = {}
        _current_section = None
        for key, label, section in self._TAB_VISIBILITY_ITEMS:
            if section != _current_section:
                _current_section = section
                sec_lbl = QLabel(section)
                sec_lbl.setStyleSheet(
                    "color:#374151;font-weight:600;font-size:12px;"
                    "margin-top:6px;"
                )
                layout.addWidget(sec_lbl)
            cb = QCheckBox(label)
            cb.setCursor(Qt.PointingHandCursor)
            cb.setChecked(True)
            self.tab_visibility_checks[key] = cb
            layout.addWidget(cb)

        # Kaydet butonu
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.tab_vis_save_btn = QPushButton("💾 Kaydet")
        self.tab_vis_save_btn.setCursor(Qt.PointingHandCursor)
        self.tab_vis_save_btn.setFixedSize(120, 36)
        self.tab_vis_save_btn.setStyleSheet(
            "QPushButton { background:#2563eb; color:white; border:none;"
            " border-radius:6px; font-weight:600; font-size:13px; }"
            " QPushButton:hover { background:#1d4ed8; }"
        )
        self.tab_vis_save_btn.clicked.connect(self._on_save_tab_visibility)
        btn_row.addWidget(self.tab_vis_save_btn)
        layout.addLayout(btn_row)

        self.tab_visibility_group.setLayout(layout)

    def _load_tab_visibility(self):
        """DB'den checkbox durumlarını doldur (varsayılan '1'/işaretli)."""
        if not hasattr(self, 'tab_visibility_checks'):
            return
        for key, cb in self.tab_visibility_checks.items():
            raw = str(self.db.get_setting(key, '1') or '1').strip()
            cb.setChecked(raw not in ('0', 'false', 'False'))

    def _on_save_tab_visibility(self):
        """Checkbox durumlarını DB'ye yaz, sinyal yay → main_window uygular."""
        if self.auth.get_current_user_role() != 'Admin':
            QMessageBox.warning(self, "Yetki Yok",
                                "Sekme görünürlüğünü sadece admin değiştirebilir.")
            return
        changed = 0
        for key, cb in self.tab_visibility_checks.items():
            new = '1' if cb.isChecked() else '0'
            old = str(self.db.get_setting(key, '1') or '1').strip()
            if old != new:
                self.db.set_setting(key, new)
                changed += 1
                if self._audit_manager is not None:
                    try:
                        self._audit_manager.log_action(
                            action_type='TAB_VISIBILITY_CHANGED',
                            table_name='system_settings',
                            field_name=key,
                            old_value=old,
                            new_value=new,
                            description=f"Sekme görünürlüğü: {key} {old} → {new}",
                            category='GENERAL',
                        )
                    except Exception:
                        pass
        self.tab_visibility_changed.emit()
        QMessageBox.information(
            self, "Kaydedildi",
            f"Sekme görünürlüğü güncellendi ({changed} değişiklik)."
        )

    def _on_edit_door_labels(self):
        """Open the door labels editor dialog (admin or supervisor)."""
        if self.auth.get_current_user_role() not in ('Admin', 'Supervisor'):
            QMessageBox.warning(self, "Yetki Yok",
                                "Kapı isimlerini sadece admin veya supervisor düzenleyebilir.")
            return
        try:
            from core.batch_manager import BatchManager
        except ImportError:
            QMessageBox.critical(self, "Hata", "batch_manager modülü yüklenemedi.")
            return
        bm = BatchManager(self.db, self.auth, self._audit_manager)
        dlg = _DoorLabelsDialog(bm, parent=self)
        dlg.exec_()
        # No signal needed — labels are read on-demand by the batch dialog

    def _on_edit_port_labels(self):
        """Open the port labels + motion sensor editor (admin or supervisor)."""
        if self.auth.get_current_user_role() not in ('Admin', 'Supervisor'):
            QMessageBox.warning(self, "Yetki Yok",
                                "Port ayarlarını sadece admin veya supervisor düzenleyebilir.")
            return
        try:
            from core.batch_manager import BatchManager
        except ImportError:
            QMessageBox.critical(self, "Hata", "batch_manager modülü yüklenemedi.")
            return
        bm = BatchManager(self.db, self.auth, self._audit_manager)
        dlg = _PortLabelsDialog(bm, parent=self)
        dlg.exec_()

    def _on_edit_barriers(self):
        """Open the light barriers editor (admin or supervisor)."""
        if self.auth.get_current_user_role() not in ('Admin', 'Supervisor'):
            QMessageBox.warning(self, "Yetki Yok",
                                "Işık bariyerlerini sadece admin veya supervisor düzenleyebilir.")
            return
        try:
            from core.batch_manager import BatchManager
        except ImportError:
            QMessageBox.critical(self, "Hata", "batch_manager modülü yüklenemedi.")
            return
        bm = BatchManager(self.db, self.auth, self._audit_manager)
        dlg = _BarriersDialog(bm, parent=self)
        dlg.exec_()

    def _on_edit_barrier_sensors(self):
        """Kablosuz IR bariyer sensörleri editörü (admin/supervisor)."""
        if self.auth.get_current_user_role() not in ('Admin', 'Supervisor'):
            QMessageBox.warning(self, "Yetki Yok",
                                "Bariyer sensörlerini sadece admin veya supervisor düzenleyebilir.")
            return
        try:
            from core.batch_manager import BatchManager
        except ImportError:
            QMessageBox.critical(self, "Hata", "batch_manager modülü yüklenemedi.")
            return
        bm = BatchManager(self.db, self.auth, self._audit_manager)
        dlg = _BarrierSensorsDialog(self.db, bm, parent=self)
        dlg.exec_()

    def _on_edit_laf_sensors(self):
        """Open the LAF sensor list editor (admin-only)."""
        if self.auth.get_current_user_role() != 'Admin':
            QMessageBox.warning(self, "Yetki Yok",
                                "LAF sensörlerini sadece admin düzenleyebilir.")
            return
        try:
            from core.laf_manager import LafManager
        except ImportError:
            QMessageBox.critical(self, "Hata", "laf_manager modülü yüklenemedi.")
            return
        lm = LafManager(self.db, self.auth, self._audit_manager)
        dlg = _LafSensorsDialog(lm, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.laf_settings_changed.emit()

    def _on_edit_weidmuller_modules(self):
        """Open the Weidmüller IO modules editor (admin-only)."""
        if self.auth.get_current_user_role() != 'Admin':
            QMessageBox.warning(self, "Yetki Yok",
                                "IO modüllerini sadece admin düzenleyebilir.")
            return
        try:
            from core.weidmuller_manager import WeidmullerManager
        except ImportError:
            QMessageBox.critical(self, "Hata",
                                 "weidmuller_manager modülü yüklenemedi.")
            return
        wm = WeidmullerManager(self.db, self.auth, self._audit_manager)
        dlg = _WeidmullerModulesDialog(wm, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.weidmuller_settings_changed.emit()

    def apply_styles(self):
        self.setStyleSheet("""
            QWidget {
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 14px;
                color: #374151;
                background-color: #F9FAFB;
            }
            
            QGroupBox#settingCard {
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                margin-top: 8px;
                background-color: #FFFFFF;
                padding: 0px;
                font-weight: 600;
                color: #1F2937;
            }
            
            QGroupBox#settingCard::title {
                subcontrol-origin: margin;
                left: 20px;
                top: 8px;
                padding: 0 8px;
                font-weight: 600;
                font-size: 15px;
                color: #1F2937;
                background-color: transparent;
            }
            
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #3B82F6, stop:1 #2563EB);
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                color: white;
                font-weight: 600;
                font-size: 13px;
                min-width: 100px;
            }
            
            QPushButton#uploadLogoBtn {
                background-color: #DBEAFE;
                border: 1px solid #93C5FD;
                border-radius: 8px;
                padding: 10px 24px;
                color: #1F2937;
                font-weight: 600;
                font-size: 13px;
                min-width: 160px;
                min-height: 38px;
            }
            
            QPushButton#uploadLogoBtn:hover {
                background-color: #BFDBFE;
            }
            
            QPushButton#timeoutSaveBtn {
                background-color: #DBEAFE;
                border: 1px solid #93C5FD;
                border-radius: 8px;
                padding: 8px 20px;
                color: #1F2937;
                font-weight: 600;
                font-size: 13px;
                min-width: 100px;
                min-height: 34px;
            }
            
            QPushButton#timeoutSaveBtn:hover {
                background-color: #BFDBFE;
            }
            
            QPushButton#storageBrowseBtn {
                min-width: 36px;
                max-width: 44px;
                min-height: 34px;
                padding: 4px;
                font-size: 16px;
            }
            
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #2563EB, stop:1 #1D4ED8);
            }
            
            QPushButton:pressed {
                background: #1E40AF;
            }
            
            QComboBox {
                border: 1px solid #D1D5DB;
                border-radius: 8px;
                padding: 8px 12px;
                min-width: 180px;
                background-color: #FFFFFF;
                color: #1F2937;
                font-size: 13px;
            }
            
            QComboBox:hover {
                border-color: #3B82F6;
            }
            
            QComboBox:focus {
                border: 2px solid #3B82F6;
            }
            
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #6B7280;
                margin-right: 8px;
            }
            
            QSpinBox {
                border: 1px solid #D1D5DB;
                border-radius: 8px;
                padding: 8px 12px;
                background-color: #FFFFFF;
                color: #1F2937;
                font-size: 13px;
                min-width: 120px;
            }
            
            QSpinBox:hover {
                border-color: #3B82F6;
            }
            
            QSpinBox:focus {
                border: 2px solid #3B82F6;
            }
            
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #F3F4F6;
                border: none;
                border-radius: 4px;
                width: 20px;
                margin: 2px;
            }
            
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #E5E7EB;
            }
            
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            
            QScrollBar:vertical {
                background-color: transparent;
                width: 10px;
                margin: 0;
            }
            
            QScrollBar::handle:vertical {
                background-color: #D1D5DB;
                border-radius: 5px;
                min-height: 30px;
            }
            
            QScrollBar::handle:vertical:hover {
                background-color: #9CA3AF;
            }
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)


# ── Door labels editor dialog (Oraps Faz-4) ──────────────────────
class _DoorLabelsDialog(QDialog):
    """Modal letting admins rename the 12 physical door labels."""

    def __init__(self, batch_manager, parent=None):
        super().__init__(parent)
        self.bm = batch_manager
        self.setWindowTitle("Kapı İsimleri")
        self.setMinimumWidth(520)
        self._edits = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("Her kapı için kullanıcıya gösterilecek etiketi düzenleyin.\n"
                     "Bu etiketler batch konfigürasyonu dialogunda görünür.")
        hdr.setStyleSheet("color:#6b7280;font-size:12px;")
        hdr.setWordWrap(True)
        root.addWidget(hdr)

        # 12 satır: [Kapı N] [LineEdit]
        labels = {row['door_index']: row for row in self.bm.get_door_labels()}
        form = QFormLayout()
        form.setSpacing(6)
        for i in range(1, 13):
            edit = QLineEdit(labels.get(i, {}).get('label', f"Kapı {i}"))
            edit.setStyleSheet(
                "QLineEdit { border:1px solid #d1d5db; border-radius:6px;"
                " padding:6px 10px; background:#ffffff; font-size:13px; }"
                " QLineEdit:focus { border-color:#3b82f6; }"
            )
            self._edits[i] = edit
            form.addRow(f"Kapı #{i}:", edit)
        root.addLayout(form)

        # Buttons
        btn_row = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_row.button(QDialogButtonBox.Save).setText("💾 Kaydet")
        btn_row.button(QDialogButtonBox.Cancel).setText("İptal")
        btn_row.accepted.connect(self._on_save)
        btn_row.rejected.connect(self.reject)
        root.addWidget(btn_row)

    def _on_save(self):
        try:
            existing = {row['door_index']: row for row in self.bm.get_door_labels()}
            for i, edit in self._edits.items():
                new_label = edit.text().strip()
                old_label = existing.get(i, {}).get('label', '')
                if new_label and new_label != old_label:
                    self.bm.update_door_label(i, new_label)
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        QMessageBox.information(self, "Kaydedildi", "Kapı isimleri güncellendi.")
        self.accept()


# ── Port labels + motion sensor editor dialog (Oraps Faz-4) ──────
class _PortLabelsDialog(QDialog):
    """Modal letting admins edit the 14 glove-port labels and pick which
    ports have a motion sensor (Faz-5'te IO worker'ından audit'e yazılır)."""

    def __init__(self, batch_manager, parent=None):
        super().__init__(parent)
        self.bm = batch_manager
        self.setWindowTitle("Eldiven Port Ayarları")
        self.setMinimumWidth(600)
        self._edits = {}     # port_index -> QLineEdit
        self._motion = {}    # port_index -> QCheckBox
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel(
            "Eldiven portlarının isimlerini düzenleyin ve hangi portlarda hareket sensörü\n"
            "bulunduğunu işaretleyin. Hareket sensörü olan portlar audit trail'e\n"
            "ORAPS_PORT_MOTION olayı olarak kaydedilir."
        )
        hdr.setStyleSheet("color:#6b7280;font-size:12px;")
        hdr.setWordWrap(True)
        root.addWidget(hdr)

        # Header row
        head = QHBoxLayout()
        h1 = QLabel("Port"); h1.setFixedWidth(60)
        h1.setStyleSheet("font-weight:600;color:#374151;")
        h2 = QLabel("Etiket"); h2.setStyleSheet("font-weight:600;color:#374151;")
        h3 = QLabel("🚶 Hareket Sensörü"); h3.setFixedWidth(150)
        h3.setStyleSheet("font-weight:600;color:#374151;")
        head.addWidget(h1); head.addWidget(h2, 1); head.addWidget(h3)
        root.addLayout(head)

        # 14 rows
        ports = {row['port_index']: row for row in self.bm.get_port_labels()}
        for i in range(1, 15):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)

            idx_lbl = QLabel(f"#{i}")
            idx_lbl.setFixedWidth(60)
            idx_lbl.setStyleSheet("color:#374151;font-size:13px;")

            edit = QLineEdit(ports.get(i, {}).get('label', f"Port {i}"))
            edit.setStyleSheet(
                "QLineEdit { border:1px solid #d1d5db; border-radius:6px;"
                " padding:6px 10px; background:#ffffff; font-size:13px; }"
                " QLineEdit:focus { border-color:#3b82f6; }"
            )
            self._edits[i] = edit

            cb = QCheckBox()
            cb.setChecked(bool(ports.get(i, {}).get('has_motion_sensor', 0)))
            cb_wrap = QWidget()
            cb_layout = QHBoxLayout(cb_wrap)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.addStretch()
            cb_layout.addWidget(cb)
            cb_layout.addStretch()
            cb_wrap.setFixedWidth(150)
            self._motion[i] = cb

            row_layout.addWidget(idx_lbl)
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(cb_wrap)
            root.addLayout(row_layout)

        # Buttons
        btn_row = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_row.button(QDialogButtonBox.Save).setText("💾 Kaydet")
        btn_row.button(QDialogButtonBox.Cancel).setText("İptal")
        btn_row.accepted.connect(self._on_save)
        btn_row.rejected.connect(self.reject)
        root.addWidget(btn_row)

    def _on_save(self):
        try:
            existing = {row['port_index']: row for row in self.bm.get_port_labels()}
            for i in self._edits:
                new_label = self._edits[i].text().strip()
                old_label = existing.get(i, {}).get('label', '')
                new_motion = 1 if self._motion[i].isChecked() else 0
                old_motion = int(existing.get(i, {}).get('has_motion_sensor', 0))

                kwargs = {}
                if new_label and new_label != old_label:
                    kwargs['label'] = new_label
                if new_motion != old_motion:
                    kwargs['has_motion_sensor'] = new_motion
                if kwargs:
                    self.bm.update_port_label(i, **kwargs)
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        QMessageBox.information(self, "Kaydedildi", "Port ayarları güncellendi.")
        self.accept()


# ── Light barriers editor (Faz-6c) ───────────────────────────────
class _BarrierDoorPickerDialog(QDialog):
    """Bir bariyere bağlanacak kapıları çoklu seçmek için mini dialog.
    Kapı listesi get_door_labels'tan alınır; adı olan kapılar
    'Kapı N — Ad' biçiminde, adsızlar 'Kapı N' olarak listelenir."""

    def __init__(self, door_labels: dict, current: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bariyere Bağlı Kapılar")
        self.setMinimumSize(340, 460)
        self._selected: list = []
        from PyQt5.QtWidgets import QListWidget, QListWidgetItem
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)
        info = QLabel("Bu bariyer tetiklenince aşağıda seçili kapılar 3D "
                      "görünümde turuncu boyanır ve alarm şeridine yansır.")
        info.setStyleSheet("color:#6b7280;font-size:12px;")
        info.setWordWrap(True)
        root.addWidget(info)
        self.list = QListWidget()
        cur_set = {int(x) for x in (current or [])}
        for idx in sorted(door_labels.keys()):
            lbl = (door_labels.get(idx) or '').strip()
            text = f"Kapı {idx}" + (f" — {lbl}" if lbl else '')
            it = QListWidgetItem(text)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if idx in cur_set else Qt.Unchecked)
            it.setData(Qt.UserRole, int(idx))
            self.list.addItem(it)
        root.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _accept(self):
        picked = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                picked.append(int(it.data(Qt.UserRole)))
        if not picked:
            QMessageBox.warning(self, "Uyarı",
                                "En az bir kapı seçmelisiniz.")
            return
        self._selected = picked
        self.accept()

    def selected(self) -> list:
        return list(self._selected)


class _BarriersDialog(QDialog):
    """Admin dialog: CRUD over `light_barriers`. Her bariyer N kapıya
    bağlanabilir; UI kapı listesini virgülle gösterir, 'Seç…' butonu ile
    checkbox listesinden değiştirilir."""

    def __init__(self, batch_manager, parent=None):
        super().__init__(parent)
        self.bm = batch_manager
        self.setWindowTitle("Işık Bariyerleri")
        self.setMinimumSize(760, 420)
        self._door_labels = {}   # door_index -> label
        # Satır bazında düzenlenen kapı listesi cache (row_id -> List[int])
        self._row_doors: dict = {}
        self._build_ui()
        self._load_doors()
        self._reload()

    def _build_ui(self):
        from PyQt5.QtWidgets import (QTableWidget, QHeaderView,
                                     QAbstractItemView)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        info = QLabel(
            "Işık bariyeri N kapıya bağlanır — tetiklendiğinde bağlı tüm "
            "kapılar 3D görünümde turuncu boyanır ve alarm şeridi yanar. "
            "'Weidmüller IO → 🔗 Bağla' menüsünden bir dijital girişe atayın."
        )
        info.setStyleSheet("color:#6b7280;font-size:12px;")
        info.setWordWrap(True)
        root.addWidget(info)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Etiket", "Kapılar", "Aktif", "Açıklama"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        root.addWidget(self.table)

        row = QHBoxLayout()
        self.add_btn = QPushButton("➕ Yeni Bariyer")
        self.add_btn.clicked.connect(self._on_add)
        self.del_btn = QPushButton("🗑 Seçili Sil")
        self.del_btn.clicked.connect(self._on_delete)
        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("💾 Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        root.addLayout(row)

    def _load_doors(self):
        try:
            for d in self.bm.get_door_labels():
                self._door_labels[int(d['door_index'])] = (d.get('label') or '').strip()
        except Exception:
            for i in range(1, 13):
                self._door_labels[i] = ''

    def _doors_cell_widget(self, bid: int, doors: list) -> QWidget:
        """Hücre widget: kapı listesini gösterir + 'Seç…' butonu."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(6)
        lbl = QLabel(self._format_doors(doors))
        lbl.setStyleSheet("color:#374151;font-size:12px;")
        lbl.setToolTip(self._format_doors_tooltip(doors))
        h.addWidget(lbl, 1)
        btn = QPushButton("Seç…")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(24)
        btn.setStyleSheet(
            "QPushButton { background:#eff6ff;color:#1d4ed8;"
            "border:1px solid #bfdbfe;border-radius:4px;padding:2px 8px;"
            "font-size:11px;font-weight:600; }"
            "QPushButton:hover { background:#dbeafe; }"
        )
        btn.clicked.connect(lambda _=None, row_id=bid: self._on_pick_doors(row_id))
        h.addWidget(btn)
        w.setProperty('label_widget', lbl)
        return w

    def _format_doors(self, doors: list) -> str:
        if not doors:
            return "— hiç kapı seçilmedi —"
        return "Kapı " + ", ".join(str(i) for i in sorted(set(int(d) for d in doors)))

    def _format_doors_tooltip(self, doors: list) -> str:
        if not doors:
            return ""
        parts = []
        for i in sorted(set(int(d) for d in doors)):
            lbl = self._door_labels.get(i, '')
            parts.append(f"Kapı {i}" + (f" ({lbl})" if lbl else ''))
        return "\n".join(parts)

    def _on_pick_doors(self, bid: int):
        current = list(self._row_doors.get(bid, []))
        dlg = _BarrierDoorPickerDialog(self._door_labels, current, self)
        if dlg.exec_() != dlg.Accepted:
            return
        picked = dlg.selected()
        self._row_doors[bid] = picked
        # Etiketi ve tooltip'i güncelle
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is None or it.data(Qt.UserRole) != bid:
                continue
            w = self.table.cellWidget(r, 1)
            if w is None:
                continue
            lbl = w.property('label_widget')
            if lbl is not None:
                lbl.setText(self._format_doors(picked))
                lbl.setToolTip(self._format_doors_tooltip(picked))
            break

    def _reload(self):
        from PyQt5.QtWidgets import QTableWidgetItem
        self.table.setRowCount(0)
        self._row_doors = {}
        for b in self.bm.list_barriers():
            r = self.table.rowCount()
            self.table.insertRow(r)
            bid = int(b['id'])
            idxs = list(b.get('door_indices') or [])
            self._row_doors[bid] = idxs
            # 0: Etiket
            it = QTableWidgetItem(b['label'])
            it.setData(Qt.UserRole, bid)
            self.table.setItem(r, 0, it)
            # 1: Kapılar (widget)
            self.table.setCellWidget(r, 1, self._doors_cell_widget(bid, idxs))
            # 2: Aktif
            act = QTableWidgetItem('')
            act.setFlags(act.flags() | Qt.ItemIsUserCheckable)
            act.setCheckState(Qt.Checked if b['is_active'] else Qt.Unchecked)
            self.table.setItem(r, 2, act)
            # 3: Açıklama
            self.table.setItem(r, 3, QTableWidgetItem(b.get('description', '') or ''))

    def _on_add(self):
        # Varsayılan: 1 numaralı kapı seçili tek-kapılı bariyer.
        try:
            new_id = self.bm.add_barrier("Yeni Bariyer", door_indices=[1])
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == new_id:
                self.table.selectRow(r)
                break

    def _on_delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        bid = int(self.table.item(r, 0).data(Qt.UserRole))
        label = self.table.item(r, 0).text()
        if QMessageBox.question(
            self, "Sil",
            f"'{label}' bariyeri silinsin mi?\n"
            "(Bu bariyere bağlı IO noktaları orphan olur — daha sonra "
            "tekrar bağlanabilirler.)"
        ) != QMessageBox.Yes:
            return
        try:
            self.bm.delete_barrier(bid)
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()

    def _on_save(self):
        errors = []
        for r in range(self.table.rowCount()):
            bid = int(self.table.item(r, 0).data(Qt.UserRole))
            try:
                label = self.table.item(r, 0).text().strip()
                doors = list(self._row_doors.get(bid, []))
                active = 1 if self.table.item(r, 2).checkState() == Qt.Checked else 0
                desc = self.table.item(r, 3).text().strip()
                self.bm.update_barrier(
                    bid,
                    label=label,
                    door_indices=doors,
                    is_active=active,
                    description=desc,
                )
            except Exception as e:
                errors.append(f"Satır {r+1}: {e}")
        if errors:
            QMessageBox.warning(self, "Bazı hatalar", "\n".join(errors))
            return
        QMessageBox.information(self, "Kaydedildi", "Işık bariyerleri güncellendi.")
        self.accept()


# ── Kablosuz IR bariyer sensörleri editörü (Faz-7) ──────────────────
class _BarrierSensorsDialog(QDialog):
    """Master (USB CDC) üzerinden gelen ESP-NOW bariyer sensörlerini
    listeler. MAC gösterilmez; kullanıcı sadece etiket + port_index
    ayarlayabilir. Auto-discover ile yeni sensörler otomatik listeye
    düşer (BarrierManager tarafından eklenir)."""

    def __init__(self, database, batch_manager, parent=None):
        super().__init__(parent)
        self.db = database
        self.bm = batch_manager
        self.setWindowTitle("Kablosuz Bariyer Sensörleri")
        self.setMinimumSize(680, 420)
        self._port_labels: dict = {}   # port_index → label (isimli portlar)
        self._build_ui()
        self._load_ports()
        self._reload()
        # UI 3 saniyede bir yenilensin — yeni sensör keşfi anında görünsün.
        from PyQt5.QtCore import QTimer as _QT
        self._refresh_timer = _QT(self)
        self._refresh_timer.setInterval(3000)
        self._refresh_timer.timeout.connect(self._reload_silent)
        self._refresh_timer.start()

    def _build_ui(self):
        from PyQt5.QtWidgets import (QTableWidget, QHeaderView,
                                     QAbstractItemView)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)
        info = QLabel(
            "Kablosuz IR bariyer sensörleri PC'ye ESP-NOW master (USB) "
            "üzerinden bağlanır. Yeni bir sensör mesaj gönderdiğinde "
            "otomatik olarak listeye eklenir. Bir sensörü porta bağlarsan, "
            "sensör tetiklendiğinde 3D'de o port mavi (Port Hareketi) "
            "boyanır ve audit'e yazılır."
        )
        info.setStyleSheet("color:#6b7280;font-size:12px;")
        info.setWordWrap(True)
        root.addWidget(info)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["#", "Etiket", "Port", "Aktif", "Son Görülme", "Pil"]
        )
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        root.addWidget(self.table)

        row = QHBoxLayout()
        self.del_btn = QPushButton("🗑 Seçili Sil")
        self.del_btn.clicked.connect(self._on_delete)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("💾 Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Kapat")
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        root.addLayout(row)

    def _load_ports(self):
        """İsimli ORAPS portlarını { port_index: label } sözlüğüne yükle."""
        try:
            for p in self.bm.get_port_labels():
                lbl = (p.get('label') or '').strip()
                if lbl:
                    self._port_labels[int(p['port_index'])] = lbl
        except Exception:
            self._port_labels = {}

    def _port_combo(self, current_index):
        cb = QComboBox()
        cb.addItem("— Bağlı değil —", None)
        for idx in sorted(self._port_labels.keys()):
            cb.addItem(f"Port {idx} — {self._port_labels[idx]}", idx)
        # Seçim
        target = 0
        if current_index is not None:
            for k in range(cb.count()):
                if cb.itemData(k) == current_index:
                    target = k
                    break
        cb.setCurrentIndex(target)
        return cb

    def _reload_silent(self):
        """Timer tick — düzenlenmemiş satırları koruyarak yeni sensörleri ekle.
        Basit yaklaşım: seçili satırı korumak için mevcut kaydedilmiş
        değerleri okuyup tekrar reload'lar. Eğer kullanıcı düzenlemekteyse
        değişiklik kaybolur; daha güvenli: sadece yeni sensör varsa reload."""
        try:
            fresh_ids = {int(s['id']) for s in self.db.list_barrier_sensors() or []}
        except Exception:
            return
        current_ids = set()
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is None:
                continue
            sid = it.data(Qt.UserRole)
            if sid is not None:
                current_ids.add(int(sid))
        if fresh_ids - current_ids:
            self._reload()   # yeni sensör keşfedildi → tam yenile

    def _reload(self):
        from PyQt5.QtWidgets import QTableWidgetItem
        self.table.setRowCount(0)
        for s in self.db.list_barrier_sensors() or []:
            r = self.table.rowCount()
            self.table.insertRow(r)
            sid = int(s['id'])
            # 0: #
            it0 = QTableWidgetItem(f"#{sid}")
            it0.setFlags(it0.flags() & ~Qt.ItemIsEditable)
            it0.setData(Qt.UserRole, sid)
            self.table.setItem(r, 0, it0)
            # 1: Etiket
            self.table.setItem(r, 1, QTableWidgetItem(s.get('label') or ''))
            # 2: Port combo
            self.table.setCellWidget(r, 2, self._port_combo(s.get('port_index')))
            # 3: Aktif
            act = QTableWidgetItem('')
            act.setFlags(act.flags() | Qt.ItemIsUserCheckable)
            act.setCheckState(Qt.Checked if s.get('is_enabled') else Qt.Unchecked)
            self.table.setItem(r, 3, act)
            # 4: Son görülme
            seen = s.get('last_seen_ts') or ''
            seen_disp = seen[11:19] if len(seen) >= 19 else seen
            it4 = QTableWidgetItem(seen_disp)
            it4.setFlags(it4.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 4, it4)
            # 5: Pil
            bmv = s.get('last_battery_mv')
            bat = f"{bmv/1000:.2f} V" if bmv else '—'
            it5 = QTableWidgetItem(bat)
            it5.setFlags(it5.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 5, it5)

    def _on_delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        sid = int(self.table.item(r, 0).data(Qt.UserRole))
        label = self.table.item(r, 1).text() or f"#{sid}"
        if QMessageBox.question(
            self, "Sil",
            f"'{label}' bariyer sensörü silinsin mi?\n"
            "(Sensör tekrar mesaj gönderirse otomatik yeniden eklenir.)"
        ) != QMessageBox.Yes:
            return
        try:
            self.db.delete_barrier_sensor(sid)
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()

    def _on_save(self):
        errors = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is None:
                continue
            sid = int(it.data(Qt.UserRole))
            try:
                label = (self.table.item(r, 1).text() or '').strip()
                pcb = self.table.cellWidget(r, 2)
                port_idx = pcb.currentData() if pcb is not None else None
                active = 1 if self.table.item(r, 3).checkState() == Qt.Checked else 0
                self.db.update_barrier_sensor(
                    sid, label=label,
                    port_index=port_idx, is_enabled=active,
                )
            except Exception as e:
                errors.append(f"#{sid}: {e}")
        if errors:
            QMessageBox.warning(self, "Bazı hatalar", "\n".join(errors))
            return
        QMessageBox.information(self, "Kaydedildi",
                                "Bariyer sensörleri güncellendi.")
        self.accept()

    def closeEvent(self, event):
        try:
            self._refresh_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)


class _LafSensorsDialog(QDialog):
    """Admin dialog: add / edit / delete LAF sensors."""

    REG_TYPES = ('holding', 'input')
    DATA_TYPES = ('uint16', 'int16', 'uint32', 'int32', 'float32')

    def __init__(self, laf_manager, parent=None):
        super().__init__(parent)
        self.lm = laf_manager
        self.setWindowTitle("LAF Sensörleri")
        self.setMinimumSize(900, 460)
        self._build_ui()
        self._reload()

    def _build_ui(self):
        from PyQt5.QtWidgets import (QTableWidget, QTableWidgetItem,
                                     QHeaderView, QAbstractItemView)
        root = QVBoxLayout(self)
        info = QLabel("Cihaz dökümanına göre register adresleri girilmelidir. "
                      "Decimal veya hex kabul edilir (örn. 16494, 0x406E, 406E). "
                      "value = (raw × scale) + offset")
        info.setStyleSheet("color:#6b7280;font-size:11px;")
        root.addWidget(info)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Etiket", "Tip", "Register", "Reg-Tipi", "Data-Tipi",
            "Scale", "Offset", "Birim", "Görünür"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 9):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        root.addWidget(self.table)

        row = QHBoxLayout()
        self.add_btn = QPushButton("➕ Yeni Sensör")
        self.add_btn.clicked.connect(self._on_add)
        self.del_btn = QPushButton("🗑 Seçili Sil")
        self.del_btn.clicked.connect(self._on_delete)
        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("💾 Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        root.addLayout(row)

    def _reload(self):
        from PyQt5.QtWidgets import QTableWidgetItem
        self.table.setRowCount(0)
        for s in self.lm.list_sensors():
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [
                s['label'], s['sensor_type'], self._format_register_addr(s['register_addr']),
                s['register_type'], s['data_type'],
                str(s['scale']), str(s['offset']), s.get('unit', '') or '',
                '✓' if s['is_visible'] else '',
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 8:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if s['is_visible'] else Qt.Unchecked)
                    item.setText('')
                self.table.setItem(r, c, item)
            self.table.item(r, 0).setData(Qt.UserRole, s['id'])

    def _on_add(self):
        from PyQt5.QtWidgets import QTableWidgetItem
        try:
            new_id = self.lm.add_sensor(
                label='Yeni Sensör', sensor_type='generic',
                register_addr=0, register_type='holding',
                data_type='uint16', scale=1.0, offset=0.0, unit='',
                is_visible=1, sort_order=999,
            )
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()
        # Select new row
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == new_id:
                self.table.selectRow(r)
                break

    def _on_delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        sid = self.table.item(r, 0).data(Qt.UserRole)
        if QMessageBox.question(
            self, "Sil",
            f"'{self.table.item(r, 0).text()}' silinsin mi?"
        ) != QMessageBox.Yes:
            return
        try:
            self.lm.delete_sensor(int(sid))
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()

    @staticmethod
    def _format_register_addr(value) -> str:
        try:
            return f"0x{int(value):04X}"
        except (TypeError, ValueError):
            return str(value or "0")

    @staticmethod
    def _parse_register_addr(text: str) -> int:
        raw = (text or '').strip().replace('_', '')
        if not raw:
            return 0
        lower = raw.lower()
        if lower.startswith('0x'):
            return int(lower, 16)
        if lower.endswith('h'):
            return int(lower[:-1], 16)
        if any(ch in 'abcdef' for ch in lower):
            return int(lower, 16)
        return int(lower, 10)

    def _on_save(self):
        errors = []
        for r in range(self.table.rowCount()):
            sid = int(self.table.item(r, 0).data(Qt.UserRole))
            try:
                fields = {
                    'label':         self.table.item(r, 0).text().strip(),
                    'sensor_type':   self.table.item(r, 1).text().strip() or 'generic',
                    'register_addr': self._parse_register_addr(self.table.item(r, 2).text()),
                    'register_type': self.table.item(r, 3).text().strip().lower(),
                    'data_type':     self.table.item(r, 4).text().strip().lower(),
                    'scale':         float(self.table.item(r, 5).text().strip() or '1'),
                    'offset':        float(self.table.item(r, 6).text().strip() or '0'),
                    'unit':          self.table.item(r, 7).text().strip(),
                    'is_visible':    1 if self.table.item(r, 8).checkState() == Qt.Checked else 0,
                }
                self.lm.update_sensor(sid, **fields)
            except Exception as e:
                errors.append(f"Satır {r+1}: {e}")
        if errors:
            QMessageBox.warning(self, "Bazı hatalar", "\n".join(errors))
            return
        QMessageBox.information(self, "Kaydedildi", "LAF sensörleri güncellendi.")
        self.accept()


class _WeidmullerModulesDialog(QDialog):
    """Admin dialog: Weidmüller IO modülleri (ekle/düzenle/sil + IO noktaları)."""

    def __init__(self, wm_manager, parent=None):
        super().__init__(parent)
        self.wm = wm_manager
        self.setWindowTitle("Weidmüller IO Modülleri")
        self.setMinimumSize(960, 460)
        self._build_ui()
        self._reload()

    def _build_ui(self):
        from PyQt5.QtWidgets import (QTableWidget, QHeaderView,
                                     QAbstractItemView)
        root = QVBoxLayout(self)
        info = QLabel("UR20-FBC-MOD-TCP coupler için varsayılan adresler: "
                      "Input @0x0000, Output @0x0800. Detaylı düzenleme "
                      "için satırı seçip 'Düzenle…' butonuna basın.")
        info.setStyleSheet("color:#6b7280;font-size:11px;")
        info.setWordWrap(True)
        root.addWidget(info)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Ad", "Host", "Port", "Unit ID", "Poll (ms)",
            "Aktif", "Açıklama", "IO Noktaları"
        ])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        root.addWidget(self.table)

        row = QHBoxLayout()
        self.add_btn = QPushButton("➕ Yeni Modül")
        self.add_btn.clicked.connect(self._on_add)
        self.del_btn = QPushButton("🗑 Seçili Sil")
        self.del_btn.clicked.connect(self._on_delete)
        self.points_btn = QPushButton("⚙ IO Noktalarını Düzenle…")
        self.points_btn.clicked.connect(self._on_edit_points)
        self.probe_btn = QPushButton("🔍 Coupler'dan Tara")
        self.probe_btn.setToolTip(
            "Seçili modülün IP adresine TCP ile bağlanır, coupler kimliği "
            "ve Process Input/Output sözcük sayısını okur."
        )
        self.probe_btn.clicked.connect(self._on_probe)
        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        row.addWidget(self.points_btn)
        row.addWidget(self.probe_btn)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("💾 Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        root.addLayout(row)

    def _reload(self):
        from PyQt5.QtWidgets import QTableWidgetItem
        self.table.setRowCount(0)
        for m in self.wm.list_modules():
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [
                m['name'], m['host'], str(m['port']), str(m['unit_id']),
                str(m['poll_ms']), '', m.get('description', '') or '', '',
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 5:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    on = bool(m['is_active'])
                    item.setCheckState(Qt.Checked if on else Qt.Unchecked)
                    item.setText('')
                if c == 7:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    pts = self.wm.list_points(module_id=m['id'])
                    counts = {'DI': 0, 'DO': 0, 'AI': 0, 'AO': 0}
                    for p in pts:
                        counts[p['point_type']] = counts.get(p['point_type'], 0) + 1
                    item.setText(f"DI:{counts['DI']} DO:{counts['DO']} "
                                 f"AI:{counts['AI']} AO:{counts['AO']}")
                self.table.setItem(r, c, item)
            self.table.item(r, 0).setData(Qt.UserRole, m['id'])

    def _on_add(self):
        try:
            self.wm.add_module(
                name=f"IO-{len(self.wm.list_modules())+1}",
                host='192.168.0.222', port=502, unit_id=255,
                mock_mode=0, description='',
            )
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()

    def _on_delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        mid = self.table.item(r, 0).data(Qt.UserRole)
        if QMessageBox.question(
            self, "Sil",
            f"'{self.table.item(r, 0).text()}' silinsin mi? "
            "(IO noktaları da silinecek)"
        ) != QMessageBox.Yes:
            return
        try:
            self.wm.delete_module(int(mid))
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()

    def _on_edit_points(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Seçim", "Önce bir modül seçin.")
            return
        mid = int(self.table.item(r, 0).data(Qt.UserRole))
        dlg = _WeidmullerPointsDialog(self.wm, mid, parent=self)
        dlg.exec_()
        self._reload()

    def _on_probe(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Seçim", "Önce bir modül seçin.")
            return
        mid = int(self.table.item(r, 0).data(Qt.UserRole))
        # Önce satırdaki son değerleri kaydet (kullanıcı IP'yi değiştirmiş
        # ama Kaydet'e basmamış olabilir)
        try:
            self.wm.update_module(
                mid,
                host=self.table.item(r, 1).text().strip(),
                port=int(self.table.item(r, 2).text().strip() or '502'),
                unit_id=int(self.table.item(r, 3).text().strip() or '255'),
            )
        except Exception:
            pass  # validation hatasında bile probe deneyelim

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = self.wm.probe_coupler(mid, timeout=2.0)
        finally:
            QApplication.restoreOverrideCursor()

        if not res.get('ok'):
            QMessageBox.warning(
                self, "Coupler bulunamadı",
                f"Adres: {res.get('host')}:{res.get('port')}\n\n"
                f"Hata: {res.get('error') or 'Bilinmeyen hata.'}\n\n"
                "Modül ağda erişilemez durumda olabilir."
            )
            return

        lines = [
            f"Adres   : {res['host']}:{res['port']} (unit {res['unit_id']})",
            f"Coupler : {res.get('coupler_id') or '(okunamadı)'}",
            f"PI sözcük : {res.get('pi_words', 0)}",
            f"PO sözcük : {res.get('po_words', 0)}",
        ]
        if res.get('error'):
            lines.append("")
            lines.append(f"Uyarı: {res['error']}")
        QMessageBox.information(self, "Coupler Tarama Sonucu", "\n".join(lines))

    def _on_save(self):
        errors = []
        for r in range(self.table.rowCount()):
            mid = int(self.table.item(r, 0).data(Qt.UserRole))
            try:
                fields = {
                    'name':        self.table.item(r, 0).text().strip(),
                    'host':        self.table.item(r, 1).text().strip(),
                    'port':        int(self.table.item(r, 2).text().strip() or '502'),
                    'unit_id':     int(self.table.item(r, 3).text().strip() or '255'),
                    'poll_ms':     int(self.table.item(r, 4).text().strip() or '500'),
                    'is_active':   1 if self.table.item(r, 5).checkState() == Qt.Checked else 0,
                    'mock_mode':   0,
                    'description': self.table.item(r, 6).text().strip(),
                }
                self.wm.update_module(mid, **fields)
            except Exception as e:
                errors.append(f"Satır {r+1}: {e}")
        if errors:
            QMessageBox.warning(self, "Bazı hatalar", "\n".join(errors))
            return
        QMessageBox.information(self, "Kaydedildi", "IO modülleri güncellendi.")
        self.accept()


class _WeidmullerPointsDialog(QDialog):
    """Admin dialog: tek bir modüldeki IO noktalarını düzenle."""

    POINT_TYPES = ('DI', 'DO', 'AI', 'AO')

    def __init__(self, wm_manager, module_id: int, parent=None):
        super().__init__(parent)
        self.wm = wm_manager
        self.module_id = module_id
        mod = wm_manager.get_module(module_id)
        name = mod['name'] if mod else f"#{module_id}"
        self.setWindowTitle(f"IO Noktaları — {name}")
        self.setMinimumSize(820, 460)
        self._build_ui()
        self._reload()

    def _build_ui(self):
        from PyQt5.QtWidgets import (QTableWidget, QHeaderView,
                                     QAbstractItemView)
        root = QVBoxLayout(self)
        info = QLabel("Mantıksal kanal eşleme — register adresleri modül "
                      "ayarlarından otomatik hesaplanır. Tipler: DI/DO/AI/AO.")
        info.setStyleSheet("color:#6b7280;font-size:11px;")
        info.setWordWrap(True)
        root.addWidget(info)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Tip", "Kanal", "Etiket",
            "Görünür", "Açıklama", "Bağlantı", ""
        ])
        hh = self.table.horizontalHeader()
        for c in range(4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        root.addWidget(self.table)

        row = QHBoxLayout()
        self.add_btn = QPushButton("➕ Yeni Nokta")
        self.add_btn.clicked.connect(self._on_add)
        self.del_btn = QPushButton("🗑 Seçili Sil")
        self.del_btn.clicked.connect(self._on_delete)
        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("💾 Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        root.addLayout(row)

    def _reload(self):
        from PyQt5.QtWidgets import QTableWidgetItem
        self.table.setRowCount(0)
        for p in self.wm.list_points(module_id=self.module_id):
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [
                p['point_type'], str(p['channel']), p['name'],
                '', p.get('description', '') or '',
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 3:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if p['is_visible'] else Qt.Unchecked)
                    item.setText('')
                self.table.setItem(r, c, item)
            self.table.item(r, 0).setData(Qt.UserRole, p['id'])

            # Bağlantı sütunu (read-only özet)
            link_type = p.get('link_type')
            link_id = p.get('link_id')
            link_role = (p.get('link_role') or '').strip()
            if link_type and link_id is not None:
                link_text = self.wm.resolve_link_label(link_type, link_id)
                if link_role:
                    link_text += f"  [{link_role}]"
            else:
                link_text = "—"
            link_item = QTableWidgetItem(link_text)
            link_item.setFlags(link_item.flags() & ~Qt.ItemIsEditable)
            if not link_type:
                link_item.setForeground(QColor('#9CA3AF'))
            self.table.setItem(r, 5, link_item)

            btn = QPushButton("🔗 Bağla")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background:#EFF6FF;color:#1E40AF;border:1px solid #BFDBFE;"
                " border-radius:5px;padding:3px 8px;min-width:0; }"
                " QPushButton:hover { background:#DBEAFE; }"
            )
            btn.clicked.connect(lambda _=False, pid=p['id']: self._open_link_dialog(pid))
            # Bağla + (bağlıysa) Kaldır butonlarını yatay bir container'da göster.
            _cell = QWidget()
            _h = QHBoxLayout(_cell)
            _h.setContentsMargins(2, 0, 2, 0)
            _h.setSpacing(4)
            _h.addWidget(btn)
            if link_type:
                rm_btn = QPushButton("❌ Kaldır")
                rm_btn.setCursor(Qt.PointingHandCursor)
                rm_btn.setToolTip("Bu IO noktasının bağlantısını temizle")
                rm_btn.setStyleSheet(
                    "QPushButton { background:#FEE2E2;color:#B91C1C;"
                    " border:1px solid #FCA5A5;border-radius:5px;"
                    " padding:3px 8px;min-width:0; }"
                    " QPushButton:hover { background:#FECACA; }"
                )
                rm_btn.clicked.connect(
                    lambda _=False, pid=p['id'], txt=link_text:
                    self._on_clear_link(pid, txt)
                )
                _h.addWidget(rm_btn)
            self.table.setCellWidget(r, 6, _cell)

    def _on_clear_link(self, point_id: int, current_label: str):
        """IO noktasının bağlantısını temizle (kullanıcı onayı ile)."""
        ans = QMessageBox.question(
            self, "Bağlantıyı Kaldır",
            f"Bu IO noktasının bağlantısı silinsin mi?\n\n"
            f"Mevcut: {current_label}\n\n"
            "Not: Bağlantı hedefi (kapı/port/bariyer/LAF) silinmez, "
            "yalnızca bu IO noktasından çözülür.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        try:
            self.wm.set_link(int(point_id), None, None, None)
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()

    def _open_link_dialog(self, point_id: int):
        # Aynı dialog içinde tablo değişikliklerini önce DB'ye basmadan
        # link değiştirmek istemiyoruz → önce mevcut değişiklikleri commit et
        # değil; sadece link'i ayrı yolla kaydedelim. Mevcut satır
        # düzenlemelerini bozma.
        dlg = _IoLinkDialog(self.wm, point_id, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._reload()

    def _on_add(self):
        try:
            new_id = self.wm.add_point(
                module_id=self.module_id, point_type='DI',
                channel=0, name='Yeni Nokta',
            )
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == new_id:
                self.table.selectRow(r)
                break

    def _on_delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        pid = int(self.table.item(r, 0).data(Qt.UserRole))
        label = f"{self.table.item(r,0).text()}{self.table.item(r,1).text()} {self.table.item(r,2).text()}"
        if QMessageBox.question(self, "Sil", f"'{label}' silinsin mi?") != QMessageBox.Yes:
            return
        try:
            self.wm.delete_point(pid)
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))
            return
        self._reload()

    def _on_save(self):
        errors = []
        for r in range(self.table.rowCount()):
            pid = int(self.table.item(r, 0).data(Qt.UserRole))
            try:
                pt = self.table.item(r, 0).text().strip().upper()
                if pt not in self.POINT_TYPES:
                    raise ValueError(f"Tip {self.POINT_TYPES} olmalı.")
                fields = {
                    'point_type':  pt,
                    'channel':     int(self.table.item(r, 1).text().strip() or '0'),
                    'name':        self.table.item(r, 2).text().strip(),
                    'is_visible':  1 if self.table.item(r, 3).checkState() == Qt.Checked else 0,
                    'description': self.table.item(r, 4).text().strip(),
                }
                self.wm.update_point(pid, **fields)
            except Exception as e:
                errors.append(f"Satır {r+1}: {e}")
        if errors:
            QMessageBox.warning(self, "Bazı hatalar", "\n".join(errors))
            return
        QMessageBox.information(self, "Kaydedildi", "IO noktaları güncellendi.")
        self.accept()


# ---------------------------------------------------------------------------
# IO ↔ kapı/port/LAF bağlantı dialog'u (Faz-6b)
# ---------------------------------------------------------------------------

class _IoLinkDialog(QDialog):
    """Bir IO noktasını kapıya / porta / LAF sensörüne / bariyere bağlama dialog'u."""

    LINK_LABELS = [
        (None,         "Bağlantı yok"),
        ('door',       "Kapı"),
        ('door_group', "Kapı Grubu"),
        ('port',       "Port"),
        ('laf',        "LAF Sensörü"),
        ('barrier',    "Işık Bariyeri"),
        ('estop',      "Acil Stop"),
        ('buzzer',     "Buzzer (alarm kornası)"),
    ]

    def __init__(self, wm_manager, point_id: int, parent=None):
        super().__init__(parent)
        self.wm = wm_manager
        self.point_id = int(point_id)
        self.point = self.wm.get_point(self.point_id) or {}

        pt = self.point.get('point_type', '?')
        ch = self.point.get('channel', '?')
        nm = self.point.get('name', '')
        self.setWindowTitle(f"IO Bağlantısı — {pt}{ch} '{nm}'")
        self.setMinimumWidth(420)

        self._build_ui()
        self._load_current()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        from PyQt5.QtWidgets import (QRadioButton, QButtonGroup, QComboBox,
                                     QLineEdit, QFormLayout, QGroupBox)
        root = QVBoxLayout(self)

        header = QLabel(
            f"<b>{self.point.get('point_type','')}{self.point.get('channel','')}</b> "
            f"— {self.point.get('name','')}<br>"
            f"<span style='color:#6b7280;font-size:11px;'>"
            f"Bu IO noktasını hangi fiziksel ögeye bağlamak istersiniz?"
            f"</span>"
        )
        header.setWordWrap(True)
        root.addWidget(header)

        # Radio grubu
        grp_box = QGroupBox("Bağlantı tipi")
        grp_lay = QVBoxLayout(grp_box)
        self._radio_grp = QButtonGroup(self)
        self._radios = {}
        for i, (key, label) in enumerate(self.LINK_LABELS):
            rb = QRadioButton(label)
            self._radio_grp.addButton(rb, i)
            grp_lay.addWidget(rb)
            self._radios[key] = rb
            rb.toggled.connect(self._on_type_changed)
        root.addWidget(grp_box)

        # Hedef seçimi
        form = QFormLayout()
        self.target_cb = QComboBox()
        self.target_cb.setMinimumWidth(280)
        form.addRow("Hedef:", self.target_cb)

        # Rol: hazır seçenekli, serbest yazıma da açık combo.
        # DO rolleri davranış belirler:
        #   (boş)/kilit     → batch kapı kilidi sürme
        #   machine_stop    → batch sırasında bağlı kapı açılırsa DO=1
        #   buzzer          → acil stop kornası
        #   batch_complete  → tüm seçili port testleri bitti sinyali
        self.role_cb = QComboBox()
        self.role_cb.setEditable(True)
        for _r in ('', 'kilit', 'machine_stop', 'buzzer', 'batch_complete',
                   'sensor'):
            self.role_cb.addItem(_r)
        self.role_cb.setCurrentIndex(0)
        form.addRow("Rol (opsiyonel):", self.role_cb)
        role_hint = QLabel(
            "⚠ BOŞ bırakılırsa 'kilit' sayılır: batch dışında sürekli DO=1 "
            "(kilit açık) sürülür!\n"
            "machine_stop: durdurma rölesi — bağlı kapak açılınca DO=1, "
            "hepsi kapanınca DO=0."
        )
        role_hint.setStyleSheet("color:#92400e; font-size:11px; font-weight:600;")
        role_hint.setWordWrap(True)
        form.addRow("", role_hint)
        root.addLayout(form)

        # Butonlar
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("💾 Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    # ------------------------------------------------------------- load/save
    def _load_current(self):
        cur_type = self.point.get('link_type')
        cur_id = self.point.get('link_id')
        cur_role = self.point.get('link_role') or ''

        rb = self._radios.get(cur_type) or self._radios[None]
        rb.setChecked(True)
        self.role_cb.setEditText(cur_role)
        # _on_type_changed combobox'ı doldurdu; mevcut id'yi seç
        if cur_type and cur_id is not None:
            for i in range(self.target_cb.count()):
                if self.target_cb.itemData(i) == cur_id:
                    self.target_cb.setCurrentIndex(i)
                    break

    def _selected_type(self):
        for key, rb in self._radios.items():
            if rb.isChecked():
                return key
        return None

    def _on_type_changed(self, checked: bool):
        if not checked:
            return
        link_type = self._selected_type()
        self.target_cb.clear()
        if not link_type:
            self.target_cb.setEnabled(False)
            self.role_cb.setEnabled(False)
            return
        self.target_cb.setEnabled(True)
        self.role_cb.setEnabled(True)
        try:
            targets = self.wm.list_link_targets(link_type)
        except Exception as e:
            QMessageBox.warning(self, "Hata", f"Hedef listesi alınamadı: {e}")
            return
        if not targets:
            hints = {
                'barrier':    "(Önce Ayarlar → ORAPS → Işık Bariyerleri'nden ekleyin)",
                'laf':        "(Önce Ayarlar → ORAPS → LAF Sensörleri'nden ekleyin)",
                'door_group': "(Önce ORAPS → Genel Bakış → Kapı Eşleme Modu'ndan grup oluşturun)",
                'estop':      "(Acil Stop tanımlı değil — DB seed eksik olabilir)",
            }
            self.target_cb.addItem(hints.get(link_type, "(hedef bulunamadı)"))
            self.target_cb.model().item(0).setEnabled(False)
            return
        last_group = None
        for t in targets:
            grp = t.get('group') or ''
            if grp and grp != last_group:
                # Ayraç başlığı (seçilemez)
                self.target_cb.addItem(f"— {grp} —")
                idx = self.target_cb.count() - 1
                self.target_cb.model().item(idx).setEnabled(False)
                last_group = grp
            self.target_cb.addItem(t['label'], t['id'])

    def _on_save(self):
        link_type = self._selected_type()
        if link_type is None:
            link_id = None
        else:
            data = self.target_cb.currentData()
            if data is None:
                QMessageBox.warning(self, "Eksik", "Lütfen bir hedef seçin.")
                return
            link_id = int(data)
        role = self.role_cb.currentText().strip()
        # Buzzer bağlantı tipinde rol otomatik 'buzzer' — boş bırakılırsa
        # kilit kanalı sanılmasın.
        if link_type == 'buzzer' and not role:
            role = 'buzzer'
        try:
            self.wm.set_link(self.point_id, link_type, link_id, role)
        except Exception as e:
            # PermissionDenied dahil tüm hataları kullanıcıya göster
            QMessageBox.critical(self, "Hata", str(e))
            return
        self.accept()
