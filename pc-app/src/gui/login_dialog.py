"""
Login Dialog
Secure user authentication interface
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QMessageBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QPixmap, QIcon
import os


class LoginDialog(QDialog):
    """Login dialog for user authentication"""
    
    def __init__(self, auth_manager, parent=None):
        super().__init__(parent)
        self.auth = auth_manager
        self.authenticated_user = None
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        self.setWindowTitle("Ultra GITS - Login")
        self.setFixedSize(550, 420) # Wider for horizontal logo
        self.setModal(True)
        self.setStyleSheet("background-color: white;") # Match logo background
        
        # Window icon
        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "lccLogo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        layout = QVBoxLayout()
        layout.setSpacing(5)
        layout.setContentsMargins(40, 20, 40, 20)
        
        # Logo — pinned to lccLogo.png (constant LCC brand mark).
        # Settings panel's "logo değiştir" writes to logo.{ext} and only
        # affects PDF reports / app header; the login screen must always
        # show the LCC brand (user requirement, 2026-06-16).
        self.logo_label = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), "..", "assets", "lccLogo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            self.logo_label.setPixmap(pixmap.scaled(480, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.logo_label.setText("LOGO")
        self.logo_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.logo_label)
        
        layout.addSpacing(5)
        
        # Title
        title = QLabel("Ultra GITS")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        subtitle = QLabel("21 CFR Part 11 Compliant")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        
        layout.addSpacing(20)
        
        # Username
        username_label = QLabel("Username:")
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username")
        layout.addWidget(username_label)
        layout.addWidget(self.username_input)
        
        # Password
        password_label = QLabel("Password:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Enter password")
        self.password_input.returnPressed.connect(self.login)
        layout.addWidget(password_label)
        layout.addWidget(self.password_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.login)
        self.login_button.setDefault(True)
        
        self.cancel_button = QPushButton("Exit")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.login_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # Set focus to username
        self.username_input.setFocus()
    
    def login(self):
        """Perform login authentication"""
        username = self.username_input.text().strip()
        password = self.password_input.text()
        
        if not username or not password:
            QMessageBox.warning(self, "Login Error", "Please enter both username and password.")
            return
        
        success, message, user = self.auth.login(username, password)
        
        if success:
            self.authenticated_user = user
            QMessageBox.information(self, "Login Successful", 
                                   f"Welcome, {user['full_name']}!\nRole: {user['role']}")
            self.accept()
        else:
            QMessageBox.critical(self, "Login Failed", message)
            self.password_input.clear()
            self.password_input.setFocus()
