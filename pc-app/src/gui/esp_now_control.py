"""
ESP-NOW Master Control Panel
Interface for controlling slave devices and managing parameters
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox,
                             QMessageBox, QListWidget, QListWidgetItem, QInputDialog, QCheckBox,
                             QScrollArea, QGridLayout, QDialog, QSplitter)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QThread, QSettings
from PyQt5.QtGui import QFont
from datetime import datetime
import time
import json
import re
import os
import threading  # For message buffer lock
import collections
import zlib
from utils.app_logger import get_logger
from gui.device_card import DeviceCard
from gui.device_settings_dialog import DeviceSettingsDialog
from gui.device_detail_dialog import DeviceDetailDialog
from gui.rfid_management_dialog import RFIDManagementDialog
from gui.port_registration_dialog import PortRegistrationDialog

_logger = get_logger("esp_now_control")


def encode_port(left: int, right: int) -> int:
    """Port numarasını encode et: 'sol/sag' -> (sol << 8) | sag"""
    return (left << 8) | right


def decode_port(encoded: int) -> tuple:
    """Encode'lu port numarasını decode et: int -> (sol, sag)"""
    return (encoded >> 8, encoded & 0xFF)


def port_display(encoded: int) -> str:
    """Encode'lu port numarasını gösterim stringine çevir: int -> 'sol/sag'"""
    if not encoded or encoded == 0:
        return "0"
    if encoded < 256:
        return str(encoded)
    left, right = decode_port(encoded)
    return f"{left}/{right}"


def port_from_db_name(name: str) -> int:
    """DB port adından (ör. 'Port 3/5') encode'lu port numarası çıkar"""
    m = re.search(r'(\d+)\s*/\s*(\d+)', name)
    if m:
        return encode_port(int(m.group(1)), int(m.group(2)))
    # Eski format uyumluluğu: 'Port 01' → (0, 1) olarak encode
    m2 = re.search(r'\d+', name)
    if m2:
        return int(m2.group())
    return 0


class ConnectionWorker(QThread):
    """Background worker for ESP32 Connection to prevent UI freeze"""
    finished = pyqtSignal(bool, str, str) # success, message, port_name

    def __init__(self, esp32, port=None):
        super().__init__()
        self.esp32 = esp32
        self.port = port
        self.is_running = True

    def run(self):
        try:
            if self.port:
                # Manual Connect or Smart Connect
                success, msg = self.esp32.connect(self.port, test_mode=True)
                self.finished.emit(success, msg, self.port)
            else:
                # Auto Scan
                success, msg = self.esp32.scan_and_connect()
                self.finished.emit(success, msg, self.esp32.port_name if success else "")
        except Exception as e:
            self.finished.emit(False, str(e), self.port if self.port else "")

