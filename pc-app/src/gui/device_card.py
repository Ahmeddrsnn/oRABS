"""
Device Card Widget
Visual representation of a connected ESP-NOW slave device
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QGraphicsDropShadowEffect,
                             QDialog, QLineEdit, QDialogButtonBox, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QFont, QCursor
import random

class DismountConfirmDialog(QDialog):
    """
    Secure Confirmation Dialog for Dismount Operation for Safety.
    Requires user to enter a random 4-digit code.
    """
    def __init__(self, device_name, parent=None):
        super().__init__(parent)
        self.device_name = device_name
        self.captcha_code = str(random.randint(1000, 9999))
        
        self.setWindowTitle("KRİTİK GÜVENLİK ONAYI")
        self.setFixedSize(500, 350)
        self.setStyleSheet("background-color: #FEF2F2;") # Light red bg
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Warning Header
        warn_lbl = QLabel("⚠️ DİKKAT: DÜŞME TEHLİKESİ")
        warn_lbl.setAlignment(Qt.AlignCenter)
        warn_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #DC2626;")
        layout.addWidget(warn_lbl)
        
        # Warning Body
        body_lbl = QLabel(
            "Cihazın contasını indirmek üzeresiniz!\n"
            "Cihaz yerçekimi etkisiyle düşebilir.\n\n"
            "LÜTFEN CİHAZI TUTTUĞUNUZDAN EMİN OLUN."
        )
        body_lbl.setAlignment(Qt.AlignCenter)
        body_lbl.setStyleSheet("font-size: 13px; color: #7F1D1D; font-weight: 600;")
        layout.addWidget(body_lbl)
        
        # Captcha Info
        captcha_info = QLabel(f"İşlemi onaylamak için aşağıdaki kodu girin:\n{self.captcha_code}")
        captcha_info.setAlignment(Qt.AlignCenter)
        captcha_info.setStyleSheet("font-size: 14px; color: #111827; font-weight: bold; padding: 10px; background: white; border-radius: 6px; border: 1px dashed #DC2626;")
        layout.addWidget(captcha_info)
        
        # Input Field
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Kodu buraya yazın")
        self.code_input.setAlignment(Qt.AlignCenter)
        self.code_input.setMaxLength(4)
        self.code_input.setStyleSheet("font-size: 16px; padding: 5px; border: 2px solid #D1D5DB; border-radius: 4px;")
        layout.addWidget(self.code_input)
        
        # Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.confirm_btn = QPushButton("ONAYLA VE İNDİR")
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626; color: white; font-weight: bold; padding: 8px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #B91C1C; }
        """)
        self.confirm_btn.clicked.connect(self.validate_code)
        btn_box.addButton(self.confirm_btn, QDialogButtonBox.AcceptRole)
        btn_box.rejected.connect(self.reject)
        
        layout.addWidget(btn_box)
        
    def validate_code(self):
        if self.code_input.text().strip() == self.captcha_code:
            self.accept()
        else:
            QMessageBox.critical(self, "Hata", "Girdiğiniz güvenlik kodu YANLIŞ!")
            self.code_input.clear()
            self.code_input.setFocus()



