"""
RFID Management Panel
View and manage RFID tags assigned to ports
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QHeaderView,
                             QTableWidget, QTableWidgetItem, QLabel, QPushButton,
                             QAbstractItemView, QMessageBox, QInputDialog)
from PyQt5.QtCore import Qt
from gui.styles import Styles

class RFIDPanel(QWidget):
    """
    Panel to view port information (Port No, RFID, Recipe).
    Supports multi-selection and batch recipe assignment.
    """
    
    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.db = database
        self.init_ui()
        self.refresh_list()
        
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Compact Header
        header_layout = QHBoxLayout()
        title = QLabel("Port Bilgileri")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2937;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(32, 32)
        refresh_btn.setStyleSheet(Styles.get_button_style("secondary"))
        refresh_btn.setToolTip("Listeyi Yenile")
        refresh_btn.clicked.connect(self.refresh_list)
        header_layout.addWidget(refresh_btn)
        
        layout.addLayout(header_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Port No", "RFID No", "Reçete"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # Enable Multi-Selection
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        
        self.table.setStyleSheet(Styles.TABLE)
        self.table.setAlternatingRowColors(True)
        
        layout.addWidget(self.table)
        
        self.setLayout(layout)
        
    def refresh_list(self):
        """Load ports and details from DB"""
        self.table.setRowCount(0)
        ports = self.db.get_all_ports()

        # Port numarasına göre küçükten büyüğe sırala
        import re
        def _port_sort_key(p):
            nums = re.findall(r'\d+', p.get('name', ''))
            return int(nums[0]) if nums else 0
        ports.sort(key=_port_sort_key)
        
        for port in ports:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            # Sıra numarası
            seq_item = QTableWidgetItem(str(row + 1))
            seq_item.setTextAlignment(Qt.AlignCenter)
            seq_item.setForeground(Qt.gray)
            self.table.setItem(row, 0, seq_item)

            # Port No (Store ID in UserRole)
            name_item = QTableWidgetItem(port['name'])
            name_item.setData(Qt.UserRole, port['id']) # Store Port ID
            
            # Also store RFID and Recipe ID for "Port Placement" logic
            name_item.setData(Qt.UserRole + 1, port.get('rfid_tag'))
            name_item.setData(Qt.UserRole + 2, port.get('recipe_id'))
            
            self.table.setItem(row, 1, name_item)
            
            # RFID No
            rfid = port.get('rfid_tag', '-')
            if not rfid: rfid = '-'
            rfid_item = QTableWidgetItem(rfid)
            if rfid != '-':
                rfid_item.setForeground(Qt.darkGreen)
            self.table.setItem(row, 2, rfid_item)
            
            # Recipe - Use 'recipe_name' from DB join
            recipe_name = port.get('recipe_name', '-') 
            if not recipe_name: recipe_name = '-'
            self.table.setItem(row, 3, QTableWidgetItem(recipe_name))

