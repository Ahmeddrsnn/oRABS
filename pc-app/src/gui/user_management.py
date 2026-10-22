"""
User Management Panel
Interface for managing users (Admin only)
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QLineEdit, QLabel, QMessageBox, QDialog, 
                             QFormLayout, QComboBox, QCheckBox, QDialogButtonBox,
                             QHeaderView)
from PyQt5.QtCore import Qt

from gui.styles import Styles

class UserManagementPanel(QWidget):
    """Admin panel for managing users"""
    
    def __init__(self, database, auth_manager, audit_manager, parent=None):
        super().__init__(parent)
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        
        self.init_ui()
        self.load_users()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # User List Group
        list_group = QGroupBox("Kullanıcı Listesi")
        list_group.setStyleSheet(Styles.GROUP_BOX)
        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(15, 25, 15, 15) # Top margin for title
        list_layout.setSpacing(10)
        
        # --- Buttons (Top) ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        # Refreh Button
        self.refresh_btn = QPushButton("🔄 Yenile")
        self.refresh_btn.setStyleSheet(Styles.get_button_style("secondary"))
        self.refresh_btn.setToolTip("Listeyi Yenile")
        self.refresh_btn.clicked.connect(self.load_users)
        
        # Add Button
        self.add_btn = QPushButton("➕ Yeni Kullanıcı")
        self.add_btn.setStyleSheet(Styles.get_button_style("primary"))
        self.add_btn.clicked.connect(self.add_user)
        
        # Edit Button
        self.edit_btn = QPushButton("✏️ Düzenle")
        self.edit_btn.setStyleSheet(Styles.get_button_style("secondary"))
        self.edit_btn.clicked.connect(self.edit_user)
        
        # Password Button
        self.password_btn = QPushButton("🔑 Şifre")
        self.password_btn.setStyleSheet(Styles.get_button_style("secondary"))
        self.password_btn.clicked.connect(self.change_password)
        
        # Status Button
        self.toggle_status_btn = QPushButton("👁️ Aktif/Pasif")
        self.toggle_status_btn.setStyleSheet(Styles.get_button_style("secondary"))
        self.toggle_status_btn.clicked.connect(self.toggle_user_status)
        
        # Add to Layout
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch() # Spacer
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.password_btn)
        btn_layout.addWidget(self.toggle_status_btn)
        
        list_layout.addLayout(btn_layout)
        
        # --- User Table (Bottom) ---
        self.user_table = QTableWidget()
        self.user_table.setColumnCount(6)
        self.user_table.setHorizontalHeaderLabels([
            "ID", "Kullanıcı Adı", "Tam İsim", "Rol", "E-posta", "Durum"
        ])
        self.user_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.user_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.user_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.user_table.setStyleSheet(Styles.TABLE)
        self.user_table.setAlternatingRowColors(True)
        
        list_layout.addWidget(self.user_table)
        
        list_group.setLayout(list_layout)
        
        layout.addWidget(list_group)
        self.setLayout(layout)

    def load_users(self):
        """Load all users from database"""
        users = self.db.get_all_users()
        self.user_table.setRowCount(len(users))
        
        for row, user in enumerate(users):
            self.user_table.setItem(row, 0, QTableWidgetItem(str(user['id'])))
            self.user_table.setItem(row, 1, QTableWidgetItem(user['username']))
            self.user_table.setItem(row, 2, QTableWidgetItem(user['full_name']))
            self.user_table.setItem(row, 3, QTableWidgetItem(user['role']))
            self.user_table.setItem(row, 4, QTableWidgetItem(user.get('email', '')))
            
            status = "Aktif" if user['is_active'] else "Pasif"
            status_item = QTableWidgetItem(status)
            if not user['is_active']:
                status_item.setForeground(Qt.red)
            self.user_table.setItem(row, 5, status_item)

    def get_selected_user_id(self):
        """Get ID of selected user"""
        selected = self.user_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Uyarı", "Lütfen bir kullanıcı seçin.")
            return None
        return int(self.user_table.item(selected[0].row(), 0).text())

    def get_selected_user_data(self):
        """Get data of selected user"""
        selected_id = self.get_selected_user_id()
        if not selected_id:
            return None
        
        users = self.db.get_all_users()
        return next((u for u in users if u['id'] == selected_id), None)

    def add_user(self):
        """Open dialog to add new user"""
        dialog = UserDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            success, result = self.db.create_user(
                data['username'], data['password'], data['full_name'], 
                data['role'], data['email']
            )
            
            if success:
                QMessageBox.information(self, "Başarılı", "Kullanıcı oluşturuldu.")
                self.audit.log_action("USER_CREATED", description=f"Created user: {data['username']}")
                self.load_users()
            else:
                QMessageBox.critical(self, "Hata", f"Kullanıcı oluşturulamadı:\n{result}")

    def edit_user(self):
        """Open dialog to edit user details"""
        user = self.get_selected_user_data()
        if not user:
            return
            
        dialog = UserDialog(self, user)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            # Only update allowable fields (no password here, no username usually)
            updates = {
                'full_name': data['full_name'],
                'role': data['role'],
                'email': data['email']
            }
            
            success, result = self.db.update_user(user['id'], updates)
            if success:
                QMessageBox.information(self, "Başarılı", "Kullanıcı güncellendi.")
                self.audit.log_action("USER_UPDATED", description=f"Updated user: {user['username']}")
                self.load_users()
            else:
                QMessageBox.critical(self, "Hata", f"Güncelleme başarısız:\n{result}")

    def change_password(self):
        """Open dialog to changes password"""
        user = self.get_selected_user_data()
        if not user:
            return
            
        password, ok = QInputDialog.getText(self, "Şifre Değiştir", 
                                          f"{user['username']} için yeni şifre:", 
                                          QLineEdit.Password)
        if ok and password:
            # Eski şifre ile aynı olamaz
            full_user = self.db.get_user_by_username(user['username'])
            if full_user and self.auth.verify_password(password, full_user['password_hash']):
                QMessageBox.warning(self, "Hata", "Yeni şifre eski şifre ile aynı olamaz.")
                return
            success, result = self.db.update_user(user['id'], {'password': password})
            if success:
                QMessageBox.information(self, "Başarılı", "Şifre değiştirildi.")
                self.audit.log_action("PASSWORD_RESET", description=f"Reset password for: {user['username']}")
            else:
                QMessageBox.critical(self, "Hata", result)

    def toggle_user_status(self):
        """Toggle active/inactive status"""
        user = self.get_selected_user_data()
        if not user:
            return
            
        if user['username'] == 'admin':
            QMessageBox.warning(self, "Hata", "Admin hesabı pasife alınamaz!")
            return
            
        new_status = 0 if user['is_active'] else 1
        action = "Pasif" if new_status == 0 else "Aktif"
        
        reply = QMessageBox.question(self, "Onay", 
                                   f"{user['username']} kullanıcısını {action} duruma getirmek istiyor musunuz?",
                                   QMessageBox.Yes | QMessageBox.No)
                                   
        if reply == QMessageBox.Yes:
            update_data = {'is_active': new_status}
            if new_status == 1:
                # Aktif yapılırken başarısız giriş sayacını sıfırla
                update_data['failed_login_attempts'] = 0
                update_data['locked_until'] = None
            success, result = self.db.update_user(user['id'], update_data)
            if success:
                self.load_users()
                self.audit.log_action("USER_STATUS_CHANGED", description=f"Changed status for {user['username']} to {action}")
            else:
                QMessageBox.critical(self, "Hata", result)


from PyQt5.QtWidgets import QInputDialog # Imported late to avoid circular if any but clean here

class UserDialog(QDialog):
    """Dialog for adding/editing users"""
    
    def __init__(self, parent=None, user_data=None):
        super().__init__(parent)
        self.user_data = user_data
        self.setWindowTitle("Kullanıcı Düzenle" if user_data else "Yeni Kullanıcı")
        self.setMinimumWidth(300)
        self.init_ui()
        
    def init_ui(self):
        layout = QFormLayout()
        
        self.username_edit = QLineEdit()
        if self.user_data:
            self.username_edit.setText(self.user_data['username'])
            self.username_edit.setReadOnly(True) # Cannot change username
        layout.addRow("Kullanıcı Adı:", self.username_edit)
        
        self.fullname_edit = QLineEdit()
        if self.user_data:
            self.fullname_edit.setText(self.user_data['full_name'])
        layout.addRow("Tam İsim:", self.fullname_edit)
        
        self.email_edit = QLineEdit()
        if self.user_data:
            self.email_edit.setText(self.user_data.get('email', ''))
        layout.addRow("E-posta:", self.email_edit)
        
        self.role_combo = QComboBox()
        self.role_combo.addItems(["Operator", "Supervisor", "Admin"])
        if self.user_data:
            self.role_combo.setCurrentText(self.user_data['role'])
        layout.addRow("Rol:", self.role_combo)
        
        if not self.user_data: # Only show password field for new users
            self.password_edit = QLineEdit()
            self.password_edit.setEchoMode(QLineEdit.Password)
            layout.addRow("Şifre:", self.password_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
        self.setLayout(layout)
    
    def validate_and_accept(self):
        """Validate required fields before accepting"""
        username = self.username_edit.text().strip()
        
        # Check username (required for new users)
        if not self.user_data and not username:
            QMessageBox.warning(self, "Uyarı", "Kullanıcı adı boş bırakılamaz!")
            self.username_edit.setFocus()
            return
        
        # Check password (required for new users) - 21 CFR Part 11 Compliant
        if not self.user_data:
            password = self.password_edit.text()
            if not password:
                QMessageBox.warning(self, "Uyarı", "Şifre boş bırakılamaz!")
                self.password_edit.setFocus()
                return
            
            # 21 CFR Part 11 Password Validation
            is_valid, error_message = self._validate_password_21cfr(password)
            if not is_valid:
                QMessageBox.warning(self, "Şifre Uyumsuz - 21 CFR Part 11", error_message)
                self.password_edit.setFocus()
                return
        
        self.accept()
    
    def _validate_password_21cfr(self, password: str) -> tuple:
        """
        Validate password against 21 CFR Part 11 requirements.
        Returns (is_valid, error_message)
        """
        import re
        
        errors = []
        
        # Minimum 8 characters
        if len(password) < 8:
            errors.append("• En az 8 karakter uzunluğunda olmalı")
        
        # At least one uppercase letter
        if not re.search(r'[A-Z]', password):
            errors.append("• En az bir büyük harf içermeli (A-Z)")
        
        # At least one lowercase letter
        if not re.search(r'[a-z]', password):
            errors.append("• En az bir küçük harf içermeli (a-z)")
        
        # At least one digit
        if not re.search(r'\d', password):
            errors.append("• En az bir rakam içermeli (0-9)")
        
        # At least one special character
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            errors.append("• En az bir özel karakter içermeli (!@#$%^&*...)")
        
        if errors:
            error_message = (
                "21 CFR Part 11 standartlarına uygun şifre gereksinimleri:\n\n"
                + "\n".join(errors)
                + "\n\nLütfen bu gereksinimleri karşılayan bir şifre girin."
            )
            return False, error_message
        
        return True, ""
        
    def get_data(self):
        data = {
            'username': self.username_edit.text().strip(),
            'full_name': self.fullname_edit.text().strip(),
            'email': self.email_edit.text().strip(),
            'role': self.role_combo.currentText()
        }
        if not self.user_data:
            data['password'] = self.password_edit.text()
        return data
