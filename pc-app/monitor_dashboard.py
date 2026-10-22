import sys
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QTextEdit, QLabel, 
                             QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
                             QGroupBox, QLineEdit)
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, Qt
from PyQt5.QtGui import QColor, QTextCursor
import json
import time
import datetime

# --- CONFIG ---
DEFAULT_BAUD = 115200

class SerialThread(QThread):
    data_received = pyqtSignal(str)
    connection_lost = pyqtSignal(str)

    def __init__(self, port, baud):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = False
        self.ser = None

    def run(self):
        try:
            # Passive Listener Mode: Do not assert DTR/RTS to avoid resetting target
            self.ser = serial.Serial(self.port, self.baud, timeout=1, dsrdtr=False, rtscts=False)
            self.ser.dtr = False
            self.ser.rts = False
            
            self.running = True
            while self.running:
                if self.ser.in_waiting:
                    try:
                        line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            self.data_received.emit(line)
                    except Exception as e:
                        pass # Ignore read errors in loop
                time.sleep(0.01)
        except serial.SerialException as e:
            self.connection_lost.emit(str(e))
        finally:
            if self.ser and self.ser.is_open:
                self.ser.close()

    def stop(self):
        self.running = False
        if self.ser:
            self.ser.close()
        self.wait()

class Dashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GLT v3 - Akıllı Sistem Monitörü")
        self.resize(1000, 700)
        
        self.serial_thread = None
        self.variables = {
            "Sistem Durumu": "Bekleniyor...",
            "Slave Sayısı": "0",
            "Son RFID": "-",
            "Tag Durumu": "Yok",
            "Recipe": "-",
            "WiFi Durumu": "Bilinmiyor"
        }

        self.init_ui()
        self.refresh_ports()

    def init_ui(self):
        # ... (keep existing UI code, just adding timer at the end of init_ui or in __init__)
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # --- TOP BAR (Connection) ---
        conn_group = QGroupBox("Bağlantı Ayarları")
        conn_layout = QHBoxLayout()
        
        self.port_combo = QComboBox()
        self.refresh_btn = QPushButton("Yenile")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "115200", "921600"])
        self.baud_combo.setCurrentText(str(DEFAULT_BAUD))
        
        self.connect_btn = QPushButton("BAĞLAN")
        self.connect_btn.setCheckable(True)
        self.connect_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 5px;")
        self.connect_btn.clicked.connect(self.toggle_connection)
        
        conn_layout.addWidget(QLabel("Port:"))
        conn_layout.addWidget(self.port_combo)
        conn_layout.addWidget(self.refresh_btn)
        conn_layout.addWidget(QLabel("Baud:"))
        conn_layout.addWidget(self.baud_combo)
        conn_layout.addWidget(self.connect_btn)
        conn_group.setLayout(conn_layout)
        
        main_layout.addWidget(conn_group)

        # --- MIDDLE SECTION (Variables & Logs) ---
        mid_layout = QHBoxLayout()

        # Left: Variables Table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Değişken", "Değer"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.update_table()
        mid_layout.addWidget(self.table, 1)

        # Right: Log Console
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas;")
        mid_layout.addWidget(self.console, 2)

        main_layout.addLayout(mid_layout)

        # --- BOTTOM BAR (Command) ---
        cmd_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Komut gönder... (Örn: list, help, send Slave1 ...)")
        self.cmd_input.returnPressed.connect(self.send_command)
        
        send_btn = QPushButton("GÖNDER")
        send_btn.clicked.connect(self.send_command)
        
        cmd_layout.addWidget(QLabel("Komut:"))
        cmd_layout.addWidget(self.cmd_input)
        cmd_layout.addWidget(send_btn)
        
        main_layout.addLayout(cmd_layout)
        
        # --- TAG REGISTRATION PANEL (Context-Sensitive) ---
        self.reg_group = QGroupBox("Hızlı Tag Kayıt (Algılanan Tanımsız Tag)")
        self.reg_group.setEnabled(False)
        reg_layout = QHBoxLayout()
        
        self.reg_rfid_label = QLabel("RFID: -")
        self.reg_port_input = QLineEdit()
        self.reg_port_input.setPlaceholderText("Port (1-50)")
        self.reg_port_input.setFixedWidth(80)
        
        self.reg_name_input = QLineEdit()
        self.reg_name_input.setPlaceholderText("Reçete İsmi")
        
        self.reg_btn = QPushButton("KAYDET VE REÇETE ATA")
        self.reg_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        self.reg_btn.clicked.connect(self.quick_register)
        
        reg_layout.addWidget(self.reg_rfid_label)
        reg_layout.addWidget(QLabel("Port:"))
        reg_layout.addWidget(self.reg_port_input)
        reg_layout.addWidget(QLabel("İsim:"))
        reg_layout.addWidget(self.reg_name_input)
        reg_layout.addWidget(self.reg_btn)
        self.reg_group.setLayout(reg_layout)
        
        main_layout.addWidget(self.reg_group)
        
        # Hints
        self.status_label = QLabel("DURUM: Hazır")
        self.status_label.setStyleSheet("font-weight: bold; color: #333;")
        main_layout.addWidget(self.status_label)

        # --- AUTO-DISCONNECT TIMER ---
        self.upload_check_timer = QTimer()
        self.upload_check_timer.timeout.connect(self.check_upload_flag)
        self.upload_check_timer.start(500) # Check every 500ms
        
        self.was_connected_before_upload = False

    def check_upload_flag(self):
        import os
        flag_file = "upload_mode.flag"
        # Check in current dir and parent dir
        exists = os.path.exists(flag_file) or os.path.exists(f"../{flag_file}")
        
        if exists:
            if self.serial_thread and self.serial_thread.running:
                self.log("[SİSTEM] Upload modu algılandı! Bağlantı geçici olarak kesiliyor...")
                self.stop_thread()
                self.connect_btn.setChecked(False)
                self.connect_btn.setText("UPLOAD MODU")
                self.connect_btn.setEnabled(False)
                self.status_label.setText("DURUM: UPLOAD BEKLENİYOR (Port Serbest)...")
                self.status_label.setStyleSheet("font-weight: bold; color: orange;")
                self.was_connected_before_upload = True
        else:
            if self.connect_btn.text() == "UPLOAD MODU":
                self.connect_btn.setEnabled(True)
                self.connect_btn.setText("BAĞLAN")
                self.status_label.setText("DURUM: Hazır")
                self.status_label.setStyleSheet("font-weight: bold; color: green;")
                self.log("[SİSTEM] Upload tamamlandı.")
                
                # Auto-reconnect if it was connected before
                if self.was_connected_before_upload:
                    self.connect_btn.setChecked(True)
                    self.toggle_connection()
                    self.was_connected_before_upload = False

    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for p in ports:
            self.port_combo.addItem(f"{p.device}")
        
        # Auto-select COM13 if present (Master default)
        idx = self.port_combo.findText("COM13")
        if idx >= 0:
            self.port_combo.setCurrentIndex(idx)

    def toggle_connection(self):
        if self.connect_btn.isChecked():
            # Connect
            port = self.port_combo.currentText()
            if not port: return
            
            baud = int(self.baud_combo.currentText())
            self.start_thread(port, baud)
            
            self.connect_btn.setText("BAĞLANTIYI KES (UPLOAD İÇİN)")
            self.connect_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
            self.variables["Sistem Durumu"] = "BAĞLI"
            self.log(f"[SİSTEM] {port} portuna bağlanıldı.")
        else:
            # Disconnect
            self.stop_thread()
            self.connect_btn.setText("BAĞLAN")
            self.connect_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
            self.variables["Sistem Durumu"] = "Bağlantı Kesildi"
            self.log("[SİSTEM] Bağlantı kesildi. Port serbest.")
            self.update_table()

    def start_thread(self, port, baud):
        self.serial_thread = SerialThread(port, baud)
        self.serial_thread.data_received.connect(self.process_data)
        self.serial_thread.connection_lost.connect(self.on_connection_lost)
        self.serial_thread.start()

    def stop_thread(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None

    def on_connection_lost(self, err):
        self.log(f"[HATA] Bağlantı koptu: {err}")
        self.connect_btn.setChecked(False)
        self.toggle_connection()

    def process_data(self, line):
        # 1. Log to console
        self.log(line)
        
        # 2. Parse Data
        self.parse_line(line)
        
        # 3. Update Table
        self.update_table()

    def parse_line(self, line):
        # Example Parsing Logic (Adapting to our firmware logs)
        
        # JSON detection
        if "{" in line and "}" in line:
            try:
                # Find JSON part
                start = line.find('{')
                end = line.rfind('}') + 1
                json_str = line[start:end]
                data = json.loads(json_str)
                
                if "cmd" in data:
                    cmd = data["cmd"]
                    
                    if cmd == "RFID_DETECTED":
                        rfid = data.get("rfid", "-")
                        auth = data.get("auth", False)
                        port = data.get("port", 0)
                        
                        self.variables["Son RFID"] = rfid
                        self.variables["Tag Durumu"] = "BAĞLI" if auth else "TANIMSIZ!"
                        
                        if not auth:
                            self.reg_group.setEnabled(True)
                            self.reg_rfid_label.setText(f"RFID: {rfid}")
                            self.status_label.setText(f"UYARI: Tanımsız Tag Algılandı! ({rfid})")
                            self.status_label.setStyleSheet("font-weight: bold; color: red;")
                        else:
                            self.reg_group.setEnabled(False)
                            self.status_label.setText(f"DURUM: Yetkili Tag Algılandı (Port {port})")
                            self.status_label.setStyleSheet("font-weight: bold; color: blue;")
                            
                    elif cmd == "RFID_REMOVED":
                        self.variables["Tag Durumu"] = "Uzaklaştırıldı"
                        self.reg_group.setEnabled(False)
                        self.status_label.setText("DURUM: Tag uzaklaştırıldı.")
                        self.status_label.setStyleSheet("font-weight: bold; color: gray;")
                            
            except Exception as e:
                self.log(f"[HATA] JSON İşleme: {e}")

        # Text Log parsing
        if "Slave added:" in line:
            try:
                parts = line.split("Slave added:")[1].strip()
                self.variables["Slave Sayısı"] = str(int(self.variables["Slave Sayısı"]) + 1)
            except:
                pass
                
        if "Parametre Ayarlandi:" in line:
            # key=recipe val=...
            if "key=recipe" in line:
                val = line.split("val=")[1].strip()
                self.variables["Recipe"] = val

    def update_table(self):
        self.table.setRowCount(len(self.variables))
        for i, (key, val) in enumerate(self.variables.items()):
            self.table.setItem(i, 0, QTableWidgetItem(key))
            self.table.setItem(i, 1, QTableWidgetItem(val))

    def log(self, text):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.console.moveCursor(QTextCursor.End)
        self.console.insertPlainText(f"[{timestamp}] {text}\n")
        self.console.moveCursor(QTextCursor.End)

    def send_command(self):
        cmd = self.cmd_input.text().strip()
        if not cmd: return
        
        if self.serial_thread and self.serial_thread.running:
            try:
                self.serial_thread.ser.write((cmd + "\n").encode('utf-8'))
                self.log(f">>> {cmd}")
                self.cmd_input.clear()
            except Exception as e:
                self.log(f"[HATA] Gönderilemedi: {e}")
        else:
            self.log("[UYARI] Bağlantı yok!")

    def quick_register(self):
        rfid = self.reg_rfid_label.text().replace("RFID: ", "").strip()
        port = self.reg_port_input.text().strip()
        name = self.reg_name_input.text().strip() or "Yeni_Tag"
        
        if not rfid or not port:
            self.log("[HATA] RFID veya Port eksik!")
            return
            
        # Format: {"cmd":"SET_TAG_CONFIG", "rfid":"...", "port":X, "recipe":"10-3000-5-2800-150-30-200", "recipe_name":"..."}
        # Use a default recipe for quick registration (7 fields: p1-p2-p3-p4-p6-p7-p8)
        default_recipe = "10-3000-5-2800-150-30-200"
        cmd = {
            "cmd": "SET_TAG_CONFIG",
            "rfid": rfid,
            "port": int(port),
            "recipe": default_recipe,
            "recipe_name": name
        }
        
        json_cmd = json.dumps(cmd)
        if self.serial_thread and self.serial_thread.running:
            self.serial_thread.ser.write((json_cmd + "\n").encode('utf-8'))
            self.log(f"[BİLGİ] Kayıt gönderildi: {rfid} -> Port {port}")
            self.reg_group.setEnabled(False)
            self.reg_port_input.clear()
            self.reg_name_input.clear()
        else:
            self.log("[UYARI] Bağlantı yok, gönderilemedi!")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Dashboard()
    window.show()
    sys.exit(app.exec_())
