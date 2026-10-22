from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, 
                             QDialogButtonBox, QLabel, QComboBox, QMessageBox)
from PyQt5.QtCore import Qt

class PortRegistrationDialog(QDialog):
    """
    Dialog for registering a new port assignment for an RFID tag.
    Fields:
    - Port Number (e.g. "Port 01")
    - RFID Tag (ReadOnly or Manual)
    - Recipe (Selection)
    """
    
    def __init__(self, rfid_tag, current_recipe_str, database=None, parent=None):
        super().__init__(parent)
        self.rfid_tag = rfid_tag
        self.recipe_str = current_recipe_str
        self.db = database
        self.port_number = 0
        self.selected_recipe = None
        
        self.setWindowTitle("Yeni Port Ekle")
        self.setFixedWidth(400)

        # Smart Port Assignment: Find first missing number
        suggested_port = 1
        if self.db:
            all_ports = self.db.get_all_ports()
            used_numbers = sorted([int(p['name'].replace('Port ', '')) for p in all_ports if 'Port ' in p['name'] and p['name'].replace('Port ', '').isdigit()])
            
            # Find gap in sequence
            for num in used_numbers:
                if num == suggested_port:
                    suggested_port += 1
                else:
                    break # Gap found
        
        self.suggested_port = suggested_port
        
        self.init_ui()
        self.apply_styles()
        
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Helper text
        info_lbl = QLabel("Not: RF ID ve Reçete alanları zorunludur.")
        info_lbl.setStyleSheet("color: #6B7280; font-style: italic; font-size: 12px;")
        layout.addWidget(info_lbl)
        
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # Port Number
        self.port_input = QLineEdit(str(self.suggested_port) if self.suggested_port else "")
        self.port_input.setPlaceholderText("Örn: 12 veya 3/5")
        form_layout.addRow("Port Numarası:", self.port_input)
        
        # RFID Tag
        self.rfid_input = QLineEdit(self.rfid_tag)
        self.rfid_input.setPlaceholderText("RFID Etiket No (Zorunlu)")
        # If passed, make read only? Or allow edit? 
        # User screenshot shows it as input. Let's allow edit but maybe highlight it?
        if self.rfid_tag:
            self.rfid_input.setReadOnly(True)
            self.rfid_input.setStyleSheet("background-color: #F3F4F6; color: #374151;")
        else:
            self.rfid_input.setStyleSheet("border: 1px solid #F59E0B;") # Orange border as hint
            
        form_layout.addRow("RF ID NO: *", self.rfid_input)
        
        # Recipe
        self.recipe_combo = QComboBox()
        self.recipe_combo.addItem("--- Reçete Seçin ---", None)
        # We should ideally list available recipes.
        # But for now we only have "Current Recipe" from the dashboard.
        # Let's add "Current Dashboard Recipe" as option.
        if self.recipe_str:
             self.recipe_combo.addItem(f"Mevcut Ayarlar ({self.recipe_str})", self.recipe_str)
        
        # Add all recipes from DB
        if self.db:
            recipes = self.db.get_all_recipes()
            for r in recipes:
                # Filter inactive recipes
                if not r.get('is_active', True):
                    continue
                # Görev 7: Hayalet reçete "4545" filtreleme
                if r.get('name') == '4545':
                    continue
                    
                # Format recipe string: 7 fields
                # Mapping: t1-p1-t2-p2-p6(failTh)-p7(testDur)-p8(succDrop)
                r_str = f"{r.get('t1_inflation', 10)}-{r.get('p1_pressure', 3000)}-{r.get('t2_stabilization', 5)}-{r.get('p2_hysteresis', 2800)}-{r.get('p3_limit', 150)}-{r.get('t3_measurement', 30)}-{r.get('p8_success_drop', 200)}"
                self.recipe_combo.addItem(f"{r['name']} ({r_str})", r_str)
        
        if self.recipe_combo.count() > 1:
            self.recipe_combo.setCurrentIndex(1)
            
        form_layout.addRow("Reçete: *", self.recipe_combo)
        
        layout.addLayout(form_layout)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
        
    def validate_and_accept(self):
        # Validate Port — format: "sol/sag" (örn: 3/5) veya sadece sayı (örn: 12)
        port_txt = self.port_input.text().strip()
        # Remove "Port " prefix if user typed it
        if port_txt.lower().startswith("port"):
            port_txt = port_txt[4:].strip()
        
        import re
        port_match = re.match(r'^(\d{1,2})\s*/\s*(\d{1,2})$', port_txt)
        single_match = re.match(r'^(\d{1,2})$', port_txt)
        
        if port_match:
            left = int(port_match.group(1))
            right = int(port_match.group(2))
            if left < 1 or left > 99 or right < 1 or right > 99:
                QMessageBox.warning(self, "Hata", "Port numarası sol ve sağ değerleri 1-99 arasında olmalıdır.")
                return
            self.port_number = (left << 8) | right
            target_name = f"Port {left}/{right}"
        elif single_match:
            port_val = int(single_match.group(1))
            if port_val < 1 or port_val > 99:
                QMessageBox.warning(self, "Hata", "Port numarası 1-99 arasında olmalıdır.")
                return
            self.port_number = port_val
            target_name = f"Port {port_val}"
        else:
            QMessageBox.warning(self, "Hata", "Lütfen geçerli bir port numarası giriniz (örn: 12 veya 3/5).")
            return

        # Check for duplicate port number (if DB is available)
        if self.db:
            all_ports = self.db.get_all_ports()
            existing = next((p for p in all_ports if p['name'] == target_name), None)
            
            if existing:
                QMessageBox.warning(self, "Port Mevcut", 
                                  f"{target_name} zaten kullanımda (RFID: {existing.get('rfid_tag', 'Yok')}).\n"
                                  "Bu portu kullanmak için önce mevcut kaydı silmelisiniz.")
                return

        # Validate RFID
        if not self.rfid_input.text().strip():
             QMessageBox.warning(self, "Hata", "RFID Etiket No zorunludur.")
             return
        self.rfid_tag = self.rfid_input.text().strip()
        
        # Validate Recipe
        if self.recipe_combo.currentIndex() <= 0:
             QMessageBox.warning(self, "Hata", "Lütfen bir reçete seçiniz.")
             return
        
        self.selected_recipe = self.recipe_combo.currentData()
        
        self.accept()

    def apply_styles(self):
        self.setStyleSheet("""
            QDialog { background-color: white; }
            QLabel { font-size: 13px; color: #374151; }
            QLineEdit {
                padding: 6px;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                background-color: white;
            }
            QComboBox {
                padding: 6px;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                background-color: white;
            }
            QDialogButtonBox QPushButton {
                padding: 6px 16px;
                border-radius: 4px;
                background-color: white;
                border: 1px solid #D1D5DB;
            }
            QDialogButtonBox QPushButton:hover {
                 background-color: #F3F4F6;
            }
        """)
