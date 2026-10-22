"""
Force Password Change Dialog
Modal dialog to force user to change password
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, 
                             QLabel, QPushButton, QMessageBox, QHBoxLayout)
from PyQt5.QtCore import Qt

class ForcePasswordChangeDialog(QDialog):
    """Dialog forcing user to change password"""

    # Sebep sabitleri: farklı başlık/mesaj göstermek için
    REASON_FIRST_LOGIN = 'first_login'
    REASON_EXPIRED     = 'expired'

    def __init__(self, auth_manager, parent=None, reason: str = None):
        super().__init__(parent)
        self.auth = auth_manager
        self.reason = reason or self._detect_reason()

        self.setWindowTitle("Şifre Değişikliği Gerekli")
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.CustomizeWindowHint) # No close button
        self.setModal(True)
        self.setMinimumWidth(350)

        self.init_ui()

    def _detect_reason(self) -> str:
        """Sebep verilmezse auth.current_user üzerinden çıkar.

        Kullanıcının `password_changed_at` alanı varsa ve `created_at`'tan
        farklıysa → süre dolumu; aksi halde ilk giriş. Fallback: ilk giriş.
        """
        try:
            u = getattr(self.auth, 'current_user', None) or {}
            changed = u.get('password_changed_at')
            created = u.get('created_at')
            if changed and created and str(changed) != str(created):
                return self.REASON_EXPIRED
        except Exception:
            pass
        return self.REASON_FIRST_LOGIN

    def init_ui(self):
        layout = QVBoxLayout()

        # Info Message — sebep'e göre farklı metin
        if self.reason == self.REASON_EXPIRED:
            months = self._interval_months_hint()
            base = (
                "Şifrenizin geçerlilik süresi doldu.\n"
                "Güvenlik gereği yeni bir şifre belirlemeniz gerekmektedir."
            )
            if months:
                base += f"\n(Periyodik şifre değiştirme: her {months} ayda bir.)"
        else:
            base = (
                "Güvenlik gereği ilk girişinizde şifrenizi "
                "değiştirmeniz gerekmektedir."
            )
        msg = QLabel(base)
        msg.setWordWrap(True)
        msg.setStyleSheet("color: #003366; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(msg)
        
        # Form
        form_layout = QFormLayout()
        
        self.new_pass = QLineEdit()
        self.new_pass.setEchoMode(QLineEdit.Password)
        self.new_pass.setPlaceholderText("Yeni Şifre")
        form_layout.addRow("Yeni Şifre:", self.new_pass)
        
        self.confirm_pass = QLineEdit()
        self.confirm_pass.setEchoMode(QLineEdit.Password)
        self.confirm_pass.setPlaceholderText("Şifre Tekrar")
        form_layout.addRow("Tekrar:", self.confirm_pass)
        
        layout.addLayout(form_layout)
        
        # Policy Info
        policy_lbl = QLabel(
            "Şifre en az 8 karakter olmalı;\n"
            "Büyük harf, küçük harf, rakam ve özel karakter içermelidir."
        )
        policy_lbl.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(policy_lbl)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("Kaydet ve Giriş Yap")
        self.save_btn.clicked.connect(self.save_password)
        self.save_btn.setStyleSheet("background-color: #003366; color: white; padding: 5px;")
        self.save_btn.setDefault(True)  # Enter → Kaydet
        
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setAutoDefault(False)  # Enter ile seçilmesin
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
        # Her iki alanda da Enter → doğrudan kaydet
        self.new_pass.returnPressed.connect(self.save_password)
        self.confirm_pass.returnPressed.connect(self.save_password)
        
        # Focus ilk alana
        self.new_pass.setFocus()
        
    def save_password(self):
        new_pass = self.new_pass.text()
        confirm = self.confirm_pass.text()
        
        if not new_pass or not confirm or new_pass != confirm:
            QMessageBox.warning(self, "Hata", "Şifreler eşleşmiyor.")
            return
            
        # Validate policy
        valid, msg = self.auth.validate_password_policy(new_pass)
        if not valid:
            QMessageBox.warning(self, "Zayıf Şifre", msg)
            return

        # Eski şifre ile aynı olamaz
        if self.auth.current_user and self.auth.verify_password(new_pass, self.auth.current_user['password_hash']):
            QMessageBox.warning(self, "Hata", "Yeni şifre eski şifre ile aynı olamaz.")
            return
            
        # Update password via database (we need user_id)
        # Auth manager currently holds the logged in user
        if not self.auth.current_user:
            QMessageBox.critical(self, "Hata", "Oturum hatası.")
            self.reject()
            return
            
        # Update user
        user_id = self.auth.current_user['id']
        success, result = self.auth.db.update_user(user_id, {
            'password': new_pass,
            'must_change_password': 0
        })
        
        if success:
            QMessageBox.information(self, "Başarılı", "Şifreniz değiştirildi. Giriş yapılıyor...")
            self.accept()
        else:
            QMessageBox.critical(self, "Hata", f"Şifre değiştirilemedi:\n{result}")

    def _interval_months_hint(self) -> str:
        """system_settings.password_change_interval_months değerini oku."""
        try:
            db = getattr(self.auth, 'db', None)
            if not db:
                return ''
            v = str(db.get_setting(
                'password_change_interval_months', '3'
            )).strip()
            return v if v in ('3', '6', '9', '12') else ''
        except Exception:
            return ''
