from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
                             QMessageBox, QAbstractItemView)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush
from .port_registration_dialog import PortRegistrationDialog

class RFIDManagementDialog(QDialog):
    """
    Dialog for managing RFID tags on a Slave device.
    Lists tags, allows sync, and assigning recipes.
    """
    
    # Signal to request sync from main app
    sync_requested = pyqtSignal(str) # device_name
    # Signal to assign config (tag_id, port, recipe_str)
    assign_config_requested = pyqtSignal(str, str, int, str) # device_name, tag_id, port, recipe_str
    
    def __init__(self, device_name, current_recipe_str, parent=None):
        super().__init__(parent)
        self.device_name = device_name
        self.current_recipe_str = current_recipe_str
        self.setWindowTitle(f"RFID Yönetimi - {device_name}")
        self.setMinimumSize(700, 450)
        
        self.tags = {} # ID -> Data
        
        self.init_ui()
        self.apply_styles()
        
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Header
        header = QLabel(f"Cihaz: {self.device_name}")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2937;")
        layout.addWidget(header)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["RFID (Hex)", "İsim", "Durum", "Port"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)
        
        # Info Label
        self.info_lbl = QLabel("Listeyi güncellemek için 'Yenile' butonuna basınız.")
        self.info_lbl.setStyleSheet("color: #6B7280; font-style: italic;")
        layout.addWidget(self.info_lbl)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.refresh_btn = QPushButton("🔄 Yenile (Sync)")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.request_sync)
        btn_layout.addWidget(self.refresh_btn)
        
        self.add_port_btn = QPushButton("➕ Port/Reçete Ata")
        self.add_port_btn.setCursor(Qt.PointingHandCursor)
        self.add_port_btn.clicked.connect(self.open_port_dialog)
        self.add_port_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #059669; }
        """)
        btn_layout.addWidget(self.add_port_btn)
        
        self.close_btn = QPushButton("Kapat")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.close_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
    def open_port_dialog(self):
        """Open dialog to assign port and recipe"""
        row = self.table.currentRow()
        rfid = ""
        
        if row >= 0:
            rfid = self.table.item(row, 0).text()
            
        dialog = PortRegistrationDialog(rfid, self.current_recipe_str, self)
        if dialog.exec_():
            # Get data and emit
            rfid_tag = dialog.rfid_tag
            port = dialog.port_number
            recipe = dialog.selected_recipe
            
            self.assign_config_requested.emit(self.device_name, rfid_tag, port, recipe)
        
    def apply_styles(self):
        self.setStyleSheet("""
            QDialog { background-color: white; }
            QTableWidget {
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                gridline-color: #F3F4F6;
            }
            QHeaderView::section {
                background-color: #F9FAFB;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #E5E7EB;
                font-weight: 600;
                color: #374151;
            }
            QPushButton {
                padding: 8px 16px;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                background-color: white;
                color: #374151;
            }
            QPushButton:hover { background-color: #F9FAFB; }
        """)
        
    def request_sync(self):
        self.table.setRowCount(0)
        self.tags.clear()
        self.info_lbl.setText("Senkronizasyon başladı...")
        self.sync_requested.emit(self.device_name)
        
    def add_tag(self, tag_data):
        """
        Add or update tag in list
        tag_data: {'rfid': '0x...', 'name': '...', 'admin': 'true'/'false', 'port': 5}
        """
        rfid = tag_data.get('rfid', '???')
        
        # Avoid duplicates in visual list
        rows = self.table.rowCount()
        found = False
        row = 0
        for r in range(rows):
            if self.table.item(r, 0).text() == rfid:
                row = r
                found = True
                break
        
        if not found:
            row = rows
            self.table.insertRow(row)
            
        # 0: RFID
        self.table.setItem(row, 0, QTableWidgetItem(rfid))
        
        # 1: Name
        name = tag_data.get('name', '')
        self.table.setItem(row, 1, QTableWidgetItem(name))
        
        # 2: Status (Admin/User)
        is_admin_raw = tag_data.get('admin', False)
        is_admin = str(is_admin_raw).lower() == 'true' if isinstance(is_admin_raw, str) else bool(is_admin_raw)
        
        status_item = QTableWidgetItem("Yönetici" if is_admin else "Kullanıcı")
        if is_admin:
            status_item.setForeground(QBrush(QColor("#DC2626")))
            status_item.setFont(self.font()) 
        else:
            status_item.setForeground(QBrush(QColor("#059669")))
        self.table.setItem(row, 2, status_item)
        
        # 3: Port
        port = tag_data.get('port', 0)
        self.table.setItem(row, 3, QTableWidgetItem(str(port) if port != 0 else "-"))
        
        self.info_lbl.setText(f"Toplam {self.table.rowCount()} kart bulundu.")
        
    def assign_current_recipe(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Uyarı", "Lütfen listeden bir kart seçiniz.")
            return
            
        rfid = self.table.item(row, 0).text()
        
        confirm = QMessageBox.question(self, "Onay", 
                                       f"Seçili karta ({rfid}) şu anki reçete değerleri yazılsın mı?\n\n"
                                       f"Reçete: {self.current_recipe_str}",
                                       QMessageBox.Yes | QMessageBox.No)
                                       
        if confirm == QMessageBox.Yes:
            self.assign_recipe_requested.emit(self.device_name, rfid, self.current_recipe_str)
