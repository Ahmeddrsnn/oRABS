"""
Report Viewer
Interface for viewing, searching, and generating reports
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QLineEdit, QLabel, QMessageBox, QDateEdit,
                             QHeaderView, QDialog, QTextEdit, QDialogButtonBox,
                             QComboBox)
from PyQt5.QtCore import Qt, QDate
from datetime import datetime
from utils.date_format import format_datetime_tr, now_tr
import os


from gui.styles import Styles

class ReportViewer(QWidget):
    """Widget for viewing and generating reports"""
    
    def __init__(self, database, pdf_generator, signature_manager, auth_manager, parent=None):
        super().__init__(parent)
        self.db = database
        self.pdf_gen = pdf_generator
        self.sig_manager = signature_manager
        self.auth = auth_manager
        
        self.init_ui()
        self.load_test_records()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Search Controls
        search_group = QGroupBox("Search Filters")
        search_group.setStyleSheet(Styles.GROUP_BOX)
        search_layout = QHBoxLayout()
        
        search_layout.addWidget(QLabel("Test ID:"))
        self.test_id_search = QLineEdit()
        self.test_id_search.setPlaceholderText("Search by Test ID")
        search_layout.addWidget(self.test_id_search)
        
        search_layout.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setDisplayFormat("dd.MM.yyyy")
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        search_layout.addWidget(self.date_from)
        
        search_layout.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setDisplayFormat("dd.MM.yyyy")
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        search_layout.addWidget(self.date_to)
        
        self.search_button = QPushButton("🔍 Search")
        self.search_button.setStyleSheet(Styles.get_button_style("secondary"))
        self.search_button.clicked.connect(self.load_test_records)
        search_layout.addWidget(self.search_button)
        
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)
        
        # Action Buttons (Moved to Top)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        self.open_folder_button = QPushButton("📂 Rapor Klasörünü Aç")
        self.open_folder_button.setStyleSheet(Styles.get_button_style("secondary"))
        self.open_folder_button.clicked.connect(self.open_reports_folder)
        
        self.open_batch_folder_button = QPushButton("📦 Batch Klasörünü Aç")
        self.open_batch_folder_button.setStyleSheet(Styles.get_button_style("secondary"))
        self.open_batch_folder_button.clicked.connect(self.open_batches_folder)
        
        self.generate_pdf_button = QPushButton("📄 Generate PDF")
        self.generate_pdf_button.setStyleSheet(Styles.get_button_style("primary"))
        self.generate_pdf_button.clicked.connect(self.generate_pdf_report)
        
        self.sign_button = QPushButton("✍️ Apply Signature")
        self.sign_button.setStyleSheet(Styles.get_button_style("success"))
        self.sign_button.clicked.connect(self.apply_signature)
        
        self.audit_button = QPushButton("📋 View Audit Trail")
        self.audit_button.setStyleSheet(Styles.get_button_style("secondary"))
        self.audit_button.clicked.connect(self.view_audit_trail)
        
        button_layout.addWidget(self.open_folder_button)
        button_layout.addWidget(self.open_batch_folder_button)
        button_layout.addWidget(self.generate_pdf_button)
        button_layout.addWidget(self.sign_button)
        button_layout.addWidget(self.audit_button)
        button_layout.addStretch()
        
        # Report language selector
        button_layout.addWidget(QLabel("Rapor Dili:"))
        self.report_lang_combo = QComboBox()
        self.report_lang_combo.addItem("Türkçe", "tr")
        self.report_lang_combo.addItem("English", "en")
        self.report_lang_combo.setFixedWidth(100)
        self.report_lang_combo.setStyleSheet("QComboBox { padding: 4px 8px; }")
        button_layout.addWidget(self.report_lang_combo)
        
        layout.addLayout(button_layout)
        
        # Test Records Table
        table_group = QGroupBox("Test Records")
        table_group.setStyleSheet(Styles.GROUP_BOX)
        table_layout = QVBoxLayout()
        table_layout.setContentsMargins(15, 25, 15, 15)
        
        self.records_table = QTableWidget()
        self.records_table.setColumnCount(10)  # 9 visible + 1 hidden ID
        self.records_table.setHorizontalHeaderLabels([
            "Test ID", "RFID", "Batch", "Reçete", "Tarih", "Saat", "Durum", "Sonuç", "Eylemler", ""
        ])
        # Tüm görünür sütunlar tabloyu eşit dolduracak şekilde genişlesin
        header = self.records_table.horizontalHeader()
        for col in range(9):  # 0-8 visible columns
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        self.records_table.setColumnHidden(9, True)  # Hidden ID
        
        self.records_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.records_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.records_table.setAlternatingRowColors(True)
        self.records_table.setStyleSheet(Styles.TABLE)
        # Task 5: Double-click ile PDF oluştur/aç
        self.records_table.doubleClicked.connect(self.generate_pdf_report)
        
        table_layout.addWidget(self.records_table)
        table_group.setLayout(table_layout)
        layout.addWidget(table_group)
        
        self.setLayout(layout)
    
    def load_test_records(self):
        """Load test records from database"""
        filters = {}
        
        test_id = self.test_id_search.text().strip()
        if test_id:
            filters['test_id'] = test_id
        
        filters['date_from'] = self.date_from.date().toString("yyyy-MM-dd")
        filters['date_to'] = self.date_to.date().toString("yyyy-MM-dd")
        
        records = self.db.get_test_records(filters)
        # Task 1: RUNNING testleri tabloda gösterme
        records = [r for r in records if r.get('test_status') != 'RUNNING']
        
        self.records_table.setRowCount(len(records))
        
        for row, record in enumerate(records):
            # Helper to create centered items
            def centered_item(text):
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(Qt.AlignCenter)
                return item

            # Col 0: Test ID
            self.records_table.setItem(row, 0, centered_item(record.get('test_id', '')))
            # Col 1: RFID (eski batch sütunundaki değer = glove_batch_number)
            self.records_table.setItem(row, 1, centered_item(record.get('glove_batch_number', '')))
            
            # Col 2: Batch — testin zamanına göre batch eşleştir
            test_time = record.get('test_start_time', '')
            batch_name = self.db.get_batch_for_test_time(test_time) if test_time else None
            self.records_table.setItem(row, 2, centered_item(batch_name if batch_name else 'OTO'))
            
            # Col 3: Reçete (eski Type = glove_type)
            self.records_table.setItem(row, 3, centered_item(record.get('glove_type', '')))
            
            # Split timestamp → Tarih + Saat (Türk formatı)
            ts = record.get('test_start_time', '')
            tr_dt = format_datetime_tr(ts, fallback='')
            if ' ' in tr_dt:
                date_str, time_str = tr_dt.split(' ', 1)
            else:
                date_str = tr_dt
                time_str = ''
            
            # Col 4: Tarih
            self.records_table.setItem(row, 4, centered_item(date_str))
            # Col 5: Saat
            self.records_table.setItem(row, 5, centered_item(time_str))
            # Col 6: Durum (eski Status = test_status)
            self.records_table.setItem(row, 6, centered_item(record.get('test_status', '')))
            # Col 7: Sonuç (eski Result = test_result) — PASS yeşil, FAIL kırmızı
            result_val = record.get('test_result', '')
            result_item = centered_item(result_val)
            if result_val == 'PASS':
                result_item.setForeground(Qt.darkGreen)
            elif result_val == 'FAIL':
                result_item.setForeground(Qt.red)
            self.records_table.setItem(row, 7, result_item)
            
            # Col 8: Eylemler — record ID stored here for display
            self.records_table.setItem(row, 8, centered_item(record.get('id', '')))
            
            # Col 9: Hidden ID (for selection logic)
            id_item = QTableWidgetItem(str(record.get('id', '')))
            self.records_table.setItem(row, 9, id_item)
    
    def get_selected_record_id(self):
        """Get selected record ID"""
        selected = self.records_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a test record")
            return None
        
        row = selected[0].row()
        record_id = int(self.records_table.item(row, 9).text())  # Hidden ID column
        return record_id
    
    def open_reports_folder(self):
        """Raporların kaydedildiği klasörü dosya yöneticisinde açar"""
        reports_dir = self.pdf_gen.output_dir
        if not os.path.exists(reports_dir):
            os.makedirs(reports_dir, exist_ok=True)
        os.startfile(reports_dir)
    
    def open_batches_folder(self):
        """Batch klasörünü dosya yöneticisinde açar"""
        batches_dir = self.pdf_gen.batch_output_dir
        if not os.path.exists(batches_dir):
            os.makedirs(batches_dir, exist_ok=True)
        os.startfile(batches_dir)

    def _open_pdf_inapp(self, pdf_path: str):
        """PDF'i uygulama içinde tam ekran görüntüleyicide aç.
        Görüntüleyici yüklenemezse (WebEngine yok vs.) sessizce sistem
        varsayılan uygulamasına fallback yapar."""
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Dosya Yok", f"PDF bulunamadı:\n{pdf_path}")
            return
        try:
            from gui.pdf_viewer_dialog import PdfViewerDialog
            PdfViewerDialog(pdf_path, parent=self).exec_()
        except Exception as e:
            # Fallback: sistem varsayılanı ile aç.
            try:
                os.startfile(pdf_path)
            except Exception:
                QMessageBox.critical(self, "Açılamadı",
                                     f"PDF açılamadı:\n{e}")

    def generate_pdf_report(self):
        """Generate PDF report for selected record"""
        record_id = self.get_selected_record_id()
        if not record_id:
            return
        
        # Get record and signatures
        records = self.db.get_test_records()
        record = next((r for r in records if r['id'] == record_id), None)
        
        if not record:
            QMessageBox.warning(self, "Error", "Record not found")
            return
        
        signatures = self.sig_manager.get_signatures_for_record('test_record', record_id)
        
        try:
            lang = self.report_lang_combo.currentData() or 'tr'
            pdf_path = self.pdf_gen.generate_test_report(record, signatures, lang=lang)

            # Open PDF inside the application (fullscreen viewer).
            self._open_pdf_inapp(pdf_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate PDF:\n{str(e)}")
    
    def apply_signature(self):
        """Apply electronic signature to selected record"""
        record_id = self.get_selected_record_id()
        if not record_id:
            return
        
        # Get password from user
        from PyQt5.QtWidgets import QInputDialog
        
        meaning, ok = QInputDialog.getText(self, "Signature Meaning",
                                          "Enter signature meaning (e.g., 'Reviewed by', 'Approved by'):")
        if not ok or not meaning:
            return
        
        password, ok = QInputDialog.getText(self, "Confirm Identity",
                                           "Enter your password to apply signature:",
                                           QLineEdit.Password)
        if not ok or not password:
            return
        
        success, message = self.sig_manager.create_signature('test_record', record_id, meaning, password)
        
        if success:
            QMessageBox.information(self, "Success", message)
            self.load_test_records()
        else:
            QMessageBox.critical(self, "Error", message)
    
    def view_audit_trail(self):
        """View and generate audit trail report with date filtering"""
        # Create a dialog for report configuration
        dialog = QDialog(self)
        dialog.setWindowTitle("Audit Trail Raporu")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        # Date selection
        date_group = QGroupBox("Tarih Aralığı")
        date_layout = QVBoxLayout()
        
        h_layout = QHBoxLayout()
        h_layout.addWidget(QLabel("Başlangıç:"))
        start_date = QDateEdit()
        start_date.setDisplayFormat("dd.MM.yyyy")
        start_date.setDate(QDate.currentDate().addMonths(-1))
        start_date.setCalendarPopup(True)
        h_layout.addWidget(start_date)
        
        h_layout.addWidget(QLabel("Bitiş:"))
        end_date = QDateEdit()
        end_date.setDisplayFormat("dd.MM.yyyy")
        end_date.setDate(QDate.currentDate())
        end_date.setCalendarPopup(True)
        h_layout.addWidget(end_date)
        
        date_layout.addLayout(h_layout)
        date_group.setLayout(date_layout)
        layout.addWidget(date_group)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        
        # Change OK button text to "Rapor Oluştur"
        buttons.button(QDialogButtonBox.Ok).setText("PDF Rapor Oluştur")
        
        layout.addWidget(buttons)
        dialog.setLayout(layout)
        
        if dialog.exec_() == QDialog.Accepted:
            try:
                date_from_str = start_date.date().toString("yyyy-MM-dd")
                date_to_str = end_date.date().toString("yyyy-MM-dd")
                
                # Fetch audit logs with date filter
                logs = self.db.get_audit_logs(limit=1000, start_date=date_from_str, end_date=date_to_str)
                
                if not logs:
                    QMessageBox.information(self, "Bilgi", "Seçilen tarih aralığında kayıt bulunamadı.")
                    return
                
                # Generate PDF
                lang = self.report_lang_combo.currentData() or 'tr'
                pdf_path = self.pdf_gen.generate_audit_trail_report(
                    logs, 
                    company_name=f"Audit Trail: {date_from_str} - {date_to_str}",
                    lang=lang
                )
                
                QMessageBox.information(self, "Başarılı", 
                                      f"Audit Trail raporu oluşturuldu:\n{pdf_path}")
                
                # Open PDF inside the application (fullscreen viewer).
                self._open_pdf_inapp(pdf_path)
                
            except Exception as e:
                QMessageBox.critical(self, "Hata", f"Rapor oluşturulurken hata oluştu:\n{str(e)}")
