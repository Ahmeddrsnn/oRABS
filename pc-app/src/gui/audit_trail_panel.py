"""
Audit Trail Panel (outer tab)
Centralised cross-application audit trail view: USER + GLT + ORAPS + SYSTEM.

USER-category records (login/logout/password/user-management) are surfaced in
every category filter except when the user explicitly narrows to GLT, ORAPS
or USER itself — in which case USER events are interleaved chronologically
with the selected scope so reviewers see who did what alongside the action.
"""

import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QHeaderView,
                             QTableWidget, QTableWidgetItem, QLabel, QPushButton,
                             QComboBox, QDateEdit, QMessageBox, QButtonGroup,
                             QRadioButton, QFrame)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor

from gui.styles import Styles
from utils.date_format import format_datetime_tr
from utils.translations import Translations


# Filter key -> SQL category list. USER is interleaved with GLT / ORAPS so
# operators see auth events alongside the scoped activity. LAF events are
# grouped under the ORABS (oraps) filter in the UI.
_CATEGORY_FILTERS = {
    'all':   None,                    # No filter -> everything
    'user':  ['USER'],
    'glt':   ['GLT', 'USER'],
    'oraps': ['ORAPS', 'LAF', 'USER'],
}

_CATEGORY_COLORS = {
    'USER':   QColor('#DBEAFE'),   # light blue
    'GLT':    QColor('#DCFCE7'),   # light green
    'ORAPS':  QColor('#FEF3C7'),   # light amber
    'LAF':    QColor('#FEF3C7'),   # light amber (shown as ORABS)
    'SYSTEM': QColor('#F3F4F6'),   # light grey
}

# UI display mapping: backend category -> user-facing label.
# Kod tabanı ORAPS/LAF olarak çalışmaya devam eder; kullanıcı her yerde ORABS görür.
_CATEGORY_DISPLAY = {
    'ORAPS': 'ORABS',
    'LAF':   'ORABS',
}


