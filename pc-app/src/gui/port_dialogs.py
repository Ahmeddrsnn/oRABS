"""
Port Management Dialogs
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, 
                             QComboBox, QDialogButtonBox, QLabel, QMessageBox)
from PyQt5.QtCore import Qt

class AddPortDialog(QDialog):
    """Dialog to add a new glove port with RFID and Recipe (both required)"""
    
    def __init__(self, db, next_port_name, parent=None):
        super().__init__(parent)
        self.db = db
        self.next_port_name = next_port_name
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Yeni Port Ekle")
        self.setFixedWidth(400)
        
        layout = QVBoxLayout(self)
        
        # Info label
        info_label = QLabel("Not: RF ID ve Reçete alanları zorunludur.")
        info_label.setStyleSheet("color: #6B7280; font-style: italic; margin-bottom: 10px;")
        layout.addWidget(info_label)
        
        form = QFormLayout()
        
        self.name_input = QLineEdit(self.next_port_name)
        self.name_input.setPlaceholderText("Örn: Port 01")
        form.addRow("Port Numarası:", self.name_input)
        
        self.rfid_input = QLineEdit()
        self.rfid_input.setPlaceholderText("RFID Etiket No (Zorunlu)")
        self.rfid_input.setStyleSheet("border: 1px solid #F59E0B;")  # Highlight required
        form.addRow("RF ID NO: *", self.rfid_input)
        
        self.recipe_combo = QComboBox()
        self.load_recipes()
        form.addRow("Reçete: *", self.recipe_combo)
        
        layout.addLayout(form)
        
        # Buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        
    def load_recipes(self):
        """Populate recipes from database"""
        self.recipe_combo.addItem("--- Reçete Seçin ---", None)
        recipes = self.db.get_all_recipes()
        for r in recipes:
            self.recipe_combo.addItem(r['name'], r['id'])
            
    def set_rfid(self, rfid_value):
        """Set RFID value programmatically (for auto-fill from device)"""
        self.rfid_input.setText(rfid_value)
        self.rfid_input.setStyleSheet("border: 2px solid #10B981;")  # Green when filled
            
    def validate_and_accept(self):
        """Perform validation before accepting - RF ID and Recipe are REQUIRED"""
        port_name = self.name_input.text().strip()
        if not port_name:
            QMessageBox.warning(self, "Uyarı", "Lütfen port numarası girin.")
            return

        # Check for duplicate port name
        all_ports = self.db.get_all_ports()

        # ESP32 max_tags limiti kontrolü
        if len(all_ports) >= 50:
            QMessageBox.warning(self, "Limit Aşıldı",
                              "Maksimum 50 port ekleyebilirsiniz.\n"
                              "Yeni port eklemek için mevcut portlardan birini silin.")
            return

        existing = next((p for p in all_ports if p['name'].lower() == port_name.lower()), None)
        if existing:
            QMessageBox.warning(self, "Port Mevcut", 
                              f"'{port_name}' zaten kullanımda (RFID: {existing.get('rfid_tag', 'Yok')}).\n"
                              "Bu port numarasını kullanmak için önce mevcut kaydı silmelisiniz.")
            return
        
        # RF ID is required
        if not self.rfid_input.text().strip():
            QMessageBox.warning(self, "Uyarı", "RF ID alanı zorunludur.\nLütfen bir RF ID etiketi okutun veya manuel girin.")
            self.rfid_input.setFocus()
            return
            
        # Recipe is required
        if self.recipe_combo.currentData() is None:
            QMessageBox.warning(self, "Uyarı", "Reçete alanı zorunludur.\nLütfen bir reçete seçin.")
            self.recipe_combo.setFocus()
            return
            
        self.accept()
        
    def get_data(self):
        """Return the entered data"""
        return {
            'name': self.name_input.text().strip(),
            'rfid': self.rfid_input.text().strip(),
            'recipe_id': self.recipe_combo.currentData()
        }
