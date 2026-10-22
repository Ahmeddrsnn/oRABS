"""
Device Settings Dialog - Minimalist Design with Extended Calibration
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, 
                             QDialogButtonBox, QLabel, QDoubleSpinBox, QWidget,
                             QHBoxLayout, QGroupBox, QPushButton, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer

class DeviceSettingsDialog(QDialog):
    """
    Dialog for configuring device settings.
    Minimalist design with clean typography and spacing.
    """
    zero_requested = pyqtSignal(str) # Emits type ("PRESSURE" or "SEAL")
    
    def __init__(self, device_data, auth_manager=None, parent=None, calib_data=None):
        super().__init__(parent)
        self.device_data = device_data
        self.auth = auth_manager
        self.setWindowTitle("Cihaz Ayarları")
        self.setMinimumWidth(500)
        
        self.new_name = None
        self.seal_pressure_set = None
        self.pressure_offset = None
        self.pressure_multiplier = None
        self.seal_offset = None
        self.seal_multiplier = None
        
        # --- Calib data tracking ---
        self._calib_received = False          # GET_CALIB cevabı geldi mi?
        self._initial_calib = {}              # Cihazdan gelen orijinal değerler
        self._last_raw_pressure = None        # Son ham basınç değeri (live data'dan)
        
        self.init_ui()
        self.load_data()
        self.apply_styles()
        
        # Kalibrasyon verisi constructor'da geldiyse hemen doldur
        if calib_data is not None:
            self.update_calibration_data(calib_data)
        
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # --- Header Section ---
        header_lbl = QLabel("Cihaz Düzenleme")
        header_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #1F2937;")
        layout.addWidget(header_lbl)
        
        # --- Info Section ---
        form_layout = QFormLayout()
        form_layout.setSpacing(15)
        
        # MAC Address (ID)
        self.mac_label = QLabel(self.device_data.get('mac', 'N/A'))
        self.mac_label.setStyleSheet("color: #6B7280; font-family: monospace;")
        form_layout.addRow(QLabel("ID:"), self.mac_label)
        
        # Device Name - Editable by Admin or Supervisor
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Cihaz adı giriniz...")
        
        # Check if user has Supervisor or higher role
        can_edit_name = self.auth.has_permission('Supervisor') if self.auth else True
        self.name_input.setEnabled(can_edit_name)
        if not can_edit_name:
            self.name_input.setToolTip("Cihaz adı sadece Admin veya Supervisor tarafından değiştirilebilir")
            
        form_layout.addRow(QLabel("Cihaz Adı:"), self.name_input)
        
        layout.addLayout(form_layout)
        
        # Divider
        self._add_divider(layout)
        
        # --- Seal Pressure Set Section ---
        seal_pressure_group = QGroupBox("Conta Basınç Ayarı")
        seal_pressure_layout = QFormLayout()
        seal_pressure_layout.setSpacing(12)
        
        self.seal_pressure_spin = QDoubleSpinBox()
        self.seal_pressure_spin.setRange(0, 2000.0)
        self.seal_pressure_spin.setDecimals(1)
        self.seal_pressure_spin.setSuffix(" hPa")
        self.seal_pressure_spin.setButtonSymbols(QDoubleSpinBox.PlusMinus)
        seal_pressure_layout.addRow(QLabel("Conta Basınç Set:"), self.seal_pressure_spin)
        
        seal_pressure_group.setLayout(seal_pressure_layout)
        layout.addWidget(seal_pressure_group)
        # Conta Basınç — şimdilik gizli ve devre dışı
        seal_pressure_group.setVisible(False)
        seal_pressure_group.setEnabled(False)
        self.seal_pressure_spin.setEnabled(False)
        
        # --- Calibration Section ---
        calib_group = QGroupBox("Kalibrasyon")
        calib_layout = QVBoxLayout()
        calib_layout.setSpacing(15)
        
        
        # Seal (Conta) Calibration (Moved UP) — şimdilik gizli
        seal_title = QLabel("Conta Kalibrasyon")
        seal_title.setStyleSheet("font-weight: 600; color: #374151;")
        calib_layout.addWidget(seal_title)
        seal_title.setVisible(False)
        
        # Seal Offset
        seal_offset_row = QHBoxLayout()
        seal_offset_row.addWidget(QLabel("Ofset:"))
        self.seal_offset_spin = QDoubleSpinBox()
        self.seal_offset_spin.setRange(-100000.0, 100000.0)
        self.seal_offset_spin.setDecimals(1)
        self.seal_offset_spin.setSuffix(" hPa")
        self.seal_offset_spin.setButtonSymbols(QDoubleSpinBox.PlusMinus)
        self.seal_offset_spin.setMinimumWidth(120)
        seal_offset_row.addWidget(self.seal_offset_spin)
        self._seal_offset_hint = QLabel("-20 - 300 hPa")
        seal_offset_row.addWidget(self._seal_offset_hint)
        seal_offset_row.addStretch()
        calib_layout.addLayout(seal_offset_row)
        
        # Seal Multiplier
        seal_mult_row = QHBoxLayout()
        self._seal_mult_label = QLabel("Çarpan:")
        seal_mult_row.addWidget(self._seal_mult_label)
        self.seal_mult_spin = QDoubleSpinBox()
        self.seal_mult_spin.setRange(-200.0, 200.0)
        self.seal_mult_spin.setDecimals(0)
        self.seal_mult_spin.setSuffix(" %")
        self.seal_mult_spin.setValue(100.0)
        self.seal_mult_spin.setButtonSymbols(QDoubleSpinBox.PlusMinus)
        self.seal_mult_spin.setMinimumWidth(120)
        seal_mult_row.addWidget(self.seal_mult_spin)
        seal_mult_row.addStretch()
        calib_layout.addLayout(seal_mult_row)

        # Conta kalibrasyon satırlarını gizle ve devre dışı bırak
        for w in [self.seal_offset_spin, self._seal_offset_hint,
                  self._seal_mult_label, self.seal_mult_spin]:
            w.setVisible(False)
            w.setEnabled(False)
        # Seal offset row label
        seal_offset_row.itemAt(0).widget().setVisible(False)

        # Divider in calibration
        self._seal_divider = QWidget()
        self._seal_divider.setFixedHeight(1)
        self._seal_divider.setStyleSheet("background-color: #E5E7EB;")
        calib_layout.addWidget(self._seal_divider)
        self._seal_divider.setVisible(False)

        # Pressure Calibration (Now Second)
        pressure_title = QLabel("Basınç Kalibrasyon")
        pressure_title.setStyleSheet("font-weight: 600; color: #374151;")
        calib_layout.addWidget(pressure_title)
        
        # Live Pressure Display
        live_p_layout = QHBoxLayout()
        live_p_layout.setSpacing(20)
        
        # Calibrated
        self.lbl_cal_pressure = QLabel("Basınç: -- Pa")
        self.lbl_cal_pressure.setStyleSheet("font-size: 14px; font-weight: bold; color: #2563EB;")
        live_p_layout.addWidget(self.lbl_cal_pressure)
        
        live_p_layout.addStretch()
        calib_layout.addLayout(live_p_layout)
        
        # Pressure Offset (hidden — internal tracking only)
        self.pressure_offset_spin = QDoubleSpinBox()
        self.pressure_offset_spin.setRange(-200000.0, 200000.0)
        self.pressure_offset_spin.setDecimals(0)
        self.pressure_offset_spin.setSuffix(" Pa")
        self.pressure_offset_spin.setVisible(False)
        
        # Pressure Multiplier + Sıfırla Button
        pressure_mult_row = QHBoxLayout()
        pressure_mult_row.addWidget(QLabel("Çarpan:"))
        self.pressure_mult_spin = QDoubleSpinBox()
        self.pressure_mult_spin.setRange(-200.0, 200.0)
        self.pressure_mult_spin.setDecimals(1)
        self.pressure_mult_spin.setSingleStep(0.1)
        self.pressure_mult_spin.setSuffix("%")
        self.pressure_mult_spin.setValue(100.0)
        self.pressure_mult_spin.setButtonSymbols(QDoubleSpinBox.PlusMinus)
        self.pressure_mult_spin.setMinimumWidth(120)
        pressure_mult_row.addWidget(self.pressure_mult_spin)
        
        # Zero Button (same size as multiplier spinbox)
        self.zero_btn = QPushButton("Sıfırla")
        self.zero_btn.setCursor(Qt.PointingHandCursor)
        self.zero_btn.setToolTip("Basıncı anında 0'a sıfırlar (cihaza gönderir)")
        self.zero_btn.setStyleSheet("background-color: #E0E7FF; color: #4338CA; border: 1px solid #C7D2FE; padding: 4px 8px; font-size: 11px; font-weight: bold;")
        self.zero_btn.setMinimumWidth(120)
        self.zero_btn.setMinimumHeight(self.pressure_mult_spin.sizeHint().height())
        self.zero_btn.clicked.connect(self._on_zero_pressure)
        pressure_mult_row.addWidget(self.zero_btn)
        
        pressure_mult_row.addStretch()
        calib_layout.addLayout(pressure_mult_row)
        
        calib_group.setLayout(calib_layout)
        layout.addWidget(calib_group)
        
        layout.addStretch()
        
        # --- Calib status ---
        self._calib_status_lbl = QLabel("")
        self._calib_status_lbl.setStyleSheet("color: #059669; font-size: 12px;")
        layout.addWidget(self._calib_status_lbl)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_settings)
        buttons.rejected.connect(self.reject)
        
        self._save_btn = buttons.button(QDialogButtonBox.Save)
        self._save_btn.setText("Kaydet")
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.setEnabled(False)  # Calib verisi gelene kadar kapalı
        
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        cancel_btn.setText("İptal")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        
        layout.addWidget(buttons)
        
        self.setLayout(layout)
        
    def _add_divider(self, layout, margin=0):
        """Add a horizontal divider line"""
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #E5E7EB;")
        if margin > 0:
            line.setContentsMargins(0, margin, 0, margin)
        layout.addWidget(line)
        
    def apply_styles(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #FFFFFF;
            }
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                color: #4B5563;
            }
            QLineEdit, QDoubleSpinBox {
                padding: 8px;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                background-color: #F9FAFB;
                font-size: 13px;
                color: #1F2937;
            }
            QLineEdit:focus, QDoubleSpinBox:focus {
                border: 1px solid #3B82F6;
                background-color: #FFFFFF;
            }
            QLineEdit:disabled {
                background-color: #E5E7EB;
                color: #9CA3AF;
            }
            QGroupBox {
                font-weight: 600;
                color: #374151;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                margin-top: 1em;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton[text="Kaydet"] {
                background-color: #3B82F6;
                color: white;
                border: none;
            }
            QPushButton[text="Kaydet"]:hover {
                background-color: #2563EB;
            }
            QPushButton[text="İptal"] {
                background-color: #FFFFFF;
                border: 1px solid #D1D5DB;
                color: #374151;
            }
            QPushButton[text="İptal"]:hover {
                background-color: #F3F4F6;
            }
        """)
        
    def load_data(self):
        """Load current values into fields"""
        self.name_input.setText(self.device_data.get('name', ''))
        params = self.device_data.get('params', {})
        
        # Seal pressure set
        self.seal_pressure_spin.setValue(float(params.get('SEAL_PRESSURE_SET', 0.0)))
        
        # Pressure calibration
        self.pressure_offset_spin.setValue(float(params.get('PRESSURE_OFFSET', 0.0)))
        # float faktör → yüzde: 1.0 * 100.0 = %100.0
        p_mult = float(params.get('PRESSURE_MULT', 1.0)) * 100.0
        self.pressure_mult_spin.setValue(p_mult)
        
        # Seal calibration  
        self.seal_offset_spin.setValue(float(params.get('SEAL_OFFSET', 0.0)))
        s_mult = float(params.get('SEAL_MULT', 1.0)) * 100.0
        self.seal_mult_spin.setValue(s_mult)
        
    def save_settings(self):
        """Collect data and accept — only mark changed calib sections"""
        # Sanitize name: replace spaces with underscores to avoid parsing issues
        raw_name = self.name_input.text().strip()
        self.new_name = raw_name.replace(" ", "_")
        
        # --- Kalibrasyon verisi hiç gelmediyse, kalibrasyon gönderme ---
        if not self._calib_received:
            self.calib_glove = None
            self.calib_gasket = None
            self.seal_pressure_set = None
            self.accept()
            return
        
        # --- Dirty detection: compare current spinbox values with initial from device ---
        _eps = 0.01  # float comparison tolerance
        
        # Glove (Pressure) Params — only set if user actually changed them
        p_off_now = self.pressure_offset_spin.value()
        p_mul_now = self.pressure_mult_spin.value()
        p_off_init = self._initial_calib.get('p_off', 0.0)
        p_mul_init = self._initial_calib.get('p_mul', 100.0)
        
        if abs(p_off_now - p_off_init) > _eps or abs(p_mul_now - p_mul_init) > _eps:
            self.calib_glove = {'offset': p_off_now, 'multiplier': p_mul_now}
        else:
            self.calib_glove = None  # Değişmedi → gönderme
        
        # Gasket (Seal) Params — only set if user actually changed them
        s_off_now = self.seal_offset_spin.value()
        s_mul_now = self.seal_mult_spin.value()
        s_off_init = self._initial_calib.get('s_off', 0.0)
        s_mul_init = self._initial_calib.get('s_mul', 100.0)
        
        if abs(s_off_now - s_off_init) > _eps or abs(s_mul_now - s_mul_init) > _eps:
            self.calib_gasket = {'offset': s_off_now, 'multiplier': s_mul_now}
        else:
            self.calib_gasket = None  # Değişmedi → gönderme
        
        # Seal Pressure Set — only if changed
        c_set_now = self.seal_pressure_spin.value()
        c_set_init = self._initial_calib.get('c_set', 0.0)
        if abs(c_set_now - c_set_init) > _eps:
            self.seal_pressure_set = c_set_now
        else:
            self.seal_pressure_set = None  # Değişmedi → gönderme
        
        self.accept()

    def update_live_data(self, calibrated, raw):
        """Update live pressure display"""
        try:
            self.lbl_cal_pressure.setText(f"Basınç: {calibrated} Pa")
            if raw is not None:
                self._last_raw_pressure = raw
                
                # Ham değer 0 ise kalibrasyon alanlarını kilitle
                raw_val = float(raw)
                calib_locked = (raw_val == 0.0)
                self.pressure_offset_spin.setEnabled(not calib_locked)
                self.pressure_mult_spin.setEnabled(not calib_locked)
                self.seal_offset_spin.setEnabled(not calib_locked)
                self.seal_mult_spin.setEnabled(not calib_locked)
                self.seal_pressure_spin.setEnabled(not calib_locked)
                self.zero_btn.setEnabled(not calib_locked)
                if calib_locked:
                    self._calib_status_lbl.setText("⚠ Cihazda kullanıcı girişi yok — kalibrasyon değiştirilemez")
                    self._calib_status_lbl.setStyleSheet("color: #DC2626; font-size: 12px; font-weight: bold;")
                elif self._calib_received:
                    self._calib_status_lbl.setText("✓ Kalibrasyon verisi alındı")
                    self._calib_status_lbl.setStyleSheet("color: #059669; font-size: 12px;")
        except:
            pass

    def _on_zero_pressure(self):
        """Sıfırla: ESP'ye ZERO komutu gönder — anında basıncı 0'a sıfırlar."""
        self.zero_requested.emit("PRESSURE")



    def update_calibration_data(self, data):
        """Called when GET_CALIB response arrives or ACK_ZERO"""
        try:
            # data: dict with keys like 'p_off', 'p_mul', 's_off', 's_mul', 'new_offset'
            is_full_calib = 'p_off' in data and 's_off' in data  # CALIB_DATA response

            if 'p_off' in data:
                self.pressure_offset_spin.setValue(float(data['p_off']))
            
            if 'p_mul' in data:
                # float faktör → GUI %100.0 formatı: 1.0 * 100.0 = 100.0
                val = float(data['p_mul']) * 100.0
                self.pressure_mult_spin.setValue(val)
                
            if 's_off' in data:
                self.seal_offset_spin.setValue(float(data['s_off']))
                
            if 's_mul' in data:
                val = float(data['s_mul']) * 100.0
                self.seal_mult_spin.setValue(val)
                
            if 'new_offset' in data:  # From ACK_ZERO
                self.pressure_offset_spin.setValue(float(data['new_offset']))
                # Update initial tracking too so dirty detection stays correct
                self._initial_calib['p_off'] = float(data['new_offset'])
            
            if 'c_set' in data:  # Conta Pressure Set
                self.seal_pressure_spin.setValue(float(data['c_set']))

            # --- İlk CALIB_DATA geldiğinde: initial değerleri kaydet, butonu aç ---
            if is_full_calib and not self._calib_received:
                self._calib_received = True
                self._initial_calib = {
                    'p_off': self.pressure_offset_spin.value(),
                    'p_mul': self.pressure_mult_spin.value(),
                    's_off': self.seal_offset_spin.value(),
                    's_mul': self.seal_mult_spin.value(),
                    'c_set': self.seal_pressure_spin.value(),
                }
                self._save_btn.setEnabled(True)
                self._calib_status_lbl.setText("✓ Kalibrasyon verisi alındı")
                self._calib_status_lbl.setStyleSheet("color: #059669; font-size: 12px;")
                
        except Exception as e:
            print(f"Cal UI Update Error: {e}")