class ESPNOWMasterPanel(QWidget):
    """Widget for ESP-NOW Master control and slave management"""
    
    command_sent = pyqtSignal(str, str)  # Emits command and response
    slaves_updated = pyqtSignal(list)  # Signal for slave list updates
    raw_data_received = pyqtSignal(str)  # Signal for raw data
    log_message = pyqtSignal(str, str, bool) # Signal for thread-safe logging
    traffic_message = pyqtSignal(str, str) # Signal for live traffic logging
    # ORAPS 3D viewer'da ilgili glove port mesh'ini yeşil/nötr yakmak için.
    # (device_name, rfid_tag, is_active) — is_active=False → RFID uzaklaştırıldı.
    rfid_state_changed = pyqtSignal(str, str, bool)
    
    def __init__(self, esp32_comm, database, auth_manager, audit_manager, parent=None):
        super().__init__(parent)
        self.esp32 = esp32_comm
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        
        self.device_cards = {} # Map name -> DeviceCard widget
        self._known_macs = {} # Map mac -> name (MAC-based uniqueness for cards)
        self._stream_discovered = set()  # MACs already processed for post-connection actions
        self._INVALID_NAMES = {"", "NewDevice", "TestAparati"}  # Geçersiz/varsayılan cihaz adları
        self.selected_device = None
        self.last_rfid_state = {} # Map name -> last RFID tag string
        self._device_last_seen = {}  # Map device_name -> time.time() (heartbeat tracking)
        self._sync_in_progress = False  # broadcast/sync sırasında heartbeat timeout devre dışı

        # ── 2-Fazlı Batch Senkronizasyon Sistemi ──
        # Faz 1: Tüm cihazlara PIN sync → Faz 2: Tüm cihazlara RFID sync
        self._sync_queue = collections.deque()  # bekleyen (mac, name) ikilileri
        self._sync_active_mac = None  # şu an senkronize edilen MAC
        self._sync_phase = None       # None | 'COLLECTING' | 'PIN' | 'RFID' | 'POST'
        self._sync_batch = []         # aktif batch: [(mac, name), ...]
        self._sync_batch_index = 0    # batch içindeki mevcut cihaz indeksi
        self._flash_pending_devices = set()  # flash_count>0 olan cihazlar (POST fazında history tetiklenecek)

        # 3sn toplama penceresi — cihazlar keşfedildikçe batch'e eklenir
        self._sync_collect_timer = QTimer()
        self._sync_collect_timer.setSingleShot(True)
        self._sync_collect_timer.timeout.connect(self._start_sync_batch)

        # 2sn CRC timeout — CRC yanıtı gelmezse log + sonraki cihaza geç
        self._crc_timeout_timer = QTimer()
        self._crc_timeout_timer.setSingleShot(True)
        self._crc_timeout_timer.timeout.connect(self._on_crc_timeout)

        # Chunk tabanlı RFID sync sistemi
        self._rfid_sync_retries = {}    # mac → toplam retry sayısı (max 3)
        self._rfid_sync_timer = {}      # mac → QTimer (SYNC_OK/FAIL timeout)
        self._pc_rfid_payload_crc = 0   # PC DB'den hesaplanan payload CRC32 (0 = henüz hesaplanmadı)
        self._pc_user_pin_crc = 0          # PC DB'den hesaplanan user PIN CRC32 (0 = henüz hesaplanmadı)
        self._pin_sync_retries = {}        # mac → retry sayısı (max 3, sonsuz döngü önleme)
        self._awaiting_pin_verify = False  # PIN push sonrası doğrulama CRC bekleniyor mu

        # Heartbeat timer — 1 saniyede bir cihaz zaman aşımı kontrolü
        self._heartbeat_timer = QTimer()
        self._heartbeat_timer.timeout.connect(self._check_device_heartbeats)
        # Timer bağlantı kurulduğunda başlatılacak
        
        # Connect signal
        self.slaves_updated.connect(self.update_slave_grid)
        self.raw_data_received.connect(self.on_rx_data)
        self.command_sent.connect(self.on_tx_data)
        self.log_message.connect(self.append_log_html)
        self.traffic_message.connect(self.append_traffic_html)

        
        # Set callback
        self.esp32.set_slave_list_callback(self.on_slave_list_received)
        self.esp32.set_raw_data_callback(self.on_raw_data_received)
        self.esp32.set_sent_data_callback(self.on_sent_data_received)
        
        self.init_ui()
        self.apply_global_styles()
        
        # HIGH-PERFORMANCE MESSAGE BUFFERING
        # Collect messages in buffer, update UI in batches to prevent blocking
        self.stream_message_buffer = []
        self.buffer_lock = threading.Lock()
        
        self.current_settings_dialog = None # Reference to active settings dialog
        self.current_settings_target = None # Name of target device for settings
        self.current_detail_dialog = None # Reference to active detail dialog
        self.current_detail_target = None # Name of target device for detail view
        # active_test_records removed — all test records now come from ESP32 flash via THP sync
        
        # Batch update timer - process buffer every 100ms
        self.batch_timer = QTimer()
        self.batch_timer.timeout.connect(self._process_message_buffer)
        self.batch_timer.start(100)  # 100ms = 10 updates/sec max
        
        
        # Buffer for parsing slave sync data
        self.slave_sync_buffers = {}
        
        # Buffer for offline test history sync
        self.offline_sync_buffers = {} # Map device_name -> {test_id: {meta: {}, pressure: []}}
        self._history_timeout_timers = {}  # Map device_name -> QTimer (15s watchdog)
        self._history_timeout_retries = {}  # Map device_name -> int (retry count)
        
        # Persistent Graph Buffers (Time/Pressure history)
        self.device_buffers = {} 
        self.sync_timers = {} # Map sender_name -> QTimer
        
        # Phase 4: Smart Port Memory
        self.settings = QSettings("GLT", "GloveTestSystem")
        self.connection_worker = None
        
        # Stale record cleanup removed — PC no longer creates RUNNING records

    def _process_slave_sync(self, sender_name):
        """Execute Strict Sync Logic for a slave (Batch Processed)"""
        try:
            _target = self._resolve_target(sender_name)
            if sender_name not in self.slave_sync_buffers: return
            
            slave_items = self.slave_sync_buffers.get(sender_name, [])
            self.log(f"Sync Verisi İşleniyor: {sender_name} ({len(slave_items)} kayıt)", color="blue")
            
            all_db_ports = self.db.get_all_ports()
            # Convert DB list to Dict for fast lookup: {rfid_hex: {port:_, recipe_id:_, name:_}}
            # Normalize DB RFIDs to lower case just in case
            db_map = {}
            for p in all_db_ports:
                r = p.get('rfid_tag')
                if r and r != "-" and r != "0x00000000":
                    r_norm = r.lower().replace("0x", "0x") # Ensure 0x prefix is consistent lower
                    db_map[r_norm] = p

            slave_map = {item['rfid'].lower(): item for item in slave_items} # Normalize slave RFIDs to lower case
            
            action_taken = False
            
            # Initialize retry counter for this specific slave if not exists
            if not hasattr(self, 'sync_retries'):
                self.sync_retries = {}
            if sender_name not in self.sync_retries:
                self.sync_retries[sender_name] = 0

            self.log(f"Sync Verisi İşleniyor: {sender_name} ({len(slave_map)} kayıt)", color="blue")
            
            # A. ORPHANS (In Slave, Not in DB)
            for slave_rfid, slave_data in slave_map.items():
                if slave_rfid.lower() not in db_map:
                    self.log(f"Fazlalık Tespit Edildi: {slave_rfid} (Siliniyor...)", "red")
                    del_cmd = f'{{"cmd":"DELETE_TAG", "rfid":"{slave_rfid}"}}'
                    self.esp32.send_command(f"send {_target} {del_cmd}")
                    action_taken = True
                    
            # B. Check for Mismatches
            for slave_rfid, slave_item in slave_map.items():
                if slave_rfid in db_map:
                    db_port = db_map[slave_rfid]
                    db_port_num = port_from_db_name(db_port.get('name', ''))
                    slave_port_num = slave_item.get('port', 0)
                    
                    # Get DB Recipe Name
                    db_recipe_id = db_port.get('recipe_id')
                    db_recipe_name = "Varsayilan"
                    if db_recipe_id:
                        try:
                            rec = self.db.get_recipe(db_recipe_id)
                            if rec:
                                db_recipe_name = rec.get('name', 'Varsayilan')
                        except Exception as e:
                            _logger.error("Recipe lookup error for ID %s: %s", db_recipe_id, e)
                            db_recipe_name = "Varsayilan"
                    
                    slave_recipe_name = slave_item.get('recipe_name', 'Varsayilan')

                    # Check Port OR Recipe Mismatch
                    if (db_port_num != slave_port_num and db_port_num != 0) or (db_recipe_name != slave_recipe_name):
                        reason = "Port" if db_port_num != slave_port_num else "Reçete"
                        log_msg = f"{reason} Uyuşmazlığı: {slave_rfid} (PC[{port_display(db_port_num)}/{db_recipe_name}] != Slave[{port_display(slave_port_num)}/{slave_recipe_name}]) -> Düzeltiliyor"
                        
                        self.log(log_msg, "orange")
                        self._push_config_to_slave(sender_name, slave_rfid, db_port_num, db_port.get('recipe_id'))
                        action_taken = True

            # C. Check for duplicate ports
            port_counts = {}
            for item in slave_items:
                p = item.get('port', 0)
                if p > 0:
                    if p not in port_counts: port_counts[p] = []
                    port_counts[p].append(item)
                    
            for p, items_on_port in port_counts.items():
                if len(items_on_port) > 1:
                    self.log(f"Çakışma: Port {p} üzerinde {len(items_on_port)} tag var! Temizleniyor...", "red")
                    
                    for item in items_on_port:
                        conflict_rfid = item.get('rfid')
                        del_cmd = f'{{"cmd":"DELETE_TAG", "rfid":"{conflict_rfid}"}}'
                        self.esp32.send_command(f"send {_target} {del_cmd}")
                        if conflict_rfid in slave_map:
                            del slave_map[conflict_rfid]
                        action_taken = True

                    target_name = f"Port {p:02d}"
                    correct_db = None
                    for db_p in all_db_ports:
                        if db_p.get('name') == target_name: 
                            correct_db = db_p
                            break
                    
                    if correct_db:
                        self.log(f"Çakışma çözümü için doğru tag geri yüklenecek: {correct_db.get('rfid_tag')}", "blue")

            # D. MISSING TAGS (Restore)
            count_restored = 0
            max_slave_capacity = 50  # ESP32 max_tags limiti
            for db_rfid, db_item in db_map.items():
                if db_rfid not in slave_map:
                    # Slave kapasitesi doluysa push etme (sonsuz loop önleme)
                    if len(slave_items) + count_restored >= max_slave_capacity:
                        self.log(f"ESP32 kapasitesi dolu ({max_slave_capacity}). Kalan taglar atlanıyor.", "orange")
                        break
                    db_port_num = port_from_db_name(db_item.get('name', ''))
                        
                    if db_port_num > 0:
                        self.log(f"Eksik Veri Yükleniyor: {db_rfid} -> Port {port_display(db_port_num)}", "blue")
                        self._push_config_to_slave(sender_name, db_rfid, db_port_num, db_item.get('recipe_id'))
                        count_restored += 1
            
            if count_restored > 0:
                self.log(f"Geri Yükleme Tamamlandı: {count_restored} adet kayıt gönderildi.", "green")
                action_taken = True

            # VERIFICATION STEP
            if action_taken:
                self.sync_retries[sender_name] += 1
                if self.sync_retries[sender_name] > 1:
                    self.log(f"Sync Düzeltme Tamamlandı: {sender_name} (max 1 retry)", "#D97706")
                    self.sync_retries[sender_name] = 0
                    # Kuyruk entegrasyonu: bu cihazın sync'ini bitir
                    sender_mac = None
                    for _m, _n in self._known_macs.items():
                        if _n == sender_name:
                            sender_mac = _m
                            break
                    if sender_mac:
                        self._finish_device_sync(sender_mac)
                else:
                    # Tek sefer doğrulama: 1000ms sonra tekrar sorgula
                    self.log(f"İşlem yapıldı. 1sn sonra doğrulanıyor... ({sender_name})", color="#8B5CF6")
                    QTimer.singleShot(1000, lambda t=_target: self.esp32.send_command(f'send {t} {{"cmd":"GET_ALL_RFIDS"}}'))
            else:
                self.sync_retries[sender_name] = 0 # Success reset
                self.log(f"Senkronizasyon Tamamlandı: Fark bulunamadı. ({sender_name})", color="green")
                self._end_sync_guard()
                # Kuyruk entegrasyonu: bu cihazın sync'ini bitir
                sender_mac = None
                for _m, _n in self._known_macs.items():
                    if _n == sender_name:
                        sender_mac = _m
                        break
                if sender_mac:
                    self._finish_device_sync(sender_mac)
                    
            # Clear buffer and timer
            self.slave_sync_buffers[sender_name] = []
            if sender_name in self.sync_timers:
                self.sync_timers[sender_name].stop()
                del self.sync_timers[sender_name]
        except Exception as e:
            _logger.error("_process_slave_sync error for %s: %s", sender_name, e, exc_info=True)
            self.log(f"Sync Hatası: {sender_name} - {e}", "red")

    def apply_global_styles(self):
        self.setStyleSheet("""
            QWidget {
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px;
                color: #374151;
            }
            QGroupBox {
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                margin-top: 1.5em; /* leave space for the title */
                background-color: #FFFFFF;
            } 
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                font-weight: bold;
                color: #1F2937;
            }
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 6px 12px;
                color: #4B5563;
            }
            QPushButton:hover {
                background-color: #F3F4F6;
                border-color: #9CA3AF;
            }
            QPushButton:pressed {
                background-color: #E5E7EB;
                border-color: #6B7280;
            }
            QLineEdit, QComboBox, QSpinBox {
                padding: 6px;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                background-color: #F9FAFB;
            }
            QScrollArea {
                border: none;
                background-color: #F9FAFB;
            }
        """)
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout()
        
        # --- Top Section: Connection & Global Controls ---
        top_bar = QHBoxLayout()
        
        # Connection
        conn_group = QWidget() # GroupBox not needed in top bar style
        conn_layout = QHBoxLayout()
        conn_layout.setContentsMargins(0, 0, 0, 0)
        
        lbl_port = QLabel("Port:")
        lbl_port.setStyleSheet("font-weight: 600;")
        conn_layout.addWidget(lbl_port)
        
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(100)
        self.refresh_ports()
        conn_layout.addWidget(self.port_combo)
        
        self.connect_button = QPushButton("Bağlan")
        self.connect_button.setCursor(Qt.PointingHandCursor)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.connect_button.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #2563EB; }
        """)
        conn_layout.addWidget(self.connect_button)
        
        self.connection_status = QLabel("❌")
        conn_layout.addWidget(self.connection_status)
        
        conn_group.setLayout(conn_layout)
        top_bar.addWidget(conn_group)
        
        # Auto-Connect Checkbox
        self.chk_auto_connect = QCheckBox("Otomatik Bağlan")
        self.chk_auto_connect.setChecked(True) # Default On
        top_bar.addWidget(self.chk_auto_connect)

        top_bar.addStretch()
        
        # Startup Auto-Connect
        QTimer.singleShot(1000, self.startup_auto_connect)
        
        # Görev 2: COM Port Watcher — periyodik yeni port algılama
        self._known_ports = set()
        self._port_watcher = QTimer(self)
        self._port_watcher.timeout.connect(self._check_new_ports)
        self._port_watcher.start(5000)  # 5 saniyede bir kontrol
        
        # --- Temporary Test Buttons REMOVED (Moved to DeviceCard) ---
        # User requested to remove "Conta", "Eldiven", "RF ID" buttons from top bar.
        
        # top_bar.addWidget(test_frame) # Removed
        
        layout.addLayout(top_bar)
        
        # --- Main Content with Splitter (Grid + Logs) ---
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(6)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #E5E7EB;
                border-radius: 2px;
            }
            QSplitter::handle:hover {
                background-color: #9CA3AF;
            }
        """)
        
        # --- Device Grid ---
        grid_group = QGroupBox("Cihaz İzleme Paneli")
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; }")
        
        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background-color: transparent;")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(20)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        
        scroll.setWidget(self.grid_container)
        
        grid_wrapper = QVBoxLayout()
        grid_wrapper.addWidget(scroll)
        grid_group.setLayout(grid_wrapper)
        
        splitter.addWidget(grid_group)
        
        # --- Bottom Section: Resizable Logs ---
        bottom_splitter = QSplitter(Qt.Horizontal)
        bottom_splitter.setHandleWidth(4)
        
        # 1. System Logs (Left)
        log_group = QGroupBox("Sistem Logları")
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(10, 15, 10, 10)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("border: none; background: #F9FAFB; color: #4B5563; font-family: monospace; font-size: 11px;")
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        
        # 2. Master Traffic (Right) — hidden by default, set visible for debug
        traffic_group = QGroupBox("Canlı Master Trafiği (Çözülmüş)")
        traffic_layout = QVBoxLayout()
        traffic_layout.setContentsMargins(10, 15, 10, 10)
        self.traffic_log = QTextEdit()
        self.traffic_log.setReadOnly(True)
        self.traffic_log.setStyleSheet("border: none; background: #EEF2FF; color: #1E1B4B; font-family: monospace; font-size: 11px;")
        traffic_layout.addWidget(self.traffic_log)
        traffic_group.setLayout(traffic_layout)
        self.traffic_group = traffic_group          # keep reference for re-enable
        traffic_group.setVisible(False)             # <<< GİZLİ — tekrar açmak için: self.traffic_group.setVisible(True)
        
        bottom_splitter.addWidget(log_group)
        bottom_splitter.addWidget(traffic_group)
        bottom_splitter.setSizes([400, 400])
        
        splitter.addWidget(bottom_splitter)
        
        # Set initial sizes: Grid gets most space, Bottom section gets minority
        splitter.setSizes([500, 150])
        
        layout.addWidget(splitter)
        
        self.setLayout(layout)

    def refresh_ports(self):
        """Refresh available COM ports"""
        self.port_combo.clear()
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)

    def startup_auto_connect(self):
        """Try to auto-connect on startup with Smart Port Memory"""
        # Zaten bağlıysa (main.py'de arka planda bağlandıysa) tekrar deneme
        if self.esp32.is_connected:
            self.connect_button.setText("Kes")
            self.connection_status.setText("✅ Bağlı")
            port = self.esp32.port_name or ""
            index = self.port_combo.findText(port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            self.log(f"Zaten bağlı: {port}")
            self.refresh_slave_list()
            return
        
        if self.chk_auto_connect.isChecked():
            # 1. Smart Port Check
            last_port = self.settings.value("last_com_port")
            available_ports = [self.port_combo.itemText(i) for i in range(self.port_combo.count())]
            
            if last_port and last_port in available_ports:
                self.log(f"Akıllı Bağlantı: Son kullanılan port denenecek ({last_port})...")
                self.start_connection_worker(last_port, is_smart_attempt=True)
            else:
                self.log("Otomatik bağlantı aranıyor (Tarama Modu)...")
                self.start_connection_worker(None)

    def toggle_connection(self):
        """Connect/Disconnect ESP32 (Async)"""
        if self.esp32.is_connected:
            self.esp32.disconnect()
            self.connect_button.setText("Bağlan")
            self.connect_button.setEnabled(True)
            self.connection_status.setText("❌")
            self.mark_all_offline()
            # Reconnect'te addslave tekrar gönderilsin diye keşif setini temizle
            self._stream_discovered.clear()
            self._device_last_seen.clear()
            self._heartbeat_timer.stop()
        else:
            port = self.port_combo.currentText()
            if not port:
                return
            
            self.start_connection_worker(port)

    def start_connection_worker(self, port, is_smart_attempt=False):
        """Start the background connection thread"""
        self.connect_button.setEnabled(False)
        self.connect_button.setText("Bağlanıyor...")
        self.port_combo.setEnabled(False)
        
        self.connection_worker = ConnectionWorker(self.esp32, port)
        self.connection_worker.finished.connect(lambda s, m, p: self.on_connection_finished(s, m, p, is_smart_attempt))
        self.connection_worker.start()

    def on_connection_finished(self, success, msg, port, is_smart_attempt):
        """Handle connection result from worker"""
        self.connect_button.setEnabled(True)
        self.port_combo.setEnabled(True)
        
        if success:
            self.connect_button.setText("Kes")
            self.connection_status.setText("✅ Bağlı")
            
            # Select correct port in combo
            index = self.port_combo.findText(port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            
            self.log(f"Bağlantı Başarılı: {port}")
            
            # Save Smart Port
            self.settings.setValue("last_com_port", port)
            
            # Heartbeat timer başlat
            self._device_last_seen.clear()
            self._heartbeat_timer.start(1000)
            
            # Initial Synces
            self.refresh_slave_list()
            
        else:
            self.connect_button.setText("Bağlan")
            
            if is_smart_attempt:
                self.log(f"Akıllı Bağlantı Başarısız ({port}): {msg}. Tarama moduna geçiliyor...", "orange")
                # Fallback to Full Scan
                QTimer.singleShot(500, lambda: self.start_connection_worker(None))
            else:
                # Regular failure — sessiz log, MessageBox GÖSTERME (Görev 2)
                self.log(f"Bağlantı denemesi başarısız: {msg}", "orange")

    def mark_all_offline(self):
        for card in self.device_cards.values():
            card.update_status(False)

    def _check_device_heartbeats(self):
        """1 saniyede bir çalışır — stream gelmeyen cihazları kaldırır."""
        now = time.time()
        # Sync sırasında daha uzun timeout (10s), normal durumda 2s
        timeout_sec = 10.0 if self._sync_in_progress else 2.0
        timed_out = [name for name, ts in self._device_last_seen.items() if now - ts > timeout_sec]
        for name in timed_out:
            del self._device_last_seen[name]
            card = self.device_cards.pop(name, None)
            if card:
                card.setParent(None)
                card.deleteLater()
                _logger.info("Cihaz zaman aşımı — kart kaldırıldı: %s", name)
                self.log(f"⚠ Cihaz bağlantısı kesildi: {name} ({timeout_sec:.0f}s zaman aşımı)", color="red")
            # İlgili state temizliği
            mac_to_remove = None
            for mac, n in list(self._known_macs.items()):
                if n == name:
                    mac_to_remove = mac
                    break
            if mac_to_remove:
                del self._known_macs[mac_to_remove]
                self._stream_discovered.discard(mac_to_remove)
                # Aktif sync bu cihazdayı ise iptal et, sıradakine geç
                if self._sync_active_mac == mac_to_remove:
                    self.log(f"Sync iptal ediliyor (cihaz koptu): {name}", "#DC2626")
                    self._finish_device_sync(mac_to_remove)
                # Kuyruktan da temizle
                self._sync_queue = collections.deque((m, n2) for m, n2 in self._sync_queue if m != mac_to_remove)
            self.esp32.slave_devices = [s for s in self.esp32.slave_devices if s.get('name') != name]
            self.device_buffers.pop(name, None)
            # last_rfid_state temizliği
            for key in [k for k in self.last_rfid_state if k.startswith(f"{name}_")]:
                del self.last_rfid_state[key]
            self._history_requested_devices.discard(name) if hasattr(self, '_history_requested_devices') else None
        # Kalan kartları grid'e yeniden yerleştir
        if timed_out and self.device_cards:
            for i, (n, c) in enumerate(self.device_cards.items()):
                row, col = i // 4, i % 4
                self.grid_layout.addWidget(c, row, col)
        if timed_out:
            self.update_slave_grid(self.esp32.slave_devices)

    def refresh_slave_list(self):
        """Request updated slave list from master"""
        if self.esp32.is_connected:
            # Trigger async scan on master
            self.esp32.get_slave_list()
            self.log("Cihaz taraması başlatıldı...")

    def _check_new_ports(self):
        """Görev 2: Periyodik COM port tarama — yeni port algılanırsa sessizce bağlan"""
        try:
            import serial.tools.list_ports
            current_ports = set(p.device for p in serial.tools.list_ports.comports())
            
            if not self._known_ports:
                # İlk çalışma — sadece mevcut portları kaydet
                self._known_ports = current_ports
                return
            
            new_ports = current_ports - self._known_ports
            self._known_ports = current_ports
            
            if new_ports and not self.esp32.is_connected:
                # Yeni port algılandı ve bağlı değiliz — sessizce tarama başlat
                self.log(f"Yeni port algılandı: {', '.join(new_ports)} — otomatik bağlanılıyor...", "blue")
                self.refresh_ports()
                self.start_connection_worker(None)
        except Exception:
            _logger.debug("_check_new_ports error", exc_info=True)

    def on_slave_list_received(self, slaves):
        """Callback from ESP32 thread"""
        self.slaves_updated.emit(slaves)

    def on_raw_data_received(self, data):
        """Callback for raw data received (Thread to UI)"""
        self.raw_data_received.emit(data)

    def on_sent_data_received(self, data):
        """Callback for sent data (Thread to UI)"""
        self.command_sent.emit(data, "")

    def set_layout_panel(self, panel):
        """Link LayoutPanel for direct updates"""
        self.layout_panel = panel

    def set_batch_panel(self, panel):
        """Link BatchPanel for batch status updates on test completion"""
        self.batch_panel = panel

    def set_io_bridge(self, bridge):
        """Link WeidmullerBridge for batch_complete DO signal on test save"""
        self._io_bridge = bridge

    def set_pdf_generator(self, pdf_gen):
        """Link PDFReportGenerator for auto PDF generation on test save"""
        self.pdf_gen = pdf_gen

    def on_rx_data(self, data):
        """Handle RX data on UI thread"""
        # FAST STREAM PARSER — 20 pipe-delimited fields:
        # @S:RFID|port|auth|p1|p2|p3|p4|p6|p7|p8|recipe|pressure|raw|ms|name|did|bat|phase|tes|CRC
        if "@S:" in data:
            try:
                # Robust split for [Sender] @S:Payload
                start_part, payload = data.split("@S:", 1)
                sender_id = start_part.strip().strip("[]")
                payload = payload.strip()
            except Exception as e:
                _logger.warning("FastStream parse error: %s", e)
                return
            
            parts = payload.split('|')
            # ── CRC Doğrulama ──
            # 21 alan beklenir (20 veri + 1 CRC). Alan sayısı veya CRC tutmazsa paket atılır.
            if len(parts) < 21:
                return  # eksik/bozuk paket — sessizce atla
            try:
                received_crc = int(parts[20].strip(), 16)
                # XOR checksum: "@S:" sonrası CRC alanı hariç tüm payload
                crc_payload = '|'.join(parts[:20])
                calc_crc = 0
                for b in crc_payload.encode('utf-8'):
                    calc_crc ^= b
                calc_crc &= 0xFF
                if calc_crc != received_crc:
                    return  # CRC hatalı — bozuk paket, atla
            except (ValueError, IndexError):
                return  # CRC parse edilemedi — bozuk paket
            if len(parts) >= 21:
                try:
                    rfid = parts[0]
                    port = int(parts[1])
                    auth = parts[2] == '1'
                    # PC DB override: ESP32 tag'ı henüz almamış olabilir
                    if not auth and rfid != "0x00000000":
                        try:
                            _db_ports = self.db.get_all_ports()
                            if any(p.get('rfid_tag', '').lower() == rfid.lower() for p in _db_ports if p.get('rfid_tag')):
                                auth = True
                        except Exception:
                            pass
                    p1 = int(parts[3])
                    p2 = int(parts[4])
                    p3 = int(parts[5])
                    p4 = int(parts[6])
                    p6 = int(parts[7])
                    p7 = int(parts[8])
                    p8 = int(parts[9])
                    recipe_name = parts[10]
                    pressure = int(parts[11])
                    raw_pressure = parts[12]
                    time_ms = parts[13]
                    device_name = parts[14]      # cihaz adı (kart için)
                    device_id = parts[15]        # LCC_XXXXXXXX
                    battery = int(parts[16])     # batarya %
                    phase = parts[17]            # I/M/P/S/T/F/V/A
                    test_elapsed = int(parts[18].strip()) # test süresi (sn)
                    flash_count = int(parts[19].strip())  # flash'taki test sayısı

                    # Resolve sender_name: device_name → device_id → MAC
                    mac = sender_id if ":" in sender_id else ""
                    if device_name and device_name not in self._INVALID_NAMES:
                        sender_name = device_name
                    elif device_id:
                        sender_name = device_id
                    else:
                        sender_name = sender_id  # son çare: ham MAC

                    # Stream'den device_id cache güncelle (çift anahtarlı)
                    if device_id and sender_name:
                        self.esp32.device_id_cache[sender_name] = device_id
                        if mac:
                            self.esp32.device_id_cache[mac] = device_id

                    # ── Heartbeat güncelle ──
                    if sender_name:
                        self._device_last_seen[sender_name] = time.time()

                    # ── Flash Count > 0 ise POST fazına ertele ──
                    if not hasattr(self, '_history_requested_devices'):
                        self._history_requested_devices = set()
                    if flash_count > 0 and sender_name:
                        if sender_name not in self._history_requested_devices:
                            self._history_requested_devices.add(sender_name)
                            if self._sync_in_progress or self._sync_phase is not None:
                                # Sync devam ediyor — POST fazına ertele
                                self._flash_pending_devices.add(sender_name)
                                self.log(f"Flash'ta {flash_count} test kaydı var → POST fazında tetiklenecek [{sender_name}]", color="#059669")
                            else:
                                # Sync yok — hemen tetikle
                                self.log(f"Flash'ta {flash_count} test kaydı var → GET_TEST_HISTORY tetikleniyor [{sender_name}]", color="#059669", bold=True)
                                QTimer.singleShot(2000, lambda n=sender_name: self._send_get_test_history(n))
                    elif flash_count == 0 and sender_name:
                        # Flash temizlendi — bir sonraki test için tekrar tetiklenebilsin
                        self._history_requested_devices.discard(sender_name)
                        # Watchdog timer varsa durdur (başarılı temizlik)
                        if sender_name in self._history_timeout_timers:
                            self._history_timeout_timers[sender_name].stop()
                            del self._history_timeout_timers[sender_name]
                            self._history_timeout_retries.pop(sender_name, None)

                    # ── Device Card Auto-Registration (replaces HELLO) ──
                    if sender_name and sender_name not in self._INVALID_NAMES and mac:
                        if sender_name not in self.device_cards:
                            # İlk kez bu cihazı görüyoruz — kart oluştur
                            self._register_device_from_stream(sender_name, mac, battery, device_id)
                        else:
                            # Var olan kart — batarya güncelle
                            self.device_cards[sender_name].update_status(True, battery=battery)
                    elif mac and ":" in mac:
                        # MAC var ama isim yok: slave listesine ekle
                        sender_name = mac
                        if not any(s.get('mac','').lower() == mac.lower() for s in self.esp32.slave_devices):
                            self.esp32.slave_devices.append({'id': '?', 'name': mac, 'mac': mac, 'status': 'BAGLI'})
                            self.update_slave_grid(self.esp32.slave_devices)

                    # ── Traffic Log (Throttled — saniyede max 2 güncelleme) ──
                    # 5Hz stream'i her pakette yazdırmak UI'ı kilitler.
                    # Bunun yerine cihaz başına saniyede 2 özet satırı: okunabilir + donmaz.
                    _phase_labels = {'I': 'Bekleme', 'M': 'Montaj', 'P': 'Şişirme',
                                     'S': 'Stabilize', 'T': 'Test', 'F': 'Bitti',
                                     'V': 'Tahliye', 'A': 'İptal'}
                    _traffic_key = f"_last_traffic_{sender_name}"
                    _now = time.time()
                    _last = getattr(self, _traffic_key, 0)
                    if _now - _last >= 0.5:  # 500ms throttle (2 Hz)
                        setattr(self, _traffic_key, _now)
                        _phase_text = _phase_labels.get(phase, phase)
                        _rfid_short = rfid if rfid != "0x00000000" else "—"
                        _auth_text = "✓" if auth else "✗"
                        traffic_info = (
                            f"<b>[{sender_name}]</b> "
                            f"<span style='color:#4F46E5'>📡</span> "
                            f"RFID:<b>{_rfid_short}</b> "
                            f"Port:<b>{port_display(port)}</b> "
                            f"Auth:<b>{_auth_text}</b> "
                            f"P1:<b>{p1}</b> "
                            f"P2:<b>{p2}</b> "
                            f"P3:<b>{p3}</b> "
                            f"P4:<b>{p4}</b> "
                            f"P6:<b>{p6}</b> "
                            f"P7:<b>{p7}</b> "
                            f"P8:<b>{p8}</b> "
                            f"Reçete:<b>{recipe_name}</b> "
                            f"Basınç:<b>{pressure}</b>Pa "
                            f"Raw:<b>{raw_pressure}</b> "
                            f"ms:<b>{time_ms}</b> "
                            f"Cihaz:<b>{device_name}</b> "
                            f"ID:<b>{device_id}</b> "
                            f"Bat:<b>{battery}%</b> "
                            f"Faz:<b>{_phase_text}</b> "
                            f"Süre:<b>{test_elapsed}s</b> "
                            f"Flash:<b>{flash_count}</b>"
                        )
                        with self.buffer_lock:
                            self.stream_message_buffer.append((traffic_info, "#4F46E5"))
                    
                    # ── RFID State Change Log ──
                    state_key = f"{sender_name}_tag"
                    if self.last_rfid_state.get(state_key) != rfid:
                        if rfid == "0x00000000":
                            self.log(f"RFID Uzaklaştırıldı: ({sender_name})", color="#D97706")
                        else:
                            self.log(f"RFID Algılandı: {rfid} ({sender_name}, Port: {port}, Reçete: {recipe_name})", color="#2563EB")
                        
                        if hasattr(self, 'layout_panel') and self.layout_panel:
                            if rfid != "0x00000000" and auth:
                                self.layout_panel.highlight_port(rfid, sender_name)
                            else:
                                self.layout_panel.clear_port_highlight(sender_name)

                        # ORAPS 3D viewer'a haber ver (oraps_port_labels.rfid_tag
                        # eslesirse o port mesh'i yeşil/nötr yanıp söner).
                        try:
                            is_active = bool(rfid and rfid != "0x00000000" and auth)
                            self.rfid_state_changed.emit(sender_name, rfid or '', is_active)
                        except Exception:
                            pass
                        
                        self.last_rfid_state[state_key] = rfid
                    
                    # ── Update UI Card ──
                    if sender_name in self.device_cards:
                        display_rfid = rfid if rfid != "0x00000000" else None
                        info_text = f"Port {port_display(port)} ({recipe_name})" if display_rfid else "BEKLİYOR"
                        self.device_cards[sender_name].set_rfid_info(display_rfid, info_text, auth)
                        
                    # ── Phase-based Test Graph (replaces TEST_DATA handler) ──
                    if sender_name not in self.device_buffers:
                        self.device_buffers[sender_name] = {'time': [], 'pressure': [], 'start_ms': None, 'is_testing': False, 'last_graph_ms': 0}
                    
                    buf = self.device_buffers[sender_name]
                    buf['current_rfid'] = rfid
                    buf['current_port'] = port
                    buf['current_recipe_name'] = recipe_name

                    # ── Reçete bilgilerini stream'den güncelle ──
                    # TEST_STARTED JSON'u gelmese bile grafik doğru çizgi ve etiketleri gösterir.
                    buf['recipe'] = {
                        'name': recipe_name,
                        'p1': p1,   # Inflation Max Time (sn)
                        'p2': p2,   # Inflation Target (Pascal)
                        'p3': p3,   # Stabilization Time (sn)
                        'p4': p4,   # Reinflate Threshold
                        'p6': p6,   # Fail Threshold (Limit Pa)
                        'p7': p7,   # Test Duration (sn)
                        'p8': p8,   # Success Drop (Pa)
                    }

                    # Auto-activate graph recording from phase
                    active_phases = ('P', 'S', 'T')  # Pre-inflation, Stabilization, Testing
                    stop_phases = ('F', 'I')          # Finished, Idle → grafik dondur
                    if phase in active_phases:
                        if not buf.get('is_testing', False):
                            buf['is_testing'] = True
                            buf['frozen'] = False
                            buf['pc_start_time'] = time.time()
                            self.log(f"[GRAPH] Auto-activated recording for {sender_name} (phase: {phase})", color="cyan")
                    elif phase in stop_phases:
                        if buf.get('is_testing', False):
                            buf['is_testing'] = False
                            buf['frozen'] = True
                            self.log(f"[GRAPH] Auto-stopped recording for {sender_name} (phase: {phase})", color="orange")

                    # Forward phase data to detail dialog (replaces TEST_DATA)
                    phase_map = {'I': 'idle', 'M': 'mounting', 'P': 'inflation',
                                 'S': 'stabilization', 'T': 'testing', 'F': 'finished',
                                 'V': 'venting', 'A': 'aborted'}
                    if self.current_detail_dialog and self.current_detail_dialog.isVisible() and self.current_detail_target == sender_name:
                        test_data = {
                            'device': sender_name,
                            'phase': phase_map.get(phase, 'unknown'),
                            'glove_pressure': pressure,
                            'battery': battery,
                            'test_elapsed_sec': test_elapsed,
                        }
                        self.current_detail_dialog.update_test_data(test_data)
                    
                    # Graph data (only when testing)
                    if buf.get('is_testing', False):
                        try:
                            current_ms = int(str(time_ms).strip())
                            pres_val = float(pressure)
                            
                            if buf.get('start_ms') is None:
                                buf['start_ms'] = current_ms
                            if current_ms < buf['start_ms']:
                                buf['start_ms'] = current_ms
                                
                            last_graph_ms = buf.get('last_graph_ms', 0)
                            if current_ms - last_graph_ms >= 1000 or len(buf['time']) == 0:
                                buf['last_graph_ms'] = current_ms
                                relative_sec = (current_ms - buf['start_ms']) / 1000.0
                                
                                buf['time'].append(relative_sec)
                                buf['pressure'].append(pres_val)
                                
                                if len(buf['time']) > 4000:
                                    buf['time'].pop(0)
                                    buf['pressure'].pop(0)
                                    
                                if self.current_detail_dialog and self.current_detail_dialog.isVisible() and self.current_detail_target == sender_name:
                                    if hasattr(self.current_detail_dialog, 'update_graph_only'):
                                        self.current_detail_dialog.update_graph_only()
                                    else:
                                        self.current_detail_dialog.update_graph_data(buf['time'], buf['pressure'])
                        except Exception:
                            _logger.debug("Graph dialog update error", exc_info=True)
                    
                    # Push to Settings Dialog (Live Monitor)
                    if self.current_settings_dialog and self.current_settings_dialog.isVisible() and self.current_settings_target == sender_name:
                         try:
                             p_val = int(pressure)
                             r_val = float(raw_pressure) if raw_pressure else None
                             self.current_settings_dialog.update_live_data(p_val, r_val)
                         except Exception as e:
                             _logger.warning("Settings dialog update error: %s", e)

                except Exception as e:
                    _logger.warning("FastStream parse error: %s", e)
                return # Fast Exit

        # ── TEORİ 2 FIX: Master auto-register logunu yakala ──
        # Master bilinmeyen slave'i "Slave_XXXX" olarak kaydeder.
        # PC bunu görünce _known_macs'teki gerçek isimle addslave gönderir.
        _auto_reg_match = re.search(
            r'\[ESP-NOW\] Auto-registered:\s*(\S+)\s*\(([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\)',
            data
        )
        if _auto_reg_match:
            _auto_name = _auto_reg_match.group(1)  # "Slave_8834"
            _auto_mac = _auto_reg_match.group(2)   # "70:04:1D:CD:88:34"
            _real_name = self._known_macs.get(_auto_mac)
            if _real_name and _real_name != _auto_name:
                self.log(f"Auto-register düzeltme: {_auto_name} → {_real_name} ({_auto_mac})", color="blue")
                self.esp32.send_command(f"addslave {_real_name} {_auto_mac}")
            return  # Bu satır JSON değil, log — daha fazla parse etmeye gerek yok

        # Parse [Sender] {JSON} format
        # KORUMA: Master TX buffer taşmasında \r\n düşerse iki mesaj birleşebilir.
        # [MAC] sınırlarında bölerek her birini ayrı ayrı işle.
        _mac_json_all = re.findall(
            r'(\[[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\]\s*\{[^{]*?\})',
            data.strip()
        )
        if len(_mac_json_all) > 1:
            for seg in _mac_json_all:
                self.on_rx_data(seg.strip())
            return

        match = re.search(r"\[(.*?)\]\s*(\{.*\})", data.strip())
        
        # Default değerler — match olmasa bile LOG/CALIB handler'da erişilebilir
        sender_id = None
        sender_name = None
        clean_mac = None
        msg_data = None
        
        if match:
            sender_id = match.group(1).strip()
            json_str = match.group(2).strip()
            
            # Resolution: Resolve MAC to Name if sender_id is a MAC
            # Serial line corruption fix: sender_id can be garbled like "70:0[70:04:1D:CD:88:34"
            # Extract a valid MAC pattern (XX:XX:XX:XX:XX:XX) from anywhere in the string
            sender_name = sender_id
            _mac_pattern = re.search(r'([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})', sender_id)
            clean_mac = _mac_pattern.group(1) if _mac_pattern else None
            is_mac = clean_mac is not None
            if is_mac:
                # Önce _known_macs'ten bak (stream parser tarafından doldurulur)
                if hasattr(self, '_known_macs') and clean_mac in self._known_macs:
                    sender_name = self._known_macs[clean_mac]
                else:
                    for slave in self.esp32.slave_devices:
                        if slave.get('mac', '').lower() == clean_mac.lower():
                            sender_name = slave.get('name', sender_id)
                            break

            # Heartbeat: JSON komutları da cihazın hayatta olduğunu gösterir
            if sender_name in self._device_last_seen:
                self._device_last_seen[sender_name] = time.time()

            msg_data = None
            try:
                msg_data = json.loads(json_str)
                if not isinstance(msg_data, dict):
                    return  # dict değil (düz string/sayı) — atla
                cmd = msg_data.get("cmd")
                
                # Update Traffic Log with resolved data
                traffic_color = "#374151"
                if cmd == "RFID_DETECTED": traffic_color = "#2563EB"
                elif cmd == "RFID_REMOVED": traffic_color = "#D97706"
                elif "ERROR" in json_str.upper(): traffic_color = "#DC2626"
                
                self.traffic_message.emit(f"<b>[{sender_name}]</b> {json_str}", traffic_color)

                if cmd == "RFID_DETECTED":
                    rfid = msg_data.get("rfid", "").upper()
                    
                    # IGNORE 00000000
                    if "00000000" in rfid:
                        return
                    
                    port = msg_data.get("port", 0)
                    
                    # Görev 6: Port 0 ise sessizce bypass
                    if port == 0 or port == '0':
                        return
                    
                    auth_raw = msg_data.get("auth", False)
                    # Robust boolean parsing
                    auth = str(auth_raw).lower() == 'true' if isinstance(auth_raw, str) else bool(auth_raw)

                    # --- PC DB override: RFID zaten DB'de kayıtlıysa auth=True say ---
                    pc_port_data = None
                    if not auth:
                        try:
                            all_ports = self.db.get_all_ports()
                            pc_port_data = next(
                                (p for p in all_ports
                                 if p.get('rfid_tag') and p['rfid_tag'].upper() == rfid),
                                None
                            )
                            if pc_port_data:
                                auth = True
                                port = port_from_db_name(pc_port_data.get('name', ''))
                        except Exception:
                            pass

                    # Only log if tag changed to prevent flood
                    state_key = f"{sender_name}_tag"
                    if self.last_rfid_state.get(state_key) != rfid:
                        self.log(f"RFID Tespit: {rfid} ({sender_name}, Port: {port_display(port)}, Auth: {auth})", color="#2563EB")
                        self.last_rfid_state[state_key] = rfid

                    # --- Auto-push: cihaz bilmiyor ama PC biliyor → SET_TAG_CONFIG gönder ---
                    if pc_port_data and sender_name:
                        try:
                            ap_port_num = port_from_db_name(pc_port_data.get('name', ''))
                            if ap_port_num > 0:
                                recipe_id = pc_port_data.get('recipe_id')
                                recipe = self.db.get_recipe(recipe_id) if recipe_id else None
                                if not recipe:
                                    recipes = self.db.get_all_recipes()
                                    recipe = next((r for r in recipes if r['name'] == 'Test Reçetesi'), None)
                                if recipe:
                                    r = recipe
                                    ap_recipe_str = f"{r.get('t1_inflation',10)}-{r.get('p1_pressure',500)}-{r.get('t2_stabilization',10)}-{r.get('p2_hysteresis',50)}-{r.get('p3_limit',100)}-{r.get('t3_measurement',60)}-{r.get('p8_success_drop',100)}"
                                    ap_recipe_name = r.get('name', 'Varsayilan')
                                    self.assign_config_to_tag(sender_name, rfid, ap_port_num, ap_recipe_str, ap_recipe_name)
                                    self.log(f"Auto-push: {rfid} -> Port {port_display(ap_port_num)} ({sender_name})", "#059669")
                        except Exception as e:
                            _logger.error("RFID auto-push error: %s", e, exc_info=True)

                    if sender_name in self.device_cards:
                        self.device_cards[sender_name].set_rfid_info(rfid, f"Port {port_display(port)}", auth)
                    
                    # Update layout panel immediately
                    if hasattr(self, 'layout_panel') and self.layout_panel:
                        self.layout_panel.on_new_rfid_detected(msg_data)

                elif cmd == "RFID_REMOVED":
                    rfid = msg_data.get("rfid")
                    esp_crc_str = msg_data.get("crc", "")
                    esp_count = msg_data.get("count", -1)
                    
                    # Only log if tag was previously present to prevent flood
                    state_key = f"{sender_name}_tag"
                    if self.last_rfid_state.get(state_key) is not None:
                        self.log(f"RFID Uzaklaştırıldı ({sender_name})", color="#D97706")
                        self.last_rfid_state[state_key] = None
                        
                    if sender_name in self.device_cards:
                        self.device_cards[sender_name].set_rfid_info(None)
                    
                    # CRC karşılaştırma (DELETE_TAG sonucu ise CRC alanı gelir)
                    if esp_crc_str and esp_count >= 0:
                        pc_count = len([p for p in self.db.get_all_ports() if p.get('rfid_tag') and p['rfid_tag'] not in ('-', '0x00000000')])
                        if esp_count != pc_count:
                            self.log(f"CRC Uyuşmazlık: Silme sonrası count farkı (ESP:{esp_count} vs PC:{pc_count}) -> Full Sync tetikleniyor", "#DC2626")
                            _target = self._resolve_target(sender_name)
                            QTimer.singleShot(500, lambda t=_target: self._broadcast_rfid_db_targeted(t))

                elif cmd == "RFID_ITEM":
                    # CRC doğrulama
                    chk_valid = True
                    chk_received = msg_data.get("chk")
                    if chk_received is not None:
                        # XOR checksum: rfid|port|recipe alanları üzerinden
                        chk_payload = f"{msg_data.get('rfid','')}{msg_data.get('port','')}{msg_data.get('recipe','')}"
                        calc_chk = 0
                        for b in chk_payload.encode('utf-8'):
                            calc_chk ^= b
                        calc_chk &= 0xFF
                        if calc_chk != int(chk_received):
                            self.log(f"RFID_ITEM CRC Hatası: {msg_data.get('rfid','')} (beklenen={calc_chk}, gelen={chk_received}) — atlandı", "red")
                            chk_valid = False
                    
                    if chk_valid:
                        # Collect item for Sync
                        if sender_name not in self.slave_sync_buffers:
                            self.slave_sync_buffers[sender_name] = []
                        
                        rfid = msg_data.get("rfid", "").upper()
                        # Filter invalid tags from list
                        if "00000000" not in rfid:
                             self.slave_sync_buffers[sender_name].append(msg_data)
                    
                    # Restart Debounce Timer (1000ms)
                    # If entries stop coming, process what we have.
                    if sender_name not in self.sync_timers:
                        self.sync_timers[sender_name] = QTimer()
                        self.sync_timers[sender_name].setSingleShot(True)
                        self.sync_timers[sender_name].timeout.connect(lambda: self._process_slave_sync(sender_name))
                    
                    self.sync_timers[sender_name].start(1000)

                elif cmd == "CRC_REPLY":
                    self._crc_timeout_timer.stop()
                    crc_val = msg_data.get("crc", "0x00000000")
                    crc_count = msg_data.get("count", 0)
                    esp_crc = int(crc_val, 16)
                    pc_crc = self._pc_rfid_payload_crc
                    _crc_mac = clean_mac
                    if not _crc_mac:
                        for _m, _n in self._known_macs.items():
                            if _n == sender_name:
                                _crc_mac = _m
                                break
                    if esp_crc == pc_crc and esp_crc != 0:
                        self.log(f"CRC Eşleşti ({crc_count} port, CRC={crc_val}) — RFID sync atlanıyor.", "#059669")
                        if _crc_mac:
                            self._advance_rfid()
                    else:
                        self.log(f"CRC Farklı! ESP=0x{esp_crc:08X} vs PC=0x{pc_crc:08X} — RFID sync başlatılıyor...", "#D97706")
                        if _crc_mac:
                            self._broadcast_rfid_db_targeted(_crc_mac)

                elif cmd == "PIN_CRC_REPLY":
                    self._crc_timeout_timer.stop()
                    pin_crc_val = msg_data.get("crc", "0x00000000")
                    pin_crc_count = msg_data.get("count", 0)
                    esp_pin_crc = int(pin_crc_val, 16)
                    pc_pin_crc = self._pc_user_pin_crc
                    _pin_mac = clean_mac
                    if not _pin_mac:
                        for _m, _n in self._known_macs.items():
                            if _n == sender_name:
                                _pin_mac = _m
                                break
                    if self._awaiting_pin_verify:
                        # PIN push sonrası doğrulama — eşleşme sonucuna göre ilerle
                        self._awaiting_pin_verify = False
                        if esp_pin_crc == pc_pin_crc and esp_pin_crc != 0:
                            self.log(f"PIN doğrulama CRC Eşleşti ({pin_crc_count} kullanıcı) ✓", "#059669")
                            if _pin_mac:
                                self._pin_sync_retries.pop(_pin_mac, None)
                            self._advance_pin()
                        else:
                            retry_count = self._pin_sync_retries.get(_pin_mac, 0) if _pin_mac else 0
                            if retry_count >= 3:
                                self.log(f"PIN CRC 3 doğrulama sonrası hâlâ farklı — devam ediliyor ({_pin_mac})", "#DC2626")
                                if _pin_mac:
                                    self._pin_sync_retries.pop(_pin_mac, None)
                                self._advance_pin()
                            else:
                                self.log(f"PIN doğrulama CRC Farklı! Tekrar push (deneme {retry_count + 1}/3)", "#D97706")
                                if _pin_mac:
                                    self._pin_sync_retries[_pin_mac] = retry_count + 1
                                    self._broadcast_user_pins_targeted(_pin_mac)
                    elif self._sync_phase == 'PIN':
                        # İlk PIN CRC kontrolü
                        if esp_pin_crc == pc_pin_crc and esp_pin_crc != 0:
                            self.log(f"PIN CRC Eşleşti ({pin_crc_count} kullanıcı, CRC={pin_crc_val}) — PIN sync atlanıyor.", "#059669")
                            if _pin_mac:
                                self._pin_sync_retries.pop(_pin_mac, None)
                            self._advance_pin()
                        else:
                            self.log(f"PIN CRC Farklı! ESP=0x{esp_pin_crc:08X} vs PC=0x{pc_pin_crc:08X} — PIN sync başlatılıyor...", "#D97706")
                            if _pin_mac:
                                self._pin_sync_retries[_pin_mac] = self._pin_sync_retries.get(_pin_mac, 0) + 1
                                self._broadcast_user_pins_targeted(_pin_mac)
                    else:
                        # Batch dışında gelen PIN_CRC_REPLY (manual trigger vs.)
                        if esp_pin_crc == pc_pin_crc and esp_pin_crc != 0:
                            self.log(f"PIN CRC Eşleşti ({pin_crc_count} kullanıcı, CRC={pin_crc_val})", "#059669")
                        else:
                            self.log(f"PIN CRC Farklı! ESP=0x{esp_pin_crc:08X} vs PC=0x{pc_pin_crc:08X} — PIN push başlatılıyor...", "#D97706")
                            if _pin_mac:
                                self._broadcast_user_pins_targeted(_pin_mac)

                elif cmd == "SYNC_OK":
                    _sync_mac = clean_mac
                    if not _sync_mac:
                        for _m, _n in self._known_macs.items():
                            if _n == sender_name:
                                _sync_mac = _m
                                break
                    if _sync_mac:
                        self._handle_sync_ok(_sync_mac, msg_data)

                elif cmd == "SYNC_FAIL":
                    _sync_mac = clean_mac
                    if not _sync_mac:
                        for _m, _n in self._known_macs.items():
                            if _n == sender_name:
                                _sync_mac = _m
                                break
                    if _sync_mac:
                        self._handle_sync_fail(_sync_mac, msg_data)

                elif cmd == "ACK_SYNC_START":
                    self.log(f"Sync başlatıldı: {sender_name} chunk bekleniyor...", "#8B5CF6")

                elif cmd == "SYNC_COMPLETE":
                    count = msg_data.get("count", 0)
                    self.log(f"Sync Tamamlandı: {count} port bildirildi. Kontrol ediliyor...", color="blue")
                    
                    # Ensure buffer exists even if empty (Important for restoring to empty device)
                    if sender_name not in self.slave_sync_buffers:
                        self.slave_sync_buffers[sender_name] = []
                    
                    # Stop timer and process immediately
                    if sender_name in self.sync_timers:
                        self.sync_timers[sender_name].stop()
                    
                    self._process_slave_sync(sender_name)



                elif cmd == "ACK_TAG_CONFIG":
                    rfid = msg_data.get("rfid", "").lower()
                    esp_crc_str = msg_data.get("crc", "")
                    esp_count = msg_data.get("count", -1)
                    self.log(f"OK: Ayarlar güncellendi -> {rfid}", "green")
                    
                    # CRC karşılaştırma: ESP32'nin bildirdiği CRC ile PC'nin hesapladığını karşılaştır
                    if esp_crc_str and esp_count >= 0:
                        pc_crc = self._calculate_rfid_payload_crc()
                        esp_crc = int(esp_crc_str, 16) if esp_crc_str.startswith("0x") else int(esp_crc_str)
                        pc_count = len([p for p in self.db.get_all_ports() if p.get('rfid_tag') and p['rfid_tag'] not in ('-', '0x00000000')])
                        if esp_count != pc_count:
                            self.log(f"CRC Uyuşmazlık: Count farkı (ESP:{esp_count} vs PC:{pc_count}) -> Full Sync tetikleniyor", "#DC2626")
                            _target = self._resolve_target(sender_name)
                            QTimer.singleShot(500, lambda t=_target: self._broadcast_rfid_db_targeted(t))
                    
                elif cmd == "ACK_RESET_SYNC":
                    self.log(f"Sync Başlatıldı: {sender_name}", color="green")
                    _target = self._resolve_target(sender_name)
                    QTimer.singleShot(200, lambda: self.esp32.send_command(f"send {_target} {{\"cmd\":\"GET_ALL_RFIDS\"}}"))
                
                elif cmd == "STATUS_REPLY":
                    device_name_hb = msg_data.get("device", sender_name)
                    battery = msg_data.get("battery")
                    
                    target_card = None
                    if device_name_hb and device_name_hb in self.device_cards:
                        target_card = self.device_cards[device_name_hb]
                    elif sender_name and sender_name in self.device_cards:
                        target_card = self.device_cards[sender_name]
                    
                    if target_card:
                        if battery is not None:
                            target_card.update_status(is_active=True, battery=int(battery))
                            if hasattr(target_card, 'update_battery'):
                                target_card.update_battery(int(battery))
                        else:
                            target_card.update_status(True)

                elif cmd == "TEST_DATA":
                    # Update device card battery from TEST_DATA
                    battery = msg_data.get('battery', 100)
                    phase = msg_data.get('phase', 'unknown')
                    if sender_name in self.device_cards:
                        self.device_cards[sender_name].update_status(True, battery=battery)

                    # --- Auto-activate graph recording if test is running but TEST_STARTED was missed ---
                    active_phases = ('inflation', 'stabilization', 'testing', 'measurement')
                    if phase in active_phases:
                        if sender_name not in self.device_buffers:
                            self.device_buffers[sender_name] = {'time': [], 'pressure': [], 'start_ms': None, 'is_testing': False, 'last_graph_ms': 0, 'frozen': False}
                        buf = self.device_buffers[sender_name]
                        if not buf.get('is_testing', False):
                            buf['is_testing'] = True
                            buf['frozen'] = False
                            buf['pc_start_time'] = time.time()
                            self.log(f"[GRAPH] Auto-activated recording for {sender_name} (phase: {phase})", color="cyan")

                        # Add pressure data point using PC clock as time source
                        glove_p = msg_data.get('glove_pressure', msg_data.get('pressure', 0))
                        pc_start = buf.get('pc_start_time')
                        if pc_start is None:
                            buf['pc_start_time'] = time.time()
                            pc_start = buf['pc_start_time']
                        elapsed = time.time() - pc_start

                        # 1-second throttle (match STREAM throttle)
                        last_t = buf['time'][-1] if buf['time'] else -1
                        if elapsed - last_t >= 1.0 or len(buf['time']) == 0:
                            buf['time'].append(round(elapsed, 2))
                            buf['pressure'].append(float(glove_p))
                            if len(buf['time']) > 4000:
                                buf['time'].pop(0)
                                buf['pressure'].pop(0)

                    # Forward real-time test data to detail dialog if open
                    if self.current_detail_dialog and self.current_detail_dialog.isVisible():
                        if self.current_detail_target == sender_name:
                            self.current_detail_dialog.update_test_data(msg_data)
                            # TRIGGER FAST GRAPH UPDATE
                            if hasattr(self.current_detail_dialog, 'update_graph_only'):
                                self.current_detail_dialog.update_graph_only()
                
                elif cmd == "THP":
                    # ═══════════════════════════════════════════════════════════
                    # DYNAMIC THP CHUNKING — Tek Payload Mimarisi (Receiver)
                    # ESP32 meta+basınç verisini pipe-delimited string olarak
                    # 180-byte chunk'lara böler ve sadece "THP" komutuyla gönderir.
                    # Payload format (birleşik):
                    #   [0]tid|[1]rfid|[2]port|[3]op|[4]rc|[5]rn|[6]dur|[7]sp
                    #   |[8]ep|[9]td|[10]wd|[11]sc|[12]ts|[13]r|[14]chk|[15]pressure_csv
                    # ═══════════════════════════════════════════════════════════
                    try:
                        idx = msg_data.get("i", 0)          # Test index (0-based)
                        total_tests = msg_data.get("n", 1)  # Toplam test sayısı
                        chunk_idx = msg_data.get("c", 0)    # Bu chunk'ın indexi
                        total_chunks = msg_data.get("ct", 1) # Bu test için toplam chunk
                        chunk_data = msg_data.get("d", "")  # Chunk string verisi

                        # İlk chunk geldiğinde buffer'ı hazırla
                        if sender_name not in self.offline_sync_buffers:
                            self.offline_sync_buffers[sender_name] = {}
                        if idx not in self.offline_sync_buffers[sender_name]:
                            self.offline_sync_buffers[sender_name][idx] = {
                                "chunks": {},
                                "ct": total_chunks,
                                "n": total_tests,
                                "meta": None,
                                "pressure": [],
                                "corrupted": False
                            }

                        test_buf = self.offline_sync_buffers[sender_name][idx]
                        test_buf["chunks"][chunk_idx] = chunk_data
                        self.log(f"THP chunk {chunk_idx+1}/{total_chunks} (test {idx+1}/{total_tests})")

                        # Tüm chunk'lar toplandı mı?
                        if len(test_buf["chunks"]) >= total_chunks:
                            # ── Chunk'ları sıralı birleştir ──
                            full_payload = ""
                            for ci in range(total_chunks):
                                full_payload += test_buf["chunks"].get(ci, "")
                            # Geçici chunks dict'i temizle (hafıza tasarrufu)
                            test_buf["chunks"] = {}

                            # ── Pipe-delimited parse ──
                            # Son pipe'dan sonrası pressure CSV
                            # İlk 15 field meta, 16. field pressure CSV
                            parts = full_payload.split('|')
                            if len(parts) < 16:
                                self.log(f"THP payload parse hatası: {len(parts)} alan (min 16 gerekli)", color="red")
                                test_buf["corrupted"] = True
                            else:
                                try:
                                    tid_val = int(parts[0])
                                    rfid_hex = parts[1]
                                    port_val = int(parts[2])
                                    op_str = parts[3]
                                    rc_str = parts[4]
                                    rn_str = parts[5]
                                    dur_val = int(parts[6])
                                    sp_val = int(parts[7])
                                    ep_val = int(parts[8])
                                    td_val = int(parts[9])
                                    wd_val = int(parts[10])
                                    sc_val = int(parts[11])
                                    ts_str = parts[12]
                                    r_str = parts[13]
                                    chk_val = int(parts[14])
                                    # parts[15:] basınç CSV'si (pipe içinde virgülle ayrılmış)
                                    # Not: Basınç CSV'sinde pipe olmaz ama birleştirme
                                    # sırasında chunk kesilmişse 15.'den sonrası hep CSV
                                    pressure_csv = '|'.join(parts[15:])

                                    # ── Meta dict oluştur (TEST_HISTORY_DONE uyumlu key'ler) ──
                                    rfid_int = int(rfid_hex, 16) if rfid_hex else 0
                                    meta = {
                                        'tid': tid_val,
                                        'rfid': rfid_hex,
                                        'port': port_val,
                                        'op': op_str,
                                        'rc': rc_str,
                                        'rn': rn_str,
                                        'dur': dur_val,
                                        'sp': sp_val,
                                        'ep': ep_val,
                                        'td': td_val,
                                        'wd': wd_val,
                                        'sc': sc_val,
                                        'ts': ts_str,
                                        'r': r_str,
                                        'chk': chk_val,
                                        'n': total_tests,
                                    }
                                    test_buf["meta"] = meta

                                    # ── CRC doğrulama ──
                                    calc_chk = (tid_val + rfid_int + port_val +
                                                sp_val + ep_val + dur_val +
                                                td_val + wd_val + sc_val) & 0xFFFFFFFF
                                    if calc_chk != chk_val:
                                        self.log(f"Çevrimdışı Test {tid_val}: Meta CRC Hatası! (calc={calc_chk} vs esp={chk_val})", color="red")
                                        test_buf["corrupted"] = True

                                    # ── Basınç CSV → int list ──
                                    if pressure_csv:
                                        raw_vals = [int(v) for v in pressure_csv.split(',') if v.strip() != '' and v.strip().lstrip('-').isdigit()]
                                        test_buf["pressure"] = raw_vals
                                    else:
                                        test_buf["pressure"] = []

                                    crc_status = 'OK' if not test_buf["corrupted"] else 'FAIL'
                                    self.log(f"Çevrimdışı test parse: tid={tid_val} sc={sc_val} pressure_len={len(test_buf['pressure'])} CRC:{crc_status}", color="cyan")

                                except (ValueError, IndexError) as pe:
                                    self.log(f"THP payload değer parse hatası: {pe}", color="red")
                                    test_buf["corrupted"] = True

                    except Exception as e:
                        print(f"THP error: {e}")
                        
                elif cmd == "TEST_HISTORY_DONE":
                    try:
                        # Watchdog timer'ı durdur — veri başarıyla geldi
                        _done_key = sender_name
                        if hasattr(self, '_known_macs'):
                            _mac_in_sender = re.search(r'([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})', sender_name)
                            if _mac_in_sender and _mac_in_sender.group(1) in self._known_macs:
                                _done_key = self._known_macs[_mac_in_sender.group(1)]
                        if _done_key in self._history_timeout_timers:
                            self._history_timeout_timers[_done_key].stop()
                            del self._history_timeout_timers[_done_key]
                        self.log(f"Çevrimdışı geçmiş aktarımı tamamlandı. Doğrulama yapılıyor...", color="blue")
                        # Fallback: serial corruption can garble sender_name — try to find the right buffer
                        _hist_key = sender_name
                        if _hist_key not in self.offline_sync_buffers and len(self.offline_sync_buffers) == 1:
                            _hist_key = next(iter(self.offline_sync_buffers))
                            self.log(f"⚠ sender_name '{sender_name}' buffer'da yok, fallback → '{_hist_key}'", color="orange")
                        elif _hist_key not in self.offline_sync_buffers:
                            self.log(f"HATA: sender_name '{sender_name}' offline_sync_buffers'da bulunamadı! Mevcut: {list(self.offline_sync_buffers.keys())}", color="red")
                        if _hist_key in self.offline_sync_buffers:
                            tests = self.offline_sync_buffers[_hist_key]
                            all_valid = True
                            saved_count = 0
                            
                            # Retry'da duplikasyon önleme: daha önce kaydedilmiş test_id'leri takip et
                            if not hasattr(self, '_saved_offline_tids'):
                                self._saved_offline_tids = set()
                            
                            for idx, test_obj in tests.items():
                                meta = test_obj.get("meta")
                                
                                # THP chunk'ları henüz tamamlanmadıysa (meta parse edilmediyse) atla
                                if meta is None:
                                    self.log(f"Test idx:{idx} henüz parse edilemedi (eksik chunk?), bozuk sayılıyor.", color="red")
                                    all_valid = False
                                    continue
                                
                                expected_sc = meta.get("sc", 0)
                                actual_len = len(test_obj.get("pressure", []))
                                
                                # 1. Validate corruption flag
                                if test_obj["corrupted"]:
                                    self.log(f"Test {meta.get('tid')} CRC veya yapısal olarak bozuk!", color="red")
                                    all_valid = False
                                    continue
                                    
                                # 2. Validate array length
                                exp = min(expected_sc, 600)
                                if actual_len != exp:
                                    self.log(f"Test {meta.get('tid')} basınç verisi eksik! Beklenen:{exp} Gelen:{actual_len}", color="red")
                                    all_valid = False
                                    continue
                                        
                                # 3. Validate logic
                                if not meta.get("ts"):
                                    self.log(f"Test {meta.get('tid')} geçersiz tarih formatı!", color="red")
                                    all_valid = False
                                    continue
                                
                                # ALL CLEAR -> Let's Save to DB
                                try:
                                    # Fix anomalous year from uninitialized ESP32 RTC (e.g. 20178)
                                    ts_raw = meta.get('ts', '')
                                    _port = meta.get('port', 0)
                                    _did = self.esp32.device_id_cache.get(sender_name, '')
                                    if not _did and clean_mac:
                                        _did = self.esp32.device_id_cache.get(clean_mac, '')
                                    if not _did and _hist_key != sender_name:
                                        _did = self.esp32.device_id_cache.get(_hist_key, '')
                                    if _did and ts_raw and self.db.is_duplicate_offline_test(_did, ts_raw[:19], _port):
                                        self.log(f"Test {meta.get('tid')} zaten DB'de mevcut (duplicate), atlanıyor.", color="cyan")
                                        saved_count += 1
                                        continue
                                    try:
                                        if len(ts_raw) > 19:
                                            ts_raw = ts_raw[:19] # Trim to normal ISO length just in case
                                        dt_obj = datetime.fromisoformat(ts_raw)
                                        if dt_obj.year > 2050 or dt_obj.year < 2020:
                                            ts_raw = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                                    except Exception:
                                        ts_raw = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

                                    # Match Operator ID dynamically from the ESP32 offline operator name
                                    op_name = meta.get('op', '').strip()
                                    op_id = 0
                                    if op_name:
                                        usr = self.db.get_user_by_username(op_name)
                                        if usr:
                                            op_id = usr.get('id', 0)

                                    # Parse T1/T2 markers from pressure data
                                    raw_samples = test_obj["pressure"]
                                    t1_index = None
                                    t2_index = None
                                    pressure_only = []
                                    for s_val in raw_samples:
                                        if s_val == -1 or s_val == 65535:  # T1 marker (int16 -1 = uint16 65535)
                                            t1_index = len(pressure_only)
                                        elif s_val == -2 or s_val == 65534:  # T2 marker
                                            t2_index = len(pressure_only)
                                        else:
                                            pressure_only.append(s_val)
                                    
                                    # Device unique ID (from cache — offline tests come after HELLO)
                                    # Çoklu fallback: sender_name → clean_mac → _hist_key
                                    device_id = self.esp32.device_id_cache.get(sender_name, '')
                                    if not device_id and clean_mac:
                                        device_id = self.esp32.device_id_cache.get(clean_mac, '')
                                    if not device_id and _hist_key != sender_name:
                                        device_id = self.esp32.device_id_cache.get(_hist_key, '')
                                    
                                    # Use device_id for test_id prefix if available
                                    # MAC adresindeki ':' Windows dosya adında yasak → kaldır
                                    off_prefix = device_id if device_id else sender_name.replace(':', '')
                                    seq = self.db.get_next_test_sequence(off_prefix)
                                    
                                    test_params = {
                                        'test_id': f"{off_prefix}-{seq:09d}",
                                        'operator_id': op_id,
                                        'glove_batch_number': meta.get('rfid', 'AUTO'),
                                        'glove_type': meta.get('rn', meta.get('rc', 'Unknown')),
                                        'test_start_time': ts_raw,
                                        'target_pressure': 0,
                                        'target_temperature': 25,
                                        'test_duration': meta.get('dur', 0),
                                        'test_status': 'FAILED' if meta.get('r') == 'FAIL' else 'COMPLETED',
                                        'device_id': device_id,
                                        'port_number': meta.get('port')
                                    }
                                    
                                    # Build data_json with pressure + recipe params
                                    data_obj = {
                                        "operator_name": op_name if op_name else 'Offline',
                                        "device_id": device_id,
                                        "port": meta.get('port', 0),
                                        "start_pressure": meta.get('sp', 0),
                                        "end_pressure": meta.get('ep', 0),
                                        "total_drop": meta.get('td', 0),
                                        "window_drop": meta.get('wd', 0),
                                        "pressure_readings": pressure_only,
                                        "time_points": list(range(len(pressure_only))),
                                        "t1_index": t1_index,
                                        "t2_index": t2_index,
                                        "offline_sync": True
                                    }
                                    
                                    # Parse compact recipe string from flash: "p1-p2-p3-p4-p6-p7-p8"
                                    rc_str = meta.get('rc', '')
                                    if rc_str and '-' in str(rc_str):
                                        try:
                                            rc_parts = [int(x) for x in str(rc_str).split('-')]
                                            if len(rc_parts) == 7:
                                                data_obj['recipe_params'] = {
                                                    'name': meta.get('rn', 'Unknown'),
                                                    'p1': rc_parts[0],
                                                    'p2': rc_parts[1],
                                                    'p3': rc_parts[2],
                                                    'p4': rc_parts[3],
                                                    'p6': rc_parts[4],
                                                    'p7': rc_parts[5],
                                                    'p8': rc_parts[6],
                                                }
                                                self.log(f"Offline reçete alındı: {data_obj['recipe_params']}", color="cyan")
                                        except Exception as e:
                                            self.log(f"Offline reçete parse hatası: {e}", color="orange")
                                    
                                    test_params['data_json'] = json.dumps(data_obj)
                                    
                                    # Duplikasyon kontrolü: Bu test daha önce kaydedildiyse atla
                                    offline_tid_key = f"{_hist_key}_{meta.get('tid')}"
                                    if offline_tid_key in self._saved_offline_tids:
                                        self.log(f"Test {meta.get('tid')} zaten kaydedilmiş, atlanıyor.", color="cyan")
                                        saved_count += 1
                                        continue
                                    
                                    # Tüm testler (online/offline/abort) tek yoldan: flash → THP sync → DB
                                    record_id = self.db.create_test_record(test_params)
                                    
                                    # Update completion
                                    self.db.update_test_record(record_id, {
                                        'test_end_time': meta.get('ts'),
                                        'test_status': 'ABORTED' if meta.get('r') == 'ABORTED' else ('FAILED' if meta.get('r') == 'FAIL' else 'COMPLETED'),
                                        'test_result': meta.get('r'),
                                        'data_json': test_params['data_json']
                                    })
                                    
                                    # Save Graph (using marker-parsed pressure data)
                                    try:
                                        from helpers.file_manager import LocalFileManager
                                        fm = LocalFileManager()
                                        time_arr = list(range(len(pressure_only)))  # 1 sample = 1 second
                                        
                                        chart_data = {
                                            "title": f"Test #{meta.get('tid')} Grafiği",
                                            "xAxis": {"data": time_arr, "title": "Süre (sn)"},
                                            "series": [{"name": "Basınç", "data": pressure_only}],
                                            "t1_index": t1_index,
                                            "t2_index": t2_index
                                        }
                                        fm.save_test_data(record_id, chart_data)
                                    except Exception as e:
                                        _logger.error("Error saving offline graph: %s", e)
                                    
                                    # ── BATCH HOOK: Test sonucunu batch paneline ilet ──
                                    try:
                                        if hasattr(self, 'batch_panel') and self.batch_panel:
                                            raw_rfid = str(meta.get('rfid', ''))
                                            # "4FD0CF" → "0x004FD0CF" formatına çevir
                                            hex_digits = raw_rfid.replace('0x', '').replace('0X', '')
                                            rfid_formatted = f"0x{hex_digits.upper().zfill(8)}"
                                            result_status = 'FAIL' if meta.get('r') == 'FAIL' else 'PASS'
                                            self.batch_panel.update_port_status(
                                                rfid_tag=rfid_formatted,
                                                status=result_status,
                                                test_record_id=record_id
                                            )
                                    except Exception as bpe:
                                        _logger.error("Batch port güncelleme hatası: %s", bpe)

                                    # ── BATCH COMPLETE SIGNAL: Tüm portlar bittiyse DO=1 ──
                                    try:
                                        if hasattr(self, '_io_bridge') and self._io_bridge:
                                            self._io_bridge.check_batch_complete()
                                    except Exception:
                                        pass

                                    # ── AUTO PDF: Test raporu otomatik oluştur ──
                                    try:
                                        if hasattr(self, 'pdf_gen') and self.pdf_gen:
                                            rec = self.db.get_test_record_by_id(record_id)
                                            if rec:
                                                _report_lang = self.db.get_language() if hasattr(self.db, 'get_language') else 'tr'
                                                pdf_path = self.pdf_gen.generate_test_report(rec, [], lang=_report_lang)
                                                self.log(f"PDF rapor oluşturuldu: {os.path.basename(pdf_path)}", color="#2563EB")
                                    except Exception as pdf_e:
                                        _logger.error("Test PDF oluşturma hatası: %s", pdf_e)

                                    saved_count += 1
                                    self._saved_offline_tids.add(offline_tid_key)
                                    self.log(f"Çevrimdışı Test {meta.get('tid')} başarıyla veritabanına işlendi.", color="green")
                                    
                                except Exception as dbe:
                                    self.log(f"Veritabanı kayıt hatası: {dbe}", color="red")
                                    all_valid = False
                                    
                            if all_valid and len(tests) > 0:
                                self.log(f"Tüm çevrimdışı testler ({saved_count}) DOĞRULANDI ve KAYDEDİLDİ. Hafıza temizleniyor...", color="green")
                                self.esp32.send_command(f"send {self._resolve_target(_hist_key)} {{\"cmd\":\"CLEAR_TEST_HISTORY\"}}")
                                # Başarılı sync sonrası buffer ve retry sayacını temizle
                                if _hist_key in self.offline_sync_buffers:
                                    del self.offline_sync_buffers[_hist_key]
                                if hasattr(self, '_saved_offline_tids'):
                                    self._saved_offline_tids.clear()
                                if hasattr(self, 'offline_sync_retries'):
                                    self.offline_sync_retries[_hist_key] = 0
                                self._history_timeout_retries.pop(_hist_key, None)
                            elif len(tests) == 0:
                                self.log("Çevrimdışı hafızada kayıtlı test yok.")
                                if hasattr(self, 'offline_sync_retries'):
                                    self.offline_sync_retries[_hist_key] = 0
                            else:
                                self.log(f"Hata/Eksik sebebiyle test hafızası temizlenmeyecek. Toplam: {len(tests)}, Kaydedilen: {saved_count}", color="orange")
                                # RETRY LOGIC
                                if not hasattr(self, 'offline_sync_retries'):
                                    self.offline_sync_retries = {}
                                retries = self.offline_sync_retries.get(_hist_key, 0)
                                if retries < 3:
                                    self.offline_sync_retries[_hist_key] = retries + 1
                                    self.log(f"Veriler bozuk/eksik. 2sn içinde tekrar deneniyor... (Deneme {retries+1}/3)", color="orange")
                                    # Retry fetching (watchdog timer ile)
                                    QTimer.singleShot(2000, lambda n=_hist_key: self._send_get_test_history(n))
                                else:
                                    self.log("Çevrimdışı senkronizasyon pes etti (Maksimum deneme aşıldı).", color="red")
                                    
                    except Exception as e:
                        _logger.error("TEST_HISTORY_DONE error: %s", e, exc_info=True)
                
                elif cmd == "NAK_TEST_HISTORY":
                    # ESP32 meşgul (test devam ediyor vb.) — sonsuz döngüyü önle
                    nak_msg = msg_data.get("msg", "Unknown")
                    self.log(f"⚠ TEST_HISTORY reddedildi [{sender_name}]: {nak_msg}", color="orange")
                    # Watchdog timer'ı durdur — retry yapma, cihaz zaten meşgul
                    _nak_key = sender_name
                    if hasattr(self, '_known_macs'):
                        _mac_in_nak = re.search(r'([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})', sender_name)
                        if _mac_in_nak and _mac_in_nak.group(1) in self._known_macs:
                            _nak_key = self._known_macs[_mac_in_nak.group(1)]
                    if _nak_key in self._history_timeout_timers:
                        self._history_timeout_timers[_nak_key].stop()
                        del self._history_timeout_timers[_nak_key]
                    self._history_timeout_retries.pop(_nak_key, None)
                    # Engeli kaldır → bir sonraki IDLE'da flash_count>0 ile tekrar tetiklensin
                    self._history_requested_devices.discard(_nak_key)
                    if _nak_key in self.offline_sync_buffers:
                        del self.offline_sync_buffers[_nak_key]

                elif cmd == "TEST_STARTED":
                    # Device started a test - create database record
                    self.log(f"Test Başladı: {sender_name} - {msg_data.get('recipe', 'N/A')}", color="green", bold=True)
                    
                    # --- Phase 6: Reset Buffer & Set State ---
                    if sender_name not in self.device_buffers:
                         self.device_buffers[sender_name] = {'time': [], 'pressure': [], 'start_ms': None, 'is_testing': False, 'last_graph_ms': 0}
                    
                    # CLEAR BUFFER for new test (IN-PLACE to preserve UI references)
                    self.device_buffers[sender_name]['time'].clear()
                    self.device_buffers[sender_name]['pressure'].clear()
                    self.device_buffers[sender_name]['start_ms'] = None
                    self.device_buffers[sender_name]['last_graph_ms'] = 0
                    self.device_buffers[sender_name]['pc_start_time'] = None  # Reset PC clock so graph X starts from 0
                    self.device_buffers[sender_name]['is_testing'] = True  # START RECORDING GRAPH
                    self.device_buffers[sender_name]['frozen'] = False      # Unfreeze graph for new test
                    # Notify dialog to reset its frozen state immediately
                    if self.current_detail_dialog and self.current_detail_dialog.isVisible() and self.current_detail_target == sender_name:
                        if hasattr(self.current_detail_dialog, '_graph_frozen'):
                            self.current_detail_dialog._graph_frozen = False
                    
                    # Reçete bilgileri artık stream parser'dan (p1-p8) device_buffers'a yazılıyor.
                    # DB kaydı ESP32 flash'tan THP sync ile gelir.
                    self.log(f"Not: Reçete stream'den alınacak, DB kaydı THP sync ile oluşturulacak", color="cyan")
                
                elif cmd == "TEST_START_FAILED":
                    # Device failed to start test
                    error_type = msg_data.get('error', 'UNKNOWN')
                    rfid = msg_data.get('rfid', '')
                    message = msg_data.get('message', 'Test başlatma hatası')
                    
                    self.log(f"❌ Test Başlatma Hatası: {sender_name}", color="red", bold=True)
                    self.log(f"   Hata: {message} ({error_type})", color="orange")
                    
                    # Stop Graphing and freeze
                    if sender_name in self.device_buffers:
                        self.device_buffers[sender_name]['is_testing'] = False
                        self.device_buffers[sender_name]['frozen'] = True
                    
                    # Show error dialog to user
                    from PyQt5.QtWidgets import QMessageBox
                    
                    # Build clean error message
                    err_msg = f"Cihaz: {sender_name}\n"
                    if rfid and rfid.lower() != "unknown" and rfid != "0":
                         err_msg += f"RFID: {rfid}\n"
                    err_msg += f"Hata: {error_type}\n\n{message}"
                    
                    QMessageBox.critical(self, "Test Başlatma Hatası", err_msg)
                
                elif cmd == "TEST_COMPLETED":
                    key_map = {
                        'r': 'result', 'op': 'operator', 'dur': 'duration_sec',
                        'sp': 'start_pressure', 'pl': 'pass_limit',
                        'ep': 'end_pressure', 'td': 'total_drop', 'wd': 'window_drop',
                        'bat': 'battery', 'tid': 'stored_test_id', 'ts': 'timestamp',
                        'rn': 'recipe_name'
                    }
                    for short_key, long_key in key_map.items():
                        if short_key in msg_data and long_key not in msg_data:
                            msg_data[long_key] = msg_data[short_key]

                    result = msg_data.get('result', 'UNKNOWN')
                    self.log(f"Test Tamamlandı: {sender_name} - Sonuç: {result}", color="green" if result == "PASS" else "orange", bold=True)

                    if sender_name in self.device_buffers:
                        self.device_buffers[sender_name]['is_testing'] = False
                        self.device_buffers[sender_name]['frozen'] = True

                    if self.current_detail_dialog and self.current_detail_dialog.isVisible():
                        if getattr(self, 'current_detail_target', None) == sender_name:
                            final_data = {'device': sender_name, 'phase': 'complete', 'test_status': 'completed', 'result': result}
                            self.current_detail_dialog.update_test_data(final_data)

                    # DB kaydı artık burada güncellenmIYOR — tüm kayıtlar ESP32 flash'tan THP sync ile gelir
                    self.log(f"Flash sync bekleniyor (TID: {msg_data.get('tid', '?')})...", color="cyan")

                elif cmd == "MOUNT_FAILED":
                    reason = msg_data.get("reason", "UNKNOWN")
                    reason_text = {
                        "NO_RFID": "RFID kart okuyucuda yok!",
                        "UNAUTHORIZED": "RFID kart yetkisiz!",
                        "WRONG_STATE": "Cihaz yanlış durumda!",
                    }.get(reason, reason)
                    self.log(f"⚠ MOUNT BAŞARISIZ [{sender_name}]: {reason_text}", color="#EF4444", bold=True)

                elif cmd in ["ACK_DISMOUNT"]:
                    self.log(f"Dismount komutu alındı: {sender_name}", color="orange")

                elif cmd in ["UNMOUNT", "TEST_ABORTED", "MOUNT_TIMEOUT"]:
                    # Device unmounted - update detail dialog with final values
                    battery = msg_data.get('battery', 100)
                    glove_pressure = msg_data.get('glove_pressure', 0)
                    
                    if cmd == "UNMOUNT":
                        self.log(f"Unmount: {sender_name}", color="orange", bold=True)
                    elif cmd == "TEST_ABORTED":
                        self.log(f"Test İptal Edildi: {sender_name}", color="red", bold=True)
                    elif cmd == "MOUNT_TIMEOUT":
                        self.log(f"Mount Zaman Aşımı: {sender_name}", color="red", bold=True)
                    
                    # Stop Graphing and freeze (Abort, Unmount, etc)
                    if sender_name in self.device_buffers:
                        self.device_buffers[sender_name]['is_testing'] = False
                        self.device_buffers[sender_name]['frozen'] = True
                    
                    # Update detail dialog if open
                    if self.current_detail_dialog and self.current_detail_dialog.isVisible():
                        if self.current_detail_target == sender_name:
                            unmount_data = {
                                'device': sender_name,
                                'battery': battery,
                                'glove_pressure': glove_pressure,
                                'phase': 'mounting',  # Return to mounting/ready state
                                'test_status': 'inactive'
                            }
                            self.current_detail_dialog.update_test_data(unmount_data)
                            self.log(f"[DEBUG] Dialog güncellendi: Battery={battery}%, Pressure={glove_pressure}Pa", color="cyan")
                    
                    # DB kaydı artık burada güncellenmIYOR — abort da dahil tüm kayıtlar ESP32 flash'tan THP sync ile gelir
                    if cmd == 'TEST_ABORTED':
                        self.log(f"Abort kaydı ESP32 flash'a yazıldı (TID: {msg_data.get('tid', '?')}), THP sync ile gelecek", color="cyan")
                     
            except json.JSONDecodeError as e:
                self.log(f"JSON Parse Hatası: {e} (Len: {len(json_str)})", color="red")
                self.log(f"İçerik: {json_str[:50]}...", color="red")
            except Exception as e:
                _logger.error("on_rx_data cmd handler error: %s", e, exc_info=True)
        
        # --- Handle LOG messages for Settings Dialog (Live Pressure) ---
        # Packet: {"cmd":"LOG", "type":"INF", "msg":"STREAM > Cal: 123 | Raw: 121.5 ..."}
        try:
             # msg_data is set to None before json.loads; truthy only if parse succeeded
             if msg_data is not None:
                 cmd = msg_data.get("cmd")
                 if cmd == "LOG":
                     msg = msg_data.get("msg", "")
                     if "STREAM >" in msg:
                         # Parse: STREAM > Filtreli: 123 | Ham: 121.50 | ...
                         # Firmware uses Turkish: Filtreli and Ham
                         cal_match = re.search(r"Filtreli:\s*(-?\d+)", msg)
                         if not cal_match: # Fallback to English if updated
                              cal_match = re.search(r"Cal:\s*(-?\d+)", msg)
                              
                         raw_match = re.search(r"Ham:\s*(-?\d+(\.\d+)?)", msg)
                         if not raw_match:
                              raw_match = re.search(r"Raw:\s*(-?\d+(\.\d+)?)", msg)
                         
                         if cal_match and self.current_settings_dialog and self.current_settings_dialog.isVisible():
                             # Hem isim hem MAC ile eşleştir
                             _stgt = self.current_settings_target
                             _smac = getattr(self, 'current_settings_target_mac', '')
                             _sender_mac = clean_mac or ''
                             if sender_name == _stgt or sender_id == _stgt or _sender_mac == _smac:
                                 cal_val = int(cal_match.group(1))
                                 raw_val = float(raw_match.group(1)) if raw_match else None
                                 self.current_settings_dialog.update_live_data(cal_val, raw_val)
                                 
                 elif cmd == "CALIB_DATA" or cmd == "ACK_ZERO":
                     # Hem isim hem MAC ile eşleştir — sender_name bazen çözümlenemez
                     _stgt = self.current_settings_target
                     _smac = getattr(self, 'current_settings_target_mac', '')
                     _sender_mac = clean_mac or ''
                     _match = sender_name == _stgt or sender_id == _stgt or _sender_mac == _smac
                     if _match:
                         # Retry timer'ı durdur — veri geldi
                         if hasattr(self, '_calib_retry_timer') and self._calib_retry_timer:
                             self._calib_retry_timer.stop()
                         
                         if self.current_settings_dialog and self.current_settings_dialog.isVisible():
                             # Dialog zaten açık — veriyi güncelle
                             self.current_settings_dialog.update_calibration_data(msg_data)
                         elif getattr(self, '_pending_settings_data', None):
                             # Dialog henüz açılmadı — şimdi aç (veri ile)
                             self._open_settings_dialog(calib_data=msg_data)

        except Exception as e:
            pass # Silent fail for log parsing
            
        else:
             pass

    def _push_config_to_slave(self, slave_name, rfid, port_num, recipe_id):
        """Helper to push configuration to slave"""
        try:
            if not recipe_id:
                 # Get Default Recipe
                 recipes = self.db.get_all_recipes()
                 recipe = next((r for r in recipes if r['name'] == "Test Reçetesi"), None)
            else:
                 recipe = self.db.get_recipe(recipe_id)
                 
            if recipe:
                r = recipe
                # Mapping: infMaxT-infP-stabT-reinfTh-failTh-testDur-succDropP
                recipe_str = f"{r.get('t1_inflation', 10)}-{r.get('p1_pressure', 500)}-{r.get('t2_stabilization', 10)}-{r.get('p2_hysteresis', 50)}-{r.get('p3_limit', 100)}-{r.get('t3_measurement', 60)}-{r.get('p8_success_drop', 100)}"
                recipe_name = r.get('name', 'Varsayilan')
            else:
                recipe_str = "10-500-10-50-100-60-100"
                recipe_name = "Varsayilan"
            
            # Normalize RFID to lowercase 0x
            rfid_norm = rfid.lower()

            # FORCE RE-REGISTRATION STRATEGY
            # 1. Delete existing (invalid) record
            del_cmd = f'{{"cmd":"DELETE_TAG", "rfid":"{rfid_norm}"}}'
            _target = self._resolve_target(slave_name)
            self.esp32.send_command(f"send {_target} {del_cmd}")
            
            # 2. Add fresh record (Wait 50ms to ensure sequential processing)
            cmd = f'{{"cmd":"SET_TAG_CONFIG", "rfid":"{rfid_norm}", "port":{port_num}, "recipe":"{recipe_str}", "recipe_name":"{recipe_name}"}}'
            
            # Use QTimer to delay the set command slightly
            QTimer.singleShot(100, lambda: self.esp32.send_command(f"send {_target} {cmd}"))
            
            self.log(f"Düzeltme: {rfid} silindi ve yeniden atanıyor -> Port {port_display(port_num)}", "blue")
        except Exception as e:
            _logger.error("_push_config_to_slave error for %s/%s: %s", slave_name, rfid, e, exc_info=True)
            self.log(f"Konfigürasyon Push Hatası: {rfid} - {e}", "red")

    def on_tx_data(self, cmd, resp):
        """Handle TX data on UI thread"""
        # PIN güvenliği: "pin":"XXXX" değerlerini maskele
        display_cmd = re.sub(r'"pin"\s*:\s*"[^"]*"', '"pin": "****"', cmd)
        self.append_log_html(f"TX > {display_cmd}", "#2563EB", True) # Blue and Bold

    def on_rfid_clicked(self, device_name):
        """Open RFID management for a specific device"""
        # ... logic ...
        # Trigger initial sync automatically after a short delay
        # This will send RESET_RFIDS_SYNC, and on_rx_data will trigger polling
        QTimer.singleShot(500, lambda: self.request_rfid_sync(device_name))
        
        self.rfid_dialog = None # Dialog logic removed for simplicity in this view?
        # Re-instating dialog call if needed, but user didn't ask for dialog changes specifically.
        # Just Sync logic.

    def _send_get_test_history(self, device_name: str):
        """GET_TEST_HISTORY gönder + 15s watchdog timer başlat."""
        _target = self._resolve_target(device_name)
        self.esp32.send_command(f'send {_target} {{"cmd":"GET_TEST_HISTORY"}}')
        # Eski buffer'ı temizle (bozuk kalan chunk'lar)
        if device_name in self.offline_sync_buffers:
            del self.offline_sync_buffers[device_name]
        # Watchdog: 15 saniye içinde TEST_HISTORY_DONE gelmezse retry
        if device_name in self._history_timeout_timers:
            self._history_timeout_timers[device_name].stop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda n=device_name: self._on_history_timeout(n))
        timer.start(15000)  # 15 saniye
        self._history_timeout_timers[device_name] = timer

    def _on_history_timeout(self, device_name: str):
        """GET_TEST_HISTORY yanıt gelmedi — retry veya vazgeç."""
        retries = self._history_timeout_retries.get(device_name, 0)
        if retries < 3:
            self._history_timeout_retries[device_name] = retries + 1
            self.log(f"⚠ GET_TEST_HISTORY yanıt gelmedi [{device_name}]. Tekrar deneniyor ({retries+1}/3)...", color="orange")
            # Buffer'ı temizle (bozuk chunk'lar varsa)
            if device_name in self.offline_sync_buffers:
                del self.offline_sync_buffers[device_name]
            self._send_get_test_history(device_name)
        else:
            self.log(f"GET_TEST_HISTORY zaman aşımı [{device_name}]. 3 deneme başarısız — bir sonraki bağlantıda tekrar denenecek.", color="red")
            # Engeli kaldır — bir sonraki flash_count>0 stream'inde tekrar tetiklensin
            self._history_requested_devices.discard(device_name)
            self._history_timeout_retries.pop(device_name, None)
            if device_name in self._history_timeout_timers:
                del self._history_timeout_timers[device_name]
            if device_name in self.offline_sync_buffers:
                del self.offline_sync_buffers[device_name]

    def _register_device_from_stream(self, name, mac, battery, device_id=""):
        """Stream'den gelen cihazı kartla kaydet (HELLO yerine)."""
        self.log(f"Yeni Cihaz Keşfedildi (Stream): {name} ({mac}) - Battery: {battery}%", color="#059669", bold=True)

        # MAC-based uniqueness: aynı MAC farklı isimle gelirse eski kartı kaldır
        old_name = self._known_macs.get(mac)
        if old_name and old_name != name and old_name in self.device_cards:
            old_card = self.device_cards.pop(old_name)
            old_card.setParent(None)
            old_card.deleteLater()
        self._known_macs[mac] = name

        # Kart oluştur
        card = DeviceCard(name, mac, self.auth, self)
        card.update_status(True, battery=battery)
        card.device_selected.connect(self.on_device_selected)
        card.settings_clicked.connect(self.on_device_settings_clicked)
        card.rfid_clicked.connect(self.on_rfid_clicked)
        card.register_port_clicked.connect(self.on_register_port_clicked)
        card.test_start_clicked.connect(self.on_device_test_start)
        card.test_dismount_clicked.connect(self.on_device_dismount)
        card.test_abort_clicked.connect(self.on_device_test_abort)
        card.test_mount_clicked.connect(self.on_device_mount)
        card.sync_clicked.connect(self._on_manual_sync_clicked)
        self.device_cards[name] = card
        count = len(self.device_cards) - 1
        row, col = count // 4, count % 4
        self.grid_layout.addWidget(card, row, col)

        # Slave listesine ekle
        if not any(s.get('mac') == mac for s in self.esp32.slave_devices):
            self.esp32.slave_devices.append({'id': device_id or '?', 'name': name, 'mac': mac, 'status': 'BAGLI'})
            self.update_slave_grid(self.esp32.slave_devices)

        # Post-connection actions (only once per MAC per session)
        if mac not in self._stream_discovered:
            self._stream_discovered.add(mac)
            self.esp32.send_command(f"addslave {name} {mac}")
            # refresh_slave_list ve GET_TEST_HISTORY artık POST fazında yapılıyor
            self._enqueue_device_sync(mac, name)

    def _end_sync_guard(self):
        """Sync/broadcast koruma flag'ini kaldır, heartbeat timeout tekrar aktif."""
        if self._sync_in_progress:
            self._sync_in_progress = False
            # Tüm canlı cihazların last_seen'ini şimdiye güncelle
            now = time.time()
            for name in list(self._device_last_seen.keys()):
                self._device_last_seen[name] = now
            self.log("RFID senkronizasyon koruması kaldırıldı.", color="#6B7280")

    # ── 2-Fazlı Batch Senkronizasyon Kuyruğu ──

    def _enqueue_device_sync(self, mac, name):
        """Yeni bağlanan cihazı senkronizasyon kuyruğuna ekle."""
        # Zaten kuyrukta veya aktif batch'te mi kontrol et
        if any(m == mac for m, _ in self._sync_queue):
            return
        if any(m == mac for m, _ in self._sync_batch):
            return
        self._sync_queue.append((mac, name))
        self.log(f"Kuyruk: {name} eklendi (bekleyen: {len(self._sync_queue)})", "#8B5CF6")

        # Sync aktif değilse → 3sn toplama penceresi başlat
        if self._sync_phase is None:
            self._sync_phase = 'COLLECTING'
            self._sync_collect_timer.start(3000)
            self.log("Cihaz toplama penceresi başladı (3sn)...", "#8B5CF6")
        elif self._sync_phase == 'COLLECTING':
            # Zaten toplama modunda — timer'ı resetle (son cihazdan 3sn bekle)
            self._sync_collect_timer.start(3000)

    def _start_sync_batch(self):
        """Toplama penceresi doldu — kuyruktaki cihazları batch'e al ve Faz 1 başlat."""
        if not self._sync_queue:
            self._sync_phase = None
            return

        self._sync_batch = list(self._sync_queue)
        self._sync_queue.clear()
        self._sync_batch_index = 0
        self._sync_in_progress = True

        names = [n for _, n in self._sync_batch]
        self.log(f"Batch Sync Başlıyor: {len(self._sync_batch)} cihaz ({', '.join(names)})", "#059669", bold=True)

        # Faz 1: PIN sync
        self._sync_phase = 'PIN'
        self.log("═══ FAZ 1: PIN Senkronizasyonu ═══", "#8B5CF6", bold=True)
        self._process_pin_for_current()

    def _process_pin_for_current(self):
        """Mevcut cihaz için SET_TIME + GET_PIN_CRC gönder."""
        if self._sync_batch_index >= len(self._sync_batch):
            # Tüm cihazların PIN'i tamamlandı → Faz 2'ye geç
            self._sync_batch_index = 0
            self._sync_phase = 'RFID'
            self.log("═══ FAZ 2: RFID Senkronizasyonu ═══", "#8B5CF6", bold=True)
            QTimer.singleShot(200, self._process_rfid_for_current)
            return

        mac, name = self._sync_batch[self._sync_batch_index]

        # Cihaz hâlâ bağlı mı?
        if mac not in self._known_macs:
            self.log(f"PIN: {name} artık bağlı değil, atlanıyor.", "#D97706")
            self._sync_batch_index += 1
            QTimer.singleShot(200, self._process_pin_for_current)
            return

        self._sync_active_mac = mac
        self.log(f"PIN Sync [{self._sync_batch_index + 1}/{len(self._sync_batch)}]: {name} ({mac})", "#059669")

        # SET_TIME
        self.esp32.send_time_to_device(mac)

        # 200ms sonra GET_PIN_CRC
        self._awaiting_pin_verify = False
        QTimer.singleShot(200, lambda m=mac: self._send_pin_crc_check(m))

    def _send_pin_crc_check(self, mac):
        """GET_PIN_CRC gönder + 2sn timeout başlat."""
        if self._sync_active_mac != mac:
            return
        self._calculate_user_pin_crc()
        self.log(f"GET_PIN_CRC → {mac} (PC=0x{self._pc_user_pin_crc:08X})", "#8B5CF6")
        self.esp32.send_command(f'send {mac} {{"cmd":"GET_PIN_CRC"}}')
        self._crc_timeout_timer.start(2000)

    def _advance_pin(self):
        """PIN fazında sonraki cihaza geç."""
        self._crc_timeout_timer.stop()
        self._sync_active_mac = None
        self._sync_batch_index += 1
        QTimer.singleShot(200, self._process_pin_for_current)

    def _process_rfid_for_current(self):
        """Mevcut cihaz için GET_CRC gönder."""
        if self._sync_batch_index >= len(self._sync_batch):
            # Tüm cihazların RFID'si tamamlandı → POST fazına geç
            self._sync_phase = 'POST'
            QTimer.singleShot(200, self._post_sync)
            return

        mac, name = self._sync_batch[self._sync_batch_index]

        # Cihaz hâlâ bağlı mı?
        if mac not in self._known_macs:
            self.log(f"RFID: {name} artık bağlı değil, atlanıyor.", "#D97706")
            self._sync_batch_index += 1
            QTimer.singleShot(200, self._process_rfid_for_current)
            return

        self._sync_active_mac = mac
        self.log(f"RFID Sync [{self._sync_batch_index + 1}/{len(self._sync_batch)}]: {name} ({mac})", "#059669")

        self._check_rfid_crc_and_sync(mac)

    def _advance_rfid(self):
        """RFID fazında sonraki cihaza geç."""
        self._crc_timeout_timer.stop()
        self._sync_active_mac = None
        self._sync_batch_index += 1
        QTimer.singleShot(200, self._process_rfid_for_current)

    def _post_sync(self):
        """Tüm cihazların sync'i tamamlandı — temizlik ve ertelenmiş görevler."""
        self.log("═══ Batch Sync Tamamlandı ═══", "#059669", bold=True)

        # 1. refresh_slave_list bir kez çağır
        self.refresh_slave_list()

        # 2. flash_count>0 olan cihazlar için GET_TEST_HISTORY tetikle
        if self._flash_pending_devices:
            self.log(f"GET_TEST_HISTORY tetikleniyor: {len(self._flash_pending_devices)} cihaz", "#059669")
            delay = 500
            for dev_name in list(self._flash_pending_devices):
                QTimer.singleShot(delay, lambda n=dev_name: self._send_get_test_history(n))
                delay += 200
            self._flash_pending_devices.clear()

        # 3. Sync guard'ı kaldır
        self._sync_active_mac = None
        self._sync_batch.clear()
        self._sync_batch_index = 0
        self._end_sync_guard()
        self._sync_phase = None

        # 4. Toplama sırasında yeni cihaz geldiyse yeni round başlat
        if self._sync_queue:
            self.log(f"Yeni cihazlar bekleniyor: {len(self._sync_queue)} — yeni round başlıyor...", "#8B5CF6")
            self._sync_phase = 'COLLECTING'
            self._sync_collect_timer.start(3000)

    def _on_crc_timeout(self):
        """2sn içinde CRC yanıtı gelmedi — loglayıp sonraki cihaza geç."""
        mac = self._sync_active_mac
        name = self._known_macs.get(mac, mac) if mac else "?"

        if self._sync_phase == 'PIN':
            if self._awaiting_pin_verify:
                # PIN verify timeout — push'u başarısız say ama devam et
                self.log(f"PIN verify CRC timeout ({name}) — devam ediliyor.", "#D97706")
                self._awaiting_pin_verify = False
                self._pin_sync_retries.pop(mac, None)
            else:
                self.log(f"PIN CRC timeout ({name}) — PIN sync atlanıyor.", "#D97706")
            self._advance_pin()
        elif self._sync_phase == 'RFID':
            self.log(f"RFID CRC timeout ({name}) — RFID sync atlanıyor.", "#D97706")
            self._advance_rfid()

    def _calculate_rfid_payload_crc(self):
        """PC DB'deki tüm geçerli portlardan payload CRC32 hesapla ve sakla."""
        try:
            all_ports = self.db.get_all_ports()
            valid_ports = [p for p in all_ports if p.get('rfid_tag') and p['rfid_tag'] not in ('-', '0x00000000')]
            if not valid_ports:
                self._pc_rfid_payload_crc = 0
                return 0

            lines = []
            for port in valid_ports:
                rfid = port['rfid_tag'].lower()
                port_num = port_from_db_name(port.get('name', ''))
                if port_num == 0:
                    continue
                recipe_id = port.get('recipe_id')
                if recipe_id:
                    recipe = self.db.get_recipe(recipe_id)
                else:
                    recipes = self.db.get_all_recipes()
                    recipe = next((r for r in recipes if r['name'] == 'Test Reçetesi'), None)
                if recipe:
                    r = recipe
                    recipe_str = f"{r.get('t1_inflation', 10)}-{r.get('p1_pressure', 500)}-{r.get('t2_stabilization', 10)}-{r.get('p2_hysteresis', 50)}-{r.get('p3_limit', 100)}-{r.get('t3_measurement', 60)}-{r.get('p8_success_drop', 100)}"
                    recipe_name = r.get('name', 'Varsayilan')
                else:
                    recipe_str = "10-500-10-50-100-60-100"
                    recipe_name = "Varsayilan"
                _tr_map = str.maketrans('çÇğĞıİöÖşŞüÜ', 'cCgGiIoOsSuU')
                recipe_name = recipe_name.translate(_tr_map)
                recipe_name = recipe_name.replace('|', '_').replace('\n', ' ')[:15]
                lines.append(f"{rfid}|{port_num}|{recipe_str}|{recipe_name}")

            if not lines:
                self._pc_rfid_payload_crc = 0
                return 0

            payload = '\n'.join(lines)
            payload_bytes = payload.encode('ascii', errors='replace')
            crc = zlib.crc32(payload_bytes, 0) & 0xFFFFFFFF
            self._pc_rfid_payload_crc = crc
            return crc
        except Exception as e:
            self.log(f"CRC hesaplama hatası: {e}", "#DC2626")
            self._pc_rfid_payload_crc = 0
            return 0

    def _check_rfid_crc_and_sync(self, mac):
        """Cihaza GET_CRC gönder + 2sn timeout başlat — CRC_REPLY gelince karşılaştırılacak."""
        if self._sync_active_mac != mac:
            return
        # Önce PC CRC'sini güncelle
        self._calculate_rfid_payload_crc()
        self.log(f"CRC kontrolü gönderiliyor -> {mac} (PC CRC=0x{self._pc_rfid_payload_crc:08X})", "#8B5CF6")
        self.esp32.send_command(f'send {mac} {{"cmd":"GET_CRC"}}')
        self._crc_timeout_timer.start(2000)
    def _calculate_user_pin_crc(self):
        """PC DB'deki tüm aktif kullanıcılardan PIN CRC32 hesapla ve sakla."""
        try:
            users = self.db.get_all_users_with_pins()
            if not users:
                self._pc_user_pin_crc = 0
                return 0
            # Alfabetik sırala (ESP32 ile aynı sıralama)
            users.sort(key=lambda u: u.get('name', ''))
            # Payload: name|pin\n formatı (ESP32 calculateUserPinCRC ile birebir aynı)
            lines = [f"{u['name']}|{u['pin']}\n" for u in users]
            payload = ''.join(lines)
            payload_bytes = payload.encode('utf-8')
            crc = zlib.crc32(payload_bytes, 0) & 0xFFFFFFFF
            self._pc_user_pin_crc = crc
            return crc
        except Exception as e:
            self.log(f"PIN CRC hesaplama hatası: {e}", "#DC2626")
            self._pc_user_pin_crc = 0
            return 0

    def _check_user_pin_crc_and_sync(self, mac):
        """Cihaza GET_PIN_CRC gönder — PIN_CRC_REPLY gelince karşılaştırılacak.
        NOT: Artık _send_pin_crc_check() kullanılıyor (batch orchestrator)."""
        if self._sync_active_mac != mac:
            return
        self._calculate_user_pin_crc()
        self.log(f"PIN CRC kontrolü gönderiliyor -> {mac} (PC PIN CRC=0x{self._pc_user_pin_crc:08X})", "#8B5CF6")
        self.esp32.send_command(f'send {mac} {{"cmd":"GET_PIN_CRC"}}')

    def _broadcast_user_pins_targeted(self, mac):
        """Kullanıcı PIN'lerini sadece belirtilen MAC'e gönder (200ms aralıkla)."""
        try:
            users = self.db.get_all_users_with_pins()
            clear_cmd = json.dumps({"cmd": "CLEAR_USER_PINS"}, separators=(',', ':'))
            QTimer.singleShot(0, lambda t=mac, c=clear_cmd: self.esp32.send_command(f"send {t} {c}"))
            # ESP-NOW 250 byte limiti: 2 kullanıcı/chunk ile ~140 byte (güvenli)
            chunk_size = 2
            chunk_idx = 0
            for i in range(0, len(users), chunk_size):
                chunk = users[i:i + chunk_size]
                add_cmd = json.dumps({"cmd": "ADD_USER_PINS", "users": chunk}, ensure_ascii=False, separators=(',', ':'))
                delay = 200 + (chunk_idx * 200)  # CLEAR sonrası 200ms, her chunk arası 200ms
                QTimer.singleShot(delay, lambda t=mac, c=add_cmd: self.esp32.send_command(f"send {t} {c}"))
                chunk_idx += 1
            # Push bittikten sonra doğrulama CRC kontrolü (200ms sonra)
            verify_delay = 200 + (chunk_idx * 200) + 200
            QTimer.singleShot(verify_delay, lambda m=mac: self._verify_pin_crc_after_push(m))
            self.log(f"PIN push -> {mac} ({len(users)} kullanıcı)", "#059669")
        except Exception as e:
            self.log(f"PIN push hatası ({mac}): {e}", "#DC2626")
            self._advance_pin()

    def _verify_pin_crc_after_push(self, mac):
        """PIN push sonrası doğrulama: GET_PIN_CRC gönder."""
        if self._sync_phase == 'PIN' and self._sync_active_mac == mac:
            # Batch modu — timeout ile doğrulama
            self._awaiting_pin_verify = True
            self.log(f"PIN push doğrulama CRC kontrolü -> {mac}", "#8B5CF6")
            self.esp32.send_command(f'send {mac} {{"cmd":"GET_PIN_CRC"}}')
            self._crc_timeout_timer.start(2000)
        else:
            # Manual modu — doğrulama CRC gönder (timeout yok, handler loglar)
            self._calculate_user_pin_crc()
            self.log(f"PIN push doğrulama CRC kontrolü -> {mac}", "#8B5CF6")
            self.esp32.send_command(f'send {mac} {{"cmd":"GET_PIN_CRC"}}')
    def _broadcast_rfid_db_targeted(self, mac):
        """PC DB'deki tüm RFID/port/reçete bilgilerini chunk tabanlı toplu olarak gönder."""
        if self._sync_active_mac != mac:
            return
        try:
            all_ports = self.db.get_all_ports()
            valid_ports = [p for p in all_ports if p.get('rfid_tag') and p['rfid_tag'] not in ('-', '0x00000000')]

            # Pipe-delimited payload oluştur: rfid|port|recipe_str|recipe_name\n
            lines = []
            for port in valid_ports:
                rfid = port['rfid_tag'].lower()
                port_num = port_from_db_name(port.get('name', ''))
                if port_num == 0:
                    continue

                recipe_id = port.get('recipe_id')
                if recipe_id:
                    recipe = self.db.get_recipe(recipe_id)
                else:
                    recipes = self.db.get_all_recipes()
                    recipe = next((r for r in recipes if r['name'] == 'Test Reçetesi'), None)

                if recipe:
                    r = recipe
                    recipe_str = f"{r.get('t1_inflation', 10)}-{r.get('p1_pressure', 500)}-{r.get('t2_stabilization', 10)}-{r.get('p2_hysteresis', 50)}-{r.get('p3_limit', 100)}-{r.get('t3_measurement', 60)}-{r.get('p8_success_drop', 100)}"
                    recipe_name = r.get('name', 'Varsayilan')
                else:
                    recipe_str = "10-500-10-50-100-60-100"
                    recipe_name = "Varsayilan"

                # recipe_name'deki pipe ve newline temizle + Türkçe → ASCII
                _tr_map = str.maketrans('çÇğĞıİöÖşŞüÜ', 'cCgGiIoOsSuU')
                recipe_name = recipe_name.translate(_tr_map)
                recipe_name = recipe_name.replace('|', '_').replace('\n', ' ')[:15]
                lines.append(f"{rfid}|{port_num}|{recipe_str}|{recipe_name}")

            if not lines:
                self.log(f"Push edilecek port yok ({mac}).", "#D97706")
                self._finish_device_sync(mac)
                return

            payload = '\n'.join(lines)
            payload_bytes = payload.encode('ascii', errors='replace')

            # CRC32 hesapla (payload üzerinden — ASCII garantili)
            payload_crc = zlib.crc32(payload_bytes, 0) & 0xFFFFFFFF
            self._pc_rfid_payload_crc = payload_crc  # Sakla — GET_CRC karşılaştırması için

            # Chunk'lara böl — ESP-NOW 250 byte limiti nedeniyle küçük tutuyoruz
            # 120 byte data + ~35 byte JSON envelope = ~155 byte ESP-NOW payload (250 limitinde %38 margin)
            CHUNK_DATA_SIZE = 120
            chunks = []
            for i in range(0, len(payload_bytes), CHUNK_DATA_SIZE):
                chunks.append(payload_bytes[i:i + CHUNK_DATA_SIZE].decode('ascii'))

            total_chunks = len(chunks)
            retries = self._rfid_sync_retries.get(mac, 0)

            self.log(f"Chunk RFID sync başlıyor -> {mac}: {len(lines)} port, {len(payload_bytes)} byte, {total_chunks} chunk (deneme {retries+1}/3)", "#059669")

            # 1) RFID_SYNC_START gönder (kompakt JSON — her byte önemli)
            start_cmd = json.dumps({"cmd": "RFID_SYNC_START", "n": len(lines), "sz": len(payload_bytes), "crc": f"0x{payload_crc:08X}", "cn": total_chunks}, separators=(',', ':'))
            self.esp32.send_command(f"send {mac} {start_cmd}")

            # 2) Chunk'ları 200ms aralıklarla gönder (kompakt JSON)
            for idx, chunk_data in enumerate(chunks):
                chunk_cmd = json.dumps({"cmd": "RSC", "i": idx, "n": total_chunks, "d": chunk_data}, separators=(',', ':'))
                delay_ms = 200 + (idx * 200)  # İlk chunk 200ms sonra, sonrakiler 200ms aralıkla
                QTimer.singleShot(delay_ms, lambda m=mac, c=chunk_cmd: self._send_chunk(m, c))

            # 3) Tüm chunk'lar gönderildikten sonra timeout başlat
            # ESP32 tarafında 3s chunk timeout var + parse+save süresi
            total_send_time = 200 + (total_chunks * 200) + 8000  # chunk süresi + 8s bekleme
            self._start_sync_timeout(mac, total_send_time)

        except Exception as e:
            self.log(f"RFID DB push hatası ({mac}): {e}", "#DC2626")
            self._finish_device_sync(mac)

    def _send_chunk(self, mac, cmd):
        """Tek bir chunk'ı gönder (QTimer callback)."""
        if self._sync_active_mac != mac:
            return
        self.esp32.send_command(f"send {mac} {cmd}")

    def _start_sync_timeout(self, mac, timeout_ms):
        """SYNC_OK/SYNC_FAIL yanıtı için timeout başlat."""
        timer = self._rfid_sync_timer.get(mac)
        if timer:
            timer.stop()
            try:
                timer.timeout.disconnect()
            except (TypeError, RuntimeError):
                pass
        else:
            timer = QTimer()
            timer.setSingleShot(True)
            self._rfid_sync_timer[mac] = timer
        timer.timeout.connect(lambda m=mac: self._sync_timeout(m))
        timer.start(timeout_ms)

    def _sync_timeout(self, mac):
        """ESP32'den SYNC_OK/SYNC_FAIL yanıtı gelmedi."""
        if self._sync_active_mac != mac:
            return
        retries = self._rfid_sync_retries.get(mac, 0) + 1
        self._rfid_sync_retries[mac] = retries
        if retries >= 3:
            self.log(f"Sync zaman aşımı — 3 deneme başarısız ({mac}).", "#DC2626", bold=True)
            self._rfid_sync_retries.pop(mac, None)
            self._finish_device_sync(mac)
        else:
            self.log(f"Sync zaman aşımı, tekrar deneniyor (deneme {retries+1}/3)...", "#D97706")
            QTimer.singleShot(1000, lambda m=mac: self._broadcast_rfid_db_targeted(m))

    def _handle_sync_ok(self, sender_mac, msg_data):
        """ESP32 chunked sync başarılı — tüm portlar doğrulandı ve kaydedildi."""
        if self._sync_active_mac != sender_mac:
            return
        # Timeout timer'ı durdur
        timer = self._rfid_sync_timer.get(sender_mac)
        if timer:
            timer.stop()
        count = msg_data.get('count', 0)
        parsed = msg_data.get('parsed', '?')
        ok = msg_data.get('ok', '?')
        max_tags = msg_data.get('max', '?')
        crc = msg_data.get('crc', '?')
        self.log(f"SYNC OK! ({count} port, parsed={parsed}, addOk={ok}, max={max_tags}, CRC={crc})", "#059669", bold=True)
        self._rfid_sync_retries.pop(sender_mac, None)
        self._finish_device_sync(sender_mac)

    def _handle_sync_fail(self, sender_mac, msg_data):
        """ESP32 chunked sync başarısız — CRC uyuşmazlığı veya buffer hatası."""
        if self._sync_active_mac != sender_mac:
            return
        # Timeout timer'ı durdur
        timer = self._rfid_sync_timer.get(sender_mac)
        if timer:
            timer.stop()
        reason = msg_data.get('reason', 'unknown')
        expected = msg_data.get('expected', '?')
        actual = msg_data.get('actual', '?')
        retries = self._rfid_sync_retries.get(sender_mac, 0) + 1
        self._rfid_sync_retries[sender_mac] = retries
        self.log(f"SYNC FAIL: {reason} (beklenen={expected}, hesaplanan={actual}). Deneme {retries}/3", "#DC2626", bold=True)
        if retries >= 3:
            self.log(f"3 deneme başarısız — sync iptal ({sender_mac}).", "#DC2626", bold=True)
            self._rfid_sync_retries.pop(sender_mac, None)
            self._finish_device_sync(sender_mac)
        else:
            self.log(f"Tekrar gönderiliyor (deneme {retries+1}/3)...", "#D97706")
            QTimer.singleShot(1000, lambda m=sender_mac: self._broadcast_rfid_db_targeted(m))

    def _finish_device_sync(self, mac):
        """Bir cihazın RFID sync'ini tamamla — batch'te sonraki cihaza geç."""
        if self._sync_active_mac == mac:
            # Timer temizle
            timer = self._rfid_sync_timer.get(mac)
            if timer:
                timer.stop()
                try:
                    timer.timeout.disconnect()
                except (TypeError, RuntimeError):
                    pass
            self._rfid_sync_retries.pop(mac, None)
            # İlgili cihazın name'ini bul
            name = self._known_macs.get(mac, mac)
            self.log(f"RFID Sync Tamamlandı: {name} ({mac})", "#059669")
            self._advance_rfid()

    def request_rfid_sync(self, device_name):
        """Send RESET_RFIDS_SYNC command to device"""
        cmd = '{"cmd":"RESET_RFIDS_SYNC"}'
        self.esp32.send_command(f"send {self._resolve_target(device_name)} {cmd}")
        self.log(f"RFID Sync isteği gönderildi -> {device_name}")

    def broadcast_rfid_db(self):
        """PC DB'deki tüm RFID/port/reçete bilgilerini tüm bağlı slave'lere batch sync ile push et."""
        if self._sync_in_progress or self._sync_phase is not None:
            self.log("Sync zaten devam ediyor, yeni broadcast atlanıyor.", "#D97706")
            return
        try:
            if not self.esp32.slave_devices:
                self.log("broadcast_rfid_db: Bağlı slave yok.", "#D97706")
                return

            # Tüm slave'leri batch kuyruk sistemine ekle
            for slave in self.esp32.slave_devices:
                mac = slave.get('mac')
                name = slave.get('name', mac)
                if mac:
                    self._enqueue_device_sync(mac, name)

            self.log(f"broadcast_rfid_db: {len(self.esp32.slave_devices)} cihaz kuyruğa eklendi.", "#059669")
        except Exception as e:
            self.log(f"broadcast_rfid_db hatası: {e}", "#DC2626")
        
    def assign_config_to_tag(self, device_name, tag_id, port, recipe_str, recipe_name="Varsayilan"):
        """Send SET_TAG_CONFIG command"""
        cmd = f'{{"cmd":"SET_TAG_CONFIG", "rfid":"{tag_id}", "port":{port}, "recipe":"{recipe_str}", "recipe_name":"{recipe_name}"}}'
        self.esp32.send_command(f"send {self._resolve_target(device_name)} {cmd}")
        self.log(f"Port ve Reçete atandı -> {tag_id} (Port: {port})")

    def on_register_port_clicked(self, mac, rfid):
        """Handle quick registration click from device card"""
        # Find device name from mac
        device_name = "Bilinmeyen Cihaz"
        for name, card in self.device_cards.items():
            if card.mac == mac:
                device_name = name
                break
                
        # Get default recipe for registration
        recipes = self.db.get_all_recipes()
        # Sadece aktif reçeteler
        recipes = [r for r in recipes if r.get('is_active', 1) and r.get('name') != '4545']
        default_recipe_str = ""
        tr = next((r for r in recipes if r['name'] == "Test Reçetesi"), None)
        if tr:
            default_recipe_str = f"{tr.get('t1_inflation', 30)}-{tr.get('p1_pressure', 1000)}-{tr.get('t2_stabilization', 30)}-{tr.get('p2_hysteresis', 50)}-{tr.get('p3_limit', 100)}-{tr.get('t3_measurement', 60)}-{tr.get('p8_success_drop', 100)}"
        else:
            default_recipe_str = "60-1500-60-50-100-300-50"

        dialog = PortRegistrationDialog(rfid, default_recipe_str, self.db, self)
        self._heartbeat_timer.stop()
        try:
            accepted = dialog.exec_() == QDialog.Accepted
        finally:
            self._heartbeat_timer.start(1000)
        if accepted:
            port_num = dialog.port_number
            recipe_str = dialog.selected_recipe or default_recipe_str
            
            # Decode for display/DB name
            port_left = port_num >> 8
            port_right = port_num & 0xFF
            
            # 1. Update Database (Source of Truth)
            # Check if port exists
            all_ports = self.db.get_all_ports()
            target_name = f"Port {port_left}/{port_right}"
            existing_port = next((p for p in all_ports if p['name'] == target_name), None)
            
            recipe_id = None
            # Find recipe ID from recipe string or selected data?
            # Dialog logic returns recipe string for hardware, but we need ID for DB.
            # We can extract it from the dialog or lookup.
            # Dialog.selected_recipe contains whatever was stored in itemData (likely ID or Str).
            # Let's check PortRegistrationDialog again. 
            # It stores `self.recipe_combo.currentData()`.
            # Step 1373 showed currentData is `r_str` (string).
            # Wait, `load_recipes` sets itemData to `r_str`.
            # So we only have the string. We need to find the ID to save to DB.
            
            # Reverse lookup recipe ID from string (or better, modify Dialog to provide ID)
            # For now, let's find ID from DB based on string match? Risky.
            # Better: Dialog should return ID.
            # But let's proceed with finding it here.
            
            matched_recipe_id = None
            if dialog.db:
                recipes = dialog.db.get_all_recipes()
                # Try to find recipe by comparing parameter string
                for r in recipes:
                    r_str = f"{r.get('t1_inflation', 30)}-{r.get('p1_pressure', 1000)}-{r.get('t2_stabilization', 30)}-{r.get('p2_hysteresis', 50)}-{r.get('p3_limit', 100)}-{r.get('t3_measurement', 60)}-{r.get('p8_success_drop', 100)}"
                    if r_str == recipe_str:
                         matched_recipe_id = r['id']
                         break
            
            if existing_port:
                self.db.update_glove_port_details(existing_port['id'], rfid, matched_recipe_id)
                self.log(f"DB Güncellendi: Port {port_display(port_num)} -> {rfid}", "green")
                try:
                    self.audit.log_action(
                        'RFID_ASSIGN',
                        table_name='glove_ports',
                        record_id=existing_port['id'],
                        new_value=rfid,
                        description=f"RFID atandı: {rfid} → {target_name}",
                        category='GLT',
                    )
                except Exception:
                    pass
            else:
                self.db.add_glove_port(target_name, 100, 100, rfid, matched_recipe_id)
                self.log(f"DB Yeni Kayıt: Port {port_display(port_num)} -> {rfid}", "green")
                try:
                    self.audit.log_action(
                        'RFID_ADD',
                        table_name='glove_ports',
                        new_value=rfid,
                        description=f"RFID kaydı eklendi: {rfid} → {target_name}",
                        category='GLT',
                    )
                except Exception:
                    pass

            # 2. Send to ALL slaves (staggered to prevent serial overflow)
            recipe_name = "Varsayilan"
            if matched_recipe_id:
                _r = self.db.get_recipe(matched_recipe_id)
                if _r:
                    recipe_name = _r.get('name', 'Varsayilan')
            for idx, slave in enumerate(self.esp32.slave_devices):
                slave_name = slave.get('name')
                if slave_name:
                    delay = idx * 150
                    QTimer.singleShot(delay, lambda sn=slave_name: self.assign_config_to_tag(sn, rfid, port_num, recipe_str, recipe_name))
            self.log(f"Hızlı Kayıt tüm cihazlara gönderildi: {rfid} -> Port {port_num}")
            
            # 3. Trigger UI Refresh (Layout Panel must reload)
            if hasattr(self, 'layout_panel'):
                 self.layout_panel.refresh_map()
                 self.layout_panel.rfid_sidebar.refresh_list()

    def append_log_html(self, message, color="#374151", bold=False):
        """Add formatted HTML message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        weight = "bold" if bold else "normal"
        html = f'<span style="color: #9CA3AF;">[{timestamp}]</span> <span style="color: {color}; font-weight: {weight};">{message}</span>'
        self.log_text.append(html)
        # Auto scroll
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def append_traffic_html(self, message, color="#374151"):
        """Add formatted JSON/Traffic message to right log"""
        # PIN güvenliği: tüm trafik log'unda PIN değerlerini maskele
        message = re.sub(r'"pin"\s*:\s*"[^"]*"', '"pin": "****"', message)
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds (3 digits)
        html = f'<span style="color: #94A3B8; font-size: 10px;">[{timestamp}]</span> <span style="color: {color};">{message}</span>'
        self.traffic_log.append(html)
        # Auto scroll
        self.traffic_log.verticalScrollBar().setValue(self.traffic_log.verticalScrollBar().maximum())
        
        # OPTIMIZED: Only cleanup every 100 messages instead of every message
        # This prevents slow QTextEdit cursor operations from blocking UI thread
        if not hasattr(self, '_traffic_counter'):
            self._traffic_counter = 0
        self._traffic_counter += 1
        
        if self._traffic_counter % 100 == 0:  # Every 100 messages
            # Limit buffer to 200 lines (increased from 50 for better history)
            doc = self.traffic_log.document()
            while doc.blockCount() > 200:
                cursor = self.traffic_log.textCursor()
                cursor.movePosition(cursor.Start)
                cursor.select(cursor.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()

    def log(self, message, color="#6B7280", bold=False):
        """Standard log method (Thread-safe via Signal)"""
        # Echo to terminal for remote debugging (Unicode-safe for Windows)
        if "DEBUG (Unmatched)" not in message:
            try:
                import sys
                # Encode with system encoding, replace unsupported chars (e.g. emoji)
                safe_msg = message.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8')
                print(f"[GUI LOG] {safe_msg}")
            except Exception:
                # Fallback: ASCII-only if encoding fails completely
                try:
                    safe_msg = message.encode('ascii', errors='ignore').decode('ascii')
                    print(f"[GUI LOG] {safe_msg}")
                except Exception:
                    pass  # Silent failure - don't crash GUI
        
        # Emit signal so append_log_html runs on Main Thread
        self.log_message.emit(message, color, bold)

    def update_slave_grid(self, slaves):
        """Update device grid with slave information.
        Görev 4: Kartlar burada OLUŞTURULMAZ — sadece mevcut kartların durumu güncellenir.
        Kart oluşturma yalnızca HELLO handler'da yapılır (isim + MAC belli olunca).
        """
        try:
            # Map current slaves by name for easy lookup
            current_slave_map = {}
            for idx, slave in enumerate(slaves):
                if idx >= 16: break
                name = slave.get('name', '')
                if name:
                    current_slave_map[name] = slave

            # 1. Update existing cards
            for name, card in self.device_cards.items():
                if name in current_slave_map:
                    slave = current_slave_map[name]
                    status = slave.get('status', 'OFFLINE')
                    card.update_status(status == 'BAGLI')
                else:
                    # Master listesinde yok ama HELLO ile oluşturulmuş — offline işaretle
                    card.update_status(False)
            
            # 2. MAC bilgisini güncelle (_known_macs)
            for slave in slaves:
                mac = slave.get('mac', '')
                name = slave.get('name', '')
                if mac and name:
                    self._known_macs[mac] = name
            
            self.log(f"{len(slaves)} cihaz güncellendi")
            
        except Exception as e:
            _logger.error("Grid Update Error: %s", e)
            self.log(f"Grid Güncelleme Hatası: {e}")

    def on_device_selected(self, device_name, device_mac):
        """Handle device card selection - Open detail dialog (non-modal)"""
        self.selected_device = device_name
        self.log(f"Opening detail view: {device_name}")
        
        # Close existing detail dialog if one is already open
        if self.current_detail_dialog:
            self.current_detail_dialog.close()
        
        # Ensure buffer exists
        if device_name not in self.device_buffers:
            self.device_buffers[device_name] = {'time': [], 'pressure': [], 'state': [], 'start_ms': None, 'is_testing': False, 'last_graph_ms': 0}
            
        device_buffer = self.device_buffers[device_name]
        
        # Open device detail dialog (non-modal so main window stays interactive)
        dialog = DeviceDetailDialog(device_name, device_mac, self.esp32, self.db, device_buffer, self)
        self.current_detail_dialog = dialog
        self.current_detail_target = device_name
        dialog.finished.connect(self._on_detail_dialog_closed)
        dialog.show()

    def display_raw_data(self, data):
        """Display raw serial data in log"""
        self.log(f"RAW: {data}")

    def _on_detail_dialog_closed(self):
        """Cleanup after detail dialog closes"""
        self.current_detail_dialog = None
        self.current_detail_target = None

    def on_device_settings_clicked(self, device_name):
        """Open settings for the specific device from card click (non-modal)"""
        try:
            # Close existing settings dialog if one is already open
            if self.current_settings_dialog:
                self.current_settings_dialog.close()
                self.current_settings_dialog = None
            
            # Find device data from grid/list
            device_data = None
            
            if device_name in self.device_cards:
                card = self.device_cards[device_name]
                device_data = {'name': device_name, 'mac': card.mac}
            
            if not device_data:
                return

            # --- Dialog'u hemen AÇMA — önce kalibrasyon verisi iste ---
            self._pending_settings_data = device_data
            self.current_settings_target = device_name
            _target = self._resolve_target(device_name)
            self.current_settings_target_mac = _target
            
            # Enable Streaming on Device
            self.esp32.send_command(f"send {_target} STREAM")
            
            # Request Initial Calibration Data
            self.esp32.send_command(f"send {_target} {{\"cmd\":\"GET_CALIB\"}}")
            self._calib_retry_count = 0
            self._calib_retry_timer = QTimer(self)
            self._calib_retry_timer.setSingleShot(True)
            self._calib_retry_timer.timeout.connect(self._retry_get_calib)
            self._calib_retry_timer.start(1500)  # 1.5s sonra cevap gelmediyse tekrar sor
            
            self.log(f"Kalibrasyon verisi isteniyor [{device_name}]...", color="#D97706")
                
        except Exception as e:
            self.log(f"Error in Settings: {e}")
            print(f"Settings Error: {e}")

    def _open_settings_dialog(self, calib_data=None):
        """Kalibrasyon verisi geldikten sonra (veya timeout'ta) dialog'u aç."""
        device_data = getattr(self, '_pending_settings_data', None)
        device_name = self.current_settings_target
        if not device_data or not device_name:
            return
        
        # Dialog zaten açıksa tekrar açma
        if self.current_settings_dialog and self.current_settings_dialog.isVisible():
            return
        
        dialog = DeviceSettingsDialog(device_data, self.auth, self, calib_data=calib_data)
        
        # Connect Zero Request
        dialog.zero_requested.connect(lambda type: self.send_zero_command(device_name, type))
        
        self.current_settings_dialog = dialog
        dialog.finished.connect(self._on_settings_dialog_finished)
        dialog.show()
        self._pending_settings_data = None

    def _retry_get_calib(self):
        """GET_CALIB cevabı gelmediyse tekrar sor (max 3 deneme), sonra QMessageBox göster"""
        # Dialog zaten açıldıysa (veri geldi), dur
        if self.current_settings_dialog and self.current_settings_dialog.isVisible():
            if self.current_settings_dialog._calib_received:
                return
        # Pending state yoksa zaten iptal edilmiş
        if not getattr(self, '_pending_settings_data', None) and not self.current_settings_dialog:
            return
        self._calib_retry_count += 1
        if self._calib_retry_count > 3:
            # Tüm retry'lar başarısız — QMessageBox ile kullanıcıya sor
            self._show_calib_retry_dialog()
            return
        _target = getattr(self, 'current_settings_target_mac', None)
        if _target:
            self.log(f"GET_CALIB tekrar sorgulanıyor... (deneme {self._calib_retry_count})", color="#D97706")
            self.esp32.send_command(f"send {_target} {{\"cmd\":\"GET_CALIB\"}}")
            self._calib_retry_timer.start(1500)  # Bir sonraki retry

    def _show_calib_retry_dialog(self):
        """Kalibrasyon verisi alınamadı — Tekrar Dene / İptal dialogı göster."""
        _target = getattr(self, 'current_settings_target_mac', None)
        while True:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Kalibrasyon Verisi")
            msg.setText("Cihazdan kalibrasyon verisi alınamadı.")
            msg.setInformativeText("Tekrar denemek ister misiniz?")
            retry_btn = msg.addButton("Tekrar Dene", QMessageBox.AcceptRole)
            cancel_btn = msg.addButton("İptal", QMessageBox.RejectRole)
            msg.setDefaultButton(retry_btn)
            msg.exec_()
            
            if msg.clickedButton() == cancel_btn:
                # İptal — her şeyi temizle
                self._pending_settings_data = None
                self.current_settings_target = None
                self.current_settings_target_mac = None
                self.log("Kalibrasyon sorgusu iptal edildi.", color="#6B7280")
                return
            
            # Tekrar Dene — GET_CALIB gönder ve kısa süre bekle
            if _target:
                self.log("GET_CALIB tekrar gönderiliyor...", color="#D97706")
                self.esp32.send_command(f"send {_target} {{\"cmd\":\"GET_CALIB\"}}")
                # Kısa bekle (processEvents ile UI donmasın)
                import time as _time
                for _ in range(15):  # 1.5s (15 x 100ms)
                    QTimer.singleShot(0, lambda: None)
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                    _time.sleep(0.1)
                    # Veri geldiyse dialog açılmış olabilir
                    if self.current_settings_dialog and self.current_settings_dialog.isVisible():
                        return  # Başarılı — dialog açıldı
            # Veri hala gelmediyse döngü devam eder, tekrar QMessageBox gösterir

    def _on_settings_dialog_finished(self, result):
        """Handle settings dialog closed — apply accepted changes"""
        dialog = self.current_settings_dialog
        device_name = self.current_settings_target
        
        # Stop retry timer
        if hasattr(self, '_calib_retry_timer') and self._calib_retry_timer:
            self._calib_retry_timer.stop()
        
        # Cleanup references
        self.current_settings_dialog = None
        self.current_settings_target = None
        self.current_settings_target_mac = None
        
        if not dialog or result != QDialog.Accepted:
            return
        
        try:
            # 1. Rename if changed
            _mac_target = self._resolve_target(device_name)
            if dialog.new_name and dialog.new_name != device_name:
                self.log(f"İsim değiştiriliyor: {device_name} -> {dialog.new_name}")
                self.esp32.send_command(f"send {_mac_target} {{\"cmd\":\"SET_NAME\",\"name\":\"{dialog.new_name}\"}}")
                time.sleep(0.1)
                self.esp32.set_name(device_name, dialog.new_name)
                
            # 2. Calibration (MAC hedef değişmez, isim değişse bile)
            
            # Send Seal Calibration
            gasket = dialog.calib_gasket
            if gasket:
                 self.log(f"Kalibrasyon (Conta): Ofset={gasket['offset']}, Çarpan={gasket['multiplier']}")
                 gf = gasket["multiplier"] / 100.0
                 seal_cmd = f'{{"cmd":"SET_CALIB", "type":"SEAL", "offset":{gasket["offset"]}, "mult":{gf}}}'
                 self.esp32.send_command(f"send {_mac_target} {seal_cmd}")
                 time.sleep(0.1)

            # Send Seal Pressure Set
            if dialog.seal_pressure_set is not None:
                 self.esp32.send_command(f"send {_mac_target} {{\"cmd\":\"SET_CONTA\",\"val\":{dialog.seal_pressure_set}}}")
                 time.sleep(0.1)
            
            # Send Glove (Eldiven - Pressure) Calibration
            glove = dialog.calib_glove
            if glove:
                 self.log(f"Kalibrasyon (Basınç): Ofset={glove['offset']}, Çarpan={glove['multiplier']}%")
                 # GUI %100.0 → float faktör: 100.0% → 1.0, 100.1% → 1.001
                 mult_hw = glove["multiplier"] / 100.0
                 cal_cmd = f'{{"cmd":"SET_CALIB", "type":"PRESSURE", "offset":{glove["offset"]}, "mult":{mult_hw}}}'
                 self.esp32.send_command(f"send {_mac_target} {cal_cmd}")
                 time.sleep(0.1)

            self.audit.log_action('DEVICE_SETTINGS_UPDATE', description=f"{device_name} settings updated")
            
            # Defer refresh to avoid crashing if objects are being cleaned up
            QTimer.singleShot(500, self.refresh_slave_list)
                
        except Exception as e:
            self.log(f"Error in Settings: {e}")
            print(f"Settings Error: {e}")

    def send_zero_command(self, target, sensor_type):
        """Send ZERO command to device"""
        # {"cmd":"ZERO", "type":"PRESSURE"}
        if sensor_type == "PRESSURE":
            cmd = '{"cmd":"ZERO", "type":"PRESSURE"}'
            self.esp32.send_command(f"send {self._resolve_target(target)} {cmd}")
            self.log(f"Sıfırlama Komutu Gönderildi -> {target} (Basınç)", "#9333EA")




    
    # --- Manual Sync Handler ---
    def _on_manual_sync_clicked(self, mac, name):
        """Cihaz kartındaki sync butonuna basıldı — bu cihazı kuyruğa ekle."""
        self.log(f"Manuel sync tetiklendi: {name} ({mac})", "#8B5CF6", bold=True)
        self._enqueue_device_sync(mac, name)

    # --- Test Button Handlers ---
    def on_device_mount(self, device_name):
        """Handle MOUNT signal from Device Card"""
        mount_time = datetime.now()
        # --- Reset PC graph buffer IN-PLACE (preserves dialog's buffer reference!) ---
        if device_name in self.device_buffers:
            buf = self.device_buffers[device_name]
            buf['time'].clear()
            buf['pressure'].clear()
            buf['start_ms'] = None
            buf['last_graph_ms'] = 0
            buf['is_testing'] = True
            buf['frozen'] = False
            buf['pc_start_time'] = None
            buf['start_time'] = mount_time  # Dialog uses this for timer start
        else:
            self.device_buffers[device_name] = {
                'time': [], 'pressure': [], 'start_ms': None,
                'is_testing': True, 'last_graph_ms': 0, 'frozen': False,
                'pc_start_time': None, 'start_time': mount_time
            }
        # --- Reset open detail dialog graph/timer if it belongs to this device ---
        if (self.current_detail_dialog and
                self.current_detail_dialog.isVisible() and
                self.current_detail_target == device_name):
            self.current_detail_dialog.reset_for_new_test()
        target = self._resolve_target(device_name)
        cmd = '{"cmd": "MOUNT"}'
        self.esp32.send_command(f"send {target} {cmd}")
        self.log(f"Montaj Komutu Gönderildi -> {device_name} ({target})", "#F59E0B")

    def on_device_test_start(self, device_name):
        """Handle START_TEST signal from Device Card"""
        # --- Reset PC graph buffer for fresh test (timer & graph start from 0) ---
        if device_name in self.device_buffers:
            buf = self.device_buffers[device_name]
            buf['time'].clear()
            buf['pressure'].clear()
            buf['start_ms'] = None
            buf['last_graph_ms'] = 0
            buf['pc_start_time'] = None
            buf['is_testing'] = True
            buf['frozen'] = False
        # --- Reset open detail dialog graph/timer ---
        if (self.current_detail_dialog and
                self.current_detail_dialog.isVisible() and
                self.current_detail_target == device_name):
            self.current_detail_dialog.reset_for_new_test()
        target = self._resolve_target(device_name)
        cmd = '{"cmd": "START_TEST"}'
        self.esp32.send_command(f"send {target} {cmd}")
        self.log(f"Test Başlatma Komutu Gönderildi -> {device_name} ({target})", "#10B981")

    def on_device_dismount(self, device_name):
        # --- Clear start_time in buffer so timer doesn't restart after dismount ---
        if device_name in self.device_buffers:
            self.device_buffers[device_name]['start_time'] = None
            self.device_buffers[device_name]['is_testing'] = False
        # --- Stop dialog timer immediately ---
        if (self.current_detail_dialog and
                self.current_detail_dialog.isVisible() and
                self.current_detail_target == device_name):
            self.current_detail_dialog.on_dismount()
        target = self._resolve_target(device_name)
        cmd = '{"cmd": "DISMOUNT"}'
        self.esp32.send_command(f"send {target} {cmd}")
        self.log(f"Conta Indirme (Dismount) Komutu Gonderildi -> {device_name} ({target})", "#DC2626")

    def on_device_test_abort(self, device_name):
        """Handle ABORT signal from Device Card"""
        target = self._resolve_target(device_name)
        cmd = '{"cmd": "ABORT"}'
        self.esp32.send_command(f"send {target} {cmd}")
        self.log(f"Test İptal Komutu Gönderildi -> {device_name} ({target})", "#EF4444")

    # Legacy simulation methods removed.


    def _resolve_target(self, device_name: str) -> str:
        """device_name → MAC adresi çözümler. Bulamazsa device_name döner (fallback)."""
        if device_name in self.device_cards:
            mac = self.device_cards[device_name].mac
            if mac:
                return mac
        # _known_macs ters harita: mac→name, name ile MAC bul
        for mac, name in self._known_macs.items():
            if name == device_name:
                return mac
        return device_name

    def _get_selected_card(self):
        """Helper: Get selected device card or none"""
        if self.selected_device and self.selected_device in self.device_cards:
            return self.device_cards[self.selected_device]
        # Fallback to first if only one?
        if len(self.device_cards) == 1:
            return list(self.device_cards.values())[0]
        return None

    def _process_message_buffer(self):
        if not self.stream_message_buffer:
            return
        with self.buffer_lock:
            messages = self.stream_message_buffer[:]
            self.stream_message_buffer.clear()
        for message, color in messages[-10:]:
            self.traffic_message.emit(message, color)

    def broadcast_user_pins(self):
        """Tüm bağlı slave cihazlara CRC kontrolü ile PIN sync tetikle (cihaz açılışındaki akışın aynısı)."""
        try:
            if not self.esp32.slave_devices:
                self.log("broadcast_user_pins: Bağlı slave yok, komut gönderilmedi.", "#D97706")
                return

            self._calculate_user_pin_crc()
            triggered = 0
            for slave in self.esp32.slave_devices:
                mac = slave.get('mac', '')
                if not mac:
                    continue
                # Her cihaza GET_PIN_CRC gönder — PIN_CRC_REPLY handler CRC karşılaştırıp gerekirse PIN push yapacak
                delay = triggered * 500
                QTimer.singleShot(delay, lambda m=mac: self.esp32.send_command(f'send {m} {{"cmd":"GET_PIN_CRC"}}'))
                triggered += 1

            self.log(f"PIN CRC kontrolü {triggered} cihaza gönderiliyor...", "#059669")
        except Exception as e:
            self.log(f"broadcast_user_pins hatası: {e}", "#DC2626")