class DeviceCard(QFrame):
    """
    Device Card widget with vertical ellipse seal indicator.
    Features WirelessGT status colors and modern design.
    """
    
    clicked = pyqtSignal(str) # Emits device name
    device_selected = pyqtSignal(str, str)  # Emits device name and MAC
    settings_clicked = pyqtSignal(str)
    rfid_clicked = pyqtSignal(str)
    rfid_clicked = pyqtSignal(str)
    register_port_clicked = pyqtSignal(str, str) # mac, rfid
    test_start_clicked = pyqtSignal(str) # Emits device name for START_TEST
    test_abort_clicked = pyqtSignal(str) # Emits device name for ABORT
    test_mount_clicked = pyqtSignal(str) # Emits device name for MOUNT
    test_dismount_clicked = pyqtSignal(str) # Emits device name for DISMOUNT
    sync_clicked = pyqtSignal(str, str) # Emits (mac, name) for manual sync

    # Conta (Seal) Status Colors
    SEAL_COLORS = {
        'inflating': '#FF8C00',   # Orange - Şişirilirken
        'active': '#00AA00',      # Green - Şişik aktif
        'passive': '#808080'      # Grey - Pasif
    }
    
    # Glove (Eldiven) Test Status Colors
    GLOVE_COLORS = {
        'testing': '#FF8C00',     # Orange - Test durumunda
        'fail': '#FF0000',        # Red - Test başarısız
        'pass': '#00AA00',        # Green - Test başarılı
        'idle': '#808080'         # Grey - Conta pasif veya test sonrası
    }
    
    def __init__(self, name, mac, auth_manager=None, parent=None):
        super().__init__(parent)
        self.name = name
        self.mac = mac
        self.auth = auth_manager
        self.is_active = False
        self.battery_level = None  # None until first real battery data received
        
        # Conta (Seal) state: 'inflating', 'active', 'passive'
        self.seal_state = 'passive'
        
        # Glove test state: 'testing', 'fail', 'pass', 'idle'
        self.glove_state = 'idle'
        
        # RF ID info
        self.rfid_tag = None
        self.rfid_port = None
        self.rfid_defined = False
        
        # Test states for temporary buttons
        self._seal_test_index = 0
        self._glove_test_index = 0
        self._rfid_test_index = 0
        
        # Device running state
        self.is_running = False
        
        # Faz-9: Ana ekran ORABS Overview için kompakt boyut.
        # Eski 200x270 → 220x210: el ikonu kalktı, ellipse küçüldü,
        # butonlar yatayda büyüdü, footer tek satıra düştü.
        self.setFixedSize(220, 210)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        
        # Shadow Effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 30))
        self.setGraphicsEffect(shadow)
        
        self.init_ui()
        self.update_style()
        
    def init_ui(self):
        layout = QVBoxLayout()
        # Faz-9: iç boşluklar daraltıldı (kompakt HMI).
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        
        # --- Header: Settings button top-right, Title below ---
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # Info (left side)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        self.name_label = QLabel(self.name)
        self.name_label.setStyleSheet("""
            font-size: 13px; 
            font-weight: 600; 
            color: #1F2937;
            font-family: 'Segoe UI', Arial;
        """)
        info_layout.addWidget(self.name_label)
        
        # ID and WiFi status row
        id_row = QHBoxLayout()
        id_row.setSpacing(6)
        
        # ID instead of MAC ID
        short_id = self.mac[-8:] if len(self.mac) >= 8 else self.mac
        self.id_label = QLabel(f"ID: {short_id}")
        self.id_label.setStyleSheet("font-size: 9px; color: #6B7280;")
        id_row.addWidget(self.id_label)
        
        # WiFi Connection Indicator (round light)
        self.wifi_indicator = QLabel("●")
        self.wifi_indicator.setFixedSize(14, 14)
        self.wifi_indicator.setAlignment(Qt.AlignCenter)
        self._update_wifi_indicator()
        id_row.addWidget(self.wifi_indicator)
        id_row.addStretch()
        
        info_layout.addLayout(id_row)
        
        header_layout.addLayout(info_layout)
        header_layout.addStretch()
        
        # Buttons Layout (Right side)
        btns_layout = QHBoxLayout()
        btns_layout.setSpacing(4)
        
        # RFID Button REMOVED as per user request (Autonomous Mode)
        # self.rfid_btn = QPushButton("📡") ...
        
        # Sync Button (Top-Right) - Manual Sync
        self.sync_btn = QPushButton("🔄")
        self.sync_btn.setFixedSize(26, 26)
        self.sync_btn.setToolTip("Manuel Senkronizasyon")
        self.sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 13px;
                font-size: 10px;
            }
            QPushButton:hover { 
                background-color: #059669;
            }
        """)
        self.sync_btn.clicked.connect(self._on_sync_click)
        btns_layout.addWidget(self.sync_btn)

        # Settings Button (Top-Right) - Settings Icon
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(26, 26)
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                border-radius: 13px;
                font-size: 14px;
            }
            QPushButton:hover { 
                background-color: #2563EB;
            }
        """)
        self.settings_btn.clicked.connect(self._on_settings_click)
        btns_layout.addWidget(self.settings_btn)
        
        header_layout.addLayout(btns_layout)
        
        layout.addLayout(header_layout)
        
        # --- Center: Kompakt seal-state göstergesi (Faz-9) ---
        # El ikonu kaldırıldı; ellipse yalnızca conta rengi (seal_state)
        # sinyali olarak küçük bir dikey oval kalıyor. update_style()
        # ellipse_container'ın border rengini yine set eder.
        self.ellipse_container = QFrame()
        self.ellipse_container.setFixedSize(28, 40)   # 78x110 → 28x40
        self.svg_icon = None   # el ikonu artık yok; referans set_rfid_info için None kalıyor

        centered_layout = QHBoxLayout()
        centered_layout.setContentsMargins(0, 0, 0, 0)
        centered_layout.addStretch()
        centered_layout.addWidget(self.ellipse_container)
        centered_layout.addStretch()
        layout.addLayout(centered_layout)
        
        # RF ID status (outside ellipse, below it)
        self.rfid_label = QLabel("")
        self.rfid_label.setAlignment(Qt.AlignCenter)
        self.rfid_label.setStyleSheet("font-size: 9px; color: #555; font-weight: 500;")
        layout.addWidget(self.rfid_label)
        
        # Registration Button (Appears for new RFID)
        self.reg_port_btn = QPushButton("💾 Port Kaydet")
        self.reg_port_btn.setFixedSize(120, 24)
        self.reg_port_btn.setStyleSheet("""
            QPushButton {
                background-color: #F59E0B;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #D97706; }
        """)
        self.reg_port_btn.setVisible(False)
        self.reg_port_btn.clicked.connect(self._on_reg_port_click)
        
        reg_btn_layout = QHBoxLayout()
        reg_btn_layout.addStretch()
        reg_btn_layout.addWidget(self.reg_port_btn)
        reg_btn_layout.addStretch()
        layout.addLayout(reg_btn_layout)
        
        layout.addStretch()
        
        # --- Device Controls (Mount, Start, Abort) ---
        self.controls_widget = QWidget()
        controls_layout = QHBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(4)
        
        # 1. MOUNT Button (Conta) — Faz-9: yatayda geniş (40x30) tıklama alanı
        self.mount_btn = QPushButton("🔒")
        self.mount_btn.setFixedSize(40, 30)
        self.mount_btn.setToolTip("Conta Şişir (Mount)")
        self.mount_btn.setStyleSheet("""
            QPushButton {
                background-color: #F59E0B;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 16px;
                padding: 0px;
            }
            QPushButton:hover { background-color: #D97706; }
            QPushButton:disabled { background-color: #E5E7EB; color: #9CA3AF; }
        """)
        self.mount_btn.clicked.connect(self._on_mount_click)
        self.mount_btn.setEnabled(False) # Default Disabled
        controls_layout.addWidget(self.mount_btn)

        # 1.5 DISMOUNT Button (Conta İndir - GÜVENLİ) — Faz-9 yatay 40x30
        self.dismount_btn = QPushButton("⏏")
        self.dismount_btn.setFixedSize(40, 30)
        self.dismount_btn.setToolTip("Conta İndir (Dismount)")
        self.dismount_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 18px;
                padding: 0px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #B91C1C; }
            QPushButton:disabled { background-color: #E5E7EB; color: #9CA3AF; }
        """)
        self.dismount_btn.clicked.connect(self._on_dismount_click)
        self.dismount_btn.setEnabled(False) 
        controls_layout.addWidget(self.dismount_btn)

        # 2. START Button (Başlat) — Faz-9 yatay 40x30
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(40, 30)
        self.play_btn.setToolTip("Testi Başlat")
        self.play_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 16px;
                padding: 0px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #E5E7EB; color: #9CA3AF; }
        """)
        self.play_btn.clicked.connect(self._on_play_click)
        self.play_btn.setEnabled(False) # Default Disabled
        controls_layout.addWidget(self.play_btn)
        
        # 3. ABORT Button (İptal) — Faz-9 yatay 40x30
        self.stop_btn = QPushButton("■")
        self.stop_btn.setFixedSize(40, 30)
        self.stop_btn.setToolTip("İptal / Havasını Al")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 16px;
                padding: 0px;
            }
            QPushButton:hover { background-color: #DC2626; }
            QPushButton:disabled { background-color: #E5E7EB; color: #9CA3AF; }
        """)
        self.stop_btn.clicked.connect(self._on_stop_click)
        self.stop_btn.setEnabled(False) # Default Disabled
        controls_layout.addWidget(self.stop_btn)
        
        layout.addWidget(self.controls_widget)
        
        # Always show these controls now, as requested to be physical buttons on card
        self.controls_widget.setVisible(True)
        
        # --- Footer: Status + Battery tek satırda (Faz-9 kompakt) ---
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(8)

        self.status_label = QLabel("Pasif")
        self.status_label.setStyleSheet("font-size: 10px; color: #4B5563; font-weight: 600;")
        footer_layout.addWidget(self.status_label)
        footer_layout.addStretch()
        self.battery_label = QLabel("🔋 --%")
        self.battery_label.setStyleSheet("font-size: 10px; color: #9CA3AF;")
        footer_layout.addWidget(self.battery_label)

        layout.addLayout(footer_layout)
        
        self.setLayout(layout)
        
    def set_rfid_info(self, rfid_tag, port_number=None, is_defined=False):
        """Set RF ID information"""
        self.rfid_tag = rfid_tag
        self.rfid_port = port_number
        self.rfid_defined = is_defined
        # Logic to enable/disable control buttons
        # Buttons are enabled ONLY if an RFID tag is present AND defined (authorized)
        has_auth = (self.rfid_tag is not None) and self.rfid_defined
        
        self.mount_btn.setEnabled(has_auth)
        self.dismount_btn.setEnabled(has_auth)
        self.play_btn.setEnabled(has_auth)
        self.stop_btn.setEnabled(has_auth)
        
        self._update_rfid_display()
        
    def _update_rfid_display(self):
        """Update RF ID label based on state"""
        if self.rfid_tag:
            if self.rfid_defined and self.rfid_port:
                self.rfid_label.setText(f"📡 RF: {self.rfid_port} ✓")
                self.rfid_label.setStyleSheet("font-size: 9px; color: #059669; font-weight: 600;")
            else:
                self.rfid_label.setText("📡 Yeni RF ID")
            # Show "Register" button only if RFID is present and NOT defined
            self.reg_port_btn.setVisible(bool(self.rfid_tag) and not self.rfid_defined)
        else:
            self.rfid_label.setText("")
            self.reg_port_btn.setVisible(False)
            self.reg_port_btn.setVisible(False)
    
    def _update_wifi_indicator(self):
        """Update WiFi connection indicator (green if connected, gray if not)"""
        if self.is_active:
            self.wifi_indicator.setStyleSheet("color: #10B981; font-size: 12px;")  # Green
            self.wifi_indicator.setToolTip("Bağlı")
        else:
            self.wifi_indicator.setStyleSheet("color: #9CA3AF; font-size: 12px;")  # Gray
            self.wifi_indicator.setToolTip("Bağlı Değil")
        
    def update_seal_state(self, state):
        """
        Update seal (conta) state
        Args:
            state: 'inflating', 'active', 'passive'
        """
        self.seal_state = state
        
        # If seal becomes passive, glove should be idle
        if state == 'passive':
            self.glove_state = 'idle'
            self.is_running = False
            
        self.update_style()
        # self._update_controls_visibility() # Removed
        
    def update_glove_state(self, state):
        """
        Update glove test state (only works if seal is active)
        Args:
            state: 'testing', 'fail', 'pass', 'idle'
        """
        # Glove state can only change if seal is active
        if self.seal_state == 'active':
            self.glove_state = state
        else:
            self.glove_state = 'idle'
        self.update_style()
        
    def update_status(self, is_active, battery=None):
        """Update device status"""
        if is_active:
            self.status_label.setText("Bagli")
        else:
            self.status_label.setText("Baglanti Yok")
            self.battery_label.setText("🔋 --%")

        if battery is not None:
            self.battery_level = battery
            self.battery_label.setText(f"🔋 {battery}%")
            if battery < 20:
                self.battery_label.setStyleSheet("color: #EF4444; font-weight: bold;")
            elif battery < 50:
                self.battery_label.setStyleSheet("color: #F59E0B; font-weight: bold;")
            else:
                self.battery_label.setStyleSheet("color: #10B981; font-weight: bold;")

        self.is_active = is_active
        self.update_style()
        self._update_wifi_indicator()

    def update_battery(self, battery):
        """Update just the battery level"""
        self.update_status(self.is_active, battery=battery)
        
    def update_style(self):
        # Get ellipse color based on seal state
        seal_color = self.SEAL_COLORS.get(self.seal_state, self.SEAL_COLORS['passive'])
        
        # Get glove icon color
        glove_color = self.GLOVE_COLORS.get(self.glove_state, self.GLOVE_COLORS['idle'])
        
        # Background color for ellipse
        bg_map = {
            'inflating': '#FFF7ED',  # Light orange
            'active': '#ECFDF5',     # Light green
            'passive': '#F3F4F6'     # Light grey
        }
        bg_color = bg_map.get(self.seal_state, '#F3F4F6')
        
        # Ellipse CSS - Faz-9 kompakt (28x40) vertical oval
        self.ellipse_container.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border: 3px solid {seal_color};
                border-radius: 14px;  /* 28/2 → yatay dairesel; dikey oval */
            }}
        """)
        
        # Card Border
        border_color = seal_color if self.is_active else "#E5E7EB"
        
        self.setStyleSheet(f"""
            DeviceCard {{
                background-color: #FFFFFF;
                border-radius: 12px;
                border: 2px solid {border_color};
            }}
            DeviceCard:hover {{
                background-color: #F9FAFB;
                border: 2px solid {seal_color};
            }}
        """)
        
        # Update status label color
        self.status_label.setStyleSheet(f"font-size: 10px; color: {seal_color}; font-weight: 600;")
        
        # Explicitly set ToolTip style for this widget's context
        # This overrides potential theme conflicts for buttons inside this card
        self.setStyleSheet(self.styleSheet() + """
            QToolTip {
                background-color: #F8F9FA;
                color: #000000;
                border: 1px solid #767676;
                font-size: 12px;
            }
        """)
        
    def _on_play_click(self):
        """Handle play button click"""
        self.test_start_clicked.emit(self.name)
            
    def _on_stop_click(self):
        """Handle stop button click"""
        self.test_abort_clicked.emit(self.name)

    def _on_mount_click(self):
        """Handle mount button click"""
        self.test_mount_clicked.emit(self.name)

    def _on_dismount_click(self):
        """Handle dismount button with security check"""
        dialog = DismountConfirmDialog(self.name, self)
        if dialog.exec_() == QDialog.Accepted:
            self.test_dismount_clicked.emit(self.name)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.name)
            self.device_selected.emit(self.name, self.mac)
        super().mousePressEvent(event)
        
    def _on_settings_click(self):
        self.settings_clicked.emit(self.name)

    def _on_sync_click(self):
        self.sync_clicked.emit(self.mac, self.name)

    def _on_rfid_click(self):
        self.rfid_clicked.emit(self.name)
    
    def _on_reg_port_click(self):
        if self.rfid_tag:
            self.register_port_clicked.emit(self.mac, self.rfid_tag)
    
    # --- Test Methods (for external test buttons) ---
    def cycle_seal_state(self):
        """Cycle through seal states for testing"""
        states = ['passive', 'inflating', 'active']
        self._seal_test_index = (self._seal_test_index + 1) % len(states)
        self.update_seal_state(states[self._seal_test_index])
        
    def cycle_glove_state(self):
        """Cycle through glove states for testing (only if seal active)"""
        if self.seal_state != 'active':
            return False  # Can only test glove when seal is active
            
        states = ['idle', 'testing', 'pass', 'fail']
        self._glove_test_index = (self._glove_test_index + 1) % len(states)
        self.update_glove_state(states[self._glove_test_index])
        return True
    
    def cycle_rfid_state(self):
        """Cycle through RF ID states for testing"""
        states = [
            (None, None, False),           # No RF ID
            ("ABC123", None, False),       # New undefined RF ID
            ("DEF456", "Port 01", True),   # Defined RF ID
            ("GHI789", "Port 02", True),   # Another defined RF ID
        ]
        self._rfid_test_index = (self._rfid_test_index + 1) % len(states)
        rfid, port, defined = states[self._rfid_test_index]
        self.set_rfid_info(rfid, port, defined)