class AuditTrailPanel(QWidget):
    """Central audit trail viewer shown as an outer application tab.

    Parameters
    ----------
    category_filter : str | None
        If set (e.g. 'oraps'), the radio strip is hidden and the panel is
        locked to that category. Used to embed a scoped audit view inside
        an application tab (Oraps inner Audit Trail).
    """

    def __init__(self, audit_manager, pdf_generator, parent=None,
                 category_filter=None):
        super().__init__(parent)
        self.audit = audit_manager
        self.pdf_gen = pdf_generator
        self._current_lang = 'tr'
        self._locked_category = (
            category_filter.lower() if isinstance(category_filter, str) else None
        )
        self._current_filter = self._locked_category or 'all'
        self.current_records = []
        self._init_ui()
        self.refresh_logs()

    # ── UI ───────────────────────────────────────────────────────────
    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Header
        self._title = QLabel()
        self._title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1F2937;")
        layout.addWidget(self._title)

        self._subtitle = QLabel()
        self._subtitle.setStyleSheet("font-size: 14px; color: #6B7280;")
        layout.addWidget(self._subtitle)

        # Filter strip
        filter_container = QFrame()
        filter_container.setStyleSheet(
            "background-color: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 8px;"
        )
        filter_layout = QHBoxLayout(filter_container)

        # Category radio group
        self._cat_label = QLabel()
        filter_layout.addWidget(self._cat_label)

        self._cat_group = QButtonGroup(self)
        self._cat_buttons = {}
        for key in ('all', 'user', 'glt', 'oraps'):
            rb = QRadioButton()
            rb.setCursor(Qt.PointingHandCursor)
            self._cat_group.addButton(rb)
            self._cat_buttons[key] = rb
            filter_layout.addWidget(rb)
        # Check the default BEFORE wiring the toggled signal so we don't
        # trigger refresh_logs while the table widget hasn't been built yet.
        initial = self._locked_category if self._locked_category in self._cat_buttons else 'all'
        self._cat_buttons[initial].setChecked(True)
        for rb in self._cat_buttons.values():
            rb.toggled.connect(self._on_category_toggled)
        # When embedded with a locked category, hide the chooser entirely
        if self._locked_category is not None:
            self._cat_label.hide()
            for rb in self._cat_buttons.values():
                rb.hide()

        filter_layout.addSpacing(20)

        # Date filters
        self._start_label = QLabel()
        filter_layout.addWidget(self._start_label)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("dd.MM.yyyy")
        self.start_date.setDate(QDate.currentDate().addDays(-7))
        filter_layout.addWidget(self.start_date)

        filter_layout.addSpacing(10)

        self._end_label = QLabel()
        filter_layout.addWidget(self._end_label)
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("dd.MM.yyyy")
        self.end_date.setDate(QDate.currentDate().addDays(1))
        filter_layout.addWidget(self.end_date)

        filter_layout.addSpacing(10)

        self.filter_btn = QPushButton()
        self.filter_btn.clicked.connect(self.refresh_logs)
        self.filter_btn.setFixedWidth(110)
        self.filter_btn.setStyleSheet(Styles.get_button_style("secondary"))
        filter_layout.addWidget(self.filter_btn)

        filter_layout.addStretch()

        self.pdf_btn = QPushButton()
        self.pdf_btn.setCursor(Qt.PointingHandCursor)
        self.pdf_btn.clicked.connect(self.export_to_pdf)
        self.pdf_btn.setStyleSheet(Styles.get_button_style("primary"))
        filter_layout.addWidget(self.pdf_btn)

        layout.addWidget(filter_container)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        header = self.table.horizontalHeader()
        self.table.setColumnWidth(0, 110)  # Date
        self.table.setColumnWidth(1, 90)   # Time
        self.table.setColumnWidth(2, 130)  # User
        self.table.setColumnWidth(3, 90)   # Category
        self.table.setColumnWidth(4, 200)  # Action
        header.setSectionResizeMode(5, QHeaderView.Stretch)  # Description

        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(Styles.TABLE)

        layout.addWidget(self.table)
        self.setLayout(layout)

        # Initial language wiring
        self.apply_language(self._current_lang)

    # ── External API ─────────────────────────────────────────────────
    def apply_language(self, lang_code: str):
        """Re-translate static UI strings."""
        self._current_lang = lang_code
        t = Translations.t
        self._title.setText(t('audit_title', lang_code))
        self._subtitle.setText(t('audit_subtitle', lang_code))
        self._cat_label.setText(t('audit_filter_cat', lang_code))
        self._cat_buttons['all'].setText(t('audit_cat_all', lang_code))
        self._cat_buttons['user'].setText(t('audit_cat_user', lang_code))
        self._cat_buttons['glt'].setText(t('audit_cat_glt', lang_code))
        self._cat_buttons['oraps'].setText(t('audit_cat_oraps', lang_code))
        self._start_label.setText(t('audit_filter_start', lang_code))
        self._end_label.setText(t('audit_filter_end', lang_code))
        self.filter_btn.setText(t('audit_filter_btn', lang_code))
        self.pdf_btn.setText(t('audit_pdf_btn', lang_code))
        self.table.setHorizontalHeaderLabels([
            t('audit_col_date', lang_code),
            t('audit_col_time', lang_code),
            t('audit_col_user', lang_code),
            t('audit_col_category', lang_code),
            t('audit_col_action', lang_code),
            t('audit_col_desc', lang_code),
        ])

    # Sekmeye her girişte güncel kayıtların gelmesi için bitiş tarihini
    # "yarın"a çekip otomatik refresh ediyoruz.
    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, 'end_date'):
            self.end_date.setDate(QDate.currentDate().addDays(1))
        if hasattr(self, 'table'):
            self.refresh_logs()

    # ── Internal ─────────────────────────────────────────────────────
    def _on_category_toggled(self, checked):
        if not checked:
            return
        for key, rb in self._cat_buttons.items():
            if rb.isChecked():
                self._current_filter = key
                break
        self.refresh_logs()

    def refresh_logs(self):
        """Fetch and display logs with current filters."""
        # Guard: avoid running before _init_ui finishes building the table
        # (e.g. if a signal fires mid-construction).
        if not hasattr(self, 'table'):
            return
        self.table.setRowCount(0)

        start = self.start_date.date().toString("yyyy-MM-dd")
        end = self.end_date.date().toString("yyyy-MM-dd")

        filters = {
            'date_from': f"{start}T00:00:00",
            'date_to': f"{end}T23:59:59",
        }
        cats = _CATEGORY_FILTERS.get(self._current_filter)
        if cats is not None:
            filters['categories'] = cats

        records = self.audit.get_audit_trail(filters)
        self.current_records = records

        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)

            ts = record.get('timestamp', '')
            tr_dt = format_datetime_tr(ts, fallback='')
            if ' ' in tr_dt:
                date_str, time_str = tr_dt.split(' ', 1)
            else:
                date_str, time_str = tr_dt, ''

            category = record.get('category') or 'SYSTEM'
            cat_color = _CATEGORY_COLORS.get(category, _CATEGORY_COLORS['SYSTEM'])
            cat_display = _CATEGORY_DISPLAY.get(category, category)

            cells = [
                (date_str,                        Qt.AlignCenter),
                (time_str,                        Qt.AlignCenter),
                (record.get('username', '-'),     Qt.AlignCenter),
                (cat_display,                     Qt.AlignCenter),
                (record.get('action_type', '-'),  Qt.AlignCenter),
                (self._format_description(record), Qt.AlignLeft | Qt.AlignVCenter),
            ]
            for col, (text, align) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                if col == 3:
                    item.setBackground(cat_color)
                self.table.setItem(row, col, item)

    @staticmethod
    def _format_description(record):
        desc = record.get('description', '') or ''
        details = record.get('details', '')
        if details:
            desc = f"{desc} ({details})" if desc else f"({details})"
        return desc

    def export_to_pdf(self):
        """Generate PDF report for currently filtered records."""
        if not self.current_records:
            QMessageBox.warning(
                self,
                Translations.t('audit_title', self._current_lang),
                Translations.t('audit_no_records', self._current_lang),
            )
            return
        try:
            filename = self.pdf_gen.generate_audit_trail_report(self.current_records)
            QMessageBox.information(
                self,
                Translations.t('audit_title', self._current_lang),
                f"{filename}",
            )
            try:
                os.startfile(os.path.dirname(os.path.abspath(filename)))
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Error", f"{e}")
