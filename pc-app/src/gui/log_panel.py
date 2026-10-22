"""
Log Records Panel
View system audit trail and event logs
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QHeaderView,
                             QTableWidget, QTableWidgetItem, QLabel, QPushButton,
                             QComboBox, QDateEdit, QMessageBox)
from PyQt5.QtCore import Qt, QDate
import os
from gui.styles import Styles
from utils.date_format import format_datetime_tr

class LogPanel(QWidget):
    """
    Panel for viewing the Audit Trail log records.
    Features:
    - Table view of all actions
    - Filtering by date/action (future enhancement)
    - Refresh capability
    """
    
    def __init__(self, audit_manager, pdf_generator, parent=None):
        super().__init__(parent)
        self.audit = audit_manager
        self.pdf_gen = pdf_generator
        self.init_ui()
        # self.apply_styles()
        self.refresh_logs()
        
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Header
        header_layout = QHBoxLayout()
        title_layout = QVBoxLayout()
        title = QLabel("Sistem Kayıtları (Audit Trail)")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1F2937;")
        title_layout.addWidget(title)
        
        subtitle = QLabel("21 CFR Part 11 uyumlu olay ve işlem kayıtları")
        subtitle.setStyleSheet("font-size: 14px; color: #6B7280;")
        title_layout.addWidget(subtitle)
        header_layout.addLayout(title_layout)
        
        header_layout.addStretch()
        
        layout.addLayout(header_layout)

        # Filters Area
        filter_container = QWidget()
        filter_container.setStyleSheet("background-color: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 8px;")
        filter_layout = QHBoxLayout(filter_container)
        
        filter_layout.addWidget(QLabel("Başlangıç:"))
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("dd.MM.yyyy")
        self.start_date.setDate(QDate.currentDate().addDays(-7))
        filter_layout.addWidget(self.start_date)
        
        filter_layout.addSpacing(10)
        
        filter_layout.addWidget(QLabel("Bitiş:"))
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("dd.MM.yyyy")
        self.end_date.setDate(QDate.currentDate())
        filter_layout.addWidget(self.end_date)
        
        filter_layout.addSpacing(10)
        
        filter_btn = QPushButton("🔍 Filtrele")
        filter_btn.clicked.connect(self.refresh_logs)
        filter_btn.setFixedWidth(100)
        filter_btn.setStyleSheet(Styles.get_button_style("secondary"))
        filter_layout.addWidget(filter_btn)
        
        filter_layout.addStretch()
        
        self.pdf_btn = QPushButton("📄 PDF Raporu")
        self.pdf_btn.setCursor(Qt.PointingHandCursor)
        self.pdf_btn.clicked.connect(self.export_to_pdf)
        self.pdf_btn.setStyleSheet(Styles.get_button_style("primary"))
        filter_layout.addWidget(self.pdf_btn)
        
        layout.addWidget(filter_container)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Tarih", "Saat", "Kullanıcı", "İşlem", "Açıklama"])
        
        # Column Resizing - Better spacing for readability
        header = self.table.horizontalHeader()
        self.table.setColumnWidth(0, 120)  # Date
        self.table.setColumnWidth(1, 100)  # Time
        self.table.setColumnWidth(2, 120)  # User
        self.table.setColumnWidth(3, 180)  # Action
        header.setSectionResizeMode(4, QHeaderView.Stretch) # Description
        
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(Styles.TABLE)
        
        layout.addWidget(self.table)
        self.setLayout(layout)
        
    def refresh_logs(self):
        """Fetch and display logs with filters"""
        self.table.setRowCount(0)
        
        # Get date filters
        start = self.start_date.date().toString("yyyy-MM-dd")
        end = self.end_date.date().toString("yyyy-MM-dd")
        
        filters = {
            'date_from': f"{start}T00:00:00",
            'date_to': f"{end}T23:59:59",
            'categories': ['GLT', 'USER'],
        }
        
        records = self.audit.get_audit_trail(filters) 
        self.current_records = records # Store for PDF export
        
        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            # Format timestamp nicely - Türk formatı (DD.MM.YYYY HH:MM:SS)
            ts = record.get('timestamp', '')
            tr_dt = format_datetime_tr(ts, fallback='')
            if ' ' in tr_dt:
                date_str, time_str = tr_dt.split(' ', 1)
            else:
                date_str = tr_dt
                time_str = ''
            
            # Add items with center alignment
            item_date = QTableWidgetItem(date_str)
            item_date.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, item_date)
            
            item_time = QTableWidgetItem(time_str)
            item_time.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, item_time)
            
            item_user = QTableWidgetItem(record.get('username', 'Unknown'))
            item_user.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, item_user)
            
            action_item = QTableWidgetItem(record.get('action_type', '-'))
            action_item.setTextAlignment(Qt.AlignCenter)
            action_item.setFont(self.font()) 
            self.table.setItem(row, 3, action_item)
            
            desc = record.get('description', '')
            details = record.get('details', '')
            if details:
                desc += f" ({details})"
            
            item_desc = QTableWidgetItem(desc)
            item_desc.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, item_desc)

    def export_to_pdf(self):
        """Generate PDF report for currently filtered logs"""
        if not hasattr(self, 'current_records') or not self.current_records:
            QMessageBox.warning(self, "Uyarı", "Raporlanacak kayıt bulunamadı.")
            return

        try:
            filename = self.pdf_gen.generate_audit_trail_report(self.current_records)
            QMessageBox.information(self, "Başarılı", f"Audit Trail raporu oluşturuldu:\n{filename}")
            
            # Open the folder containing the report
            os.startfile(os.path.dirname(os.path.abspath(filename)))
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Rapor oluşturulurken bir hata oluştu: {e}")
            
    def apply_styles(self):
        # Deprecated
        pass
