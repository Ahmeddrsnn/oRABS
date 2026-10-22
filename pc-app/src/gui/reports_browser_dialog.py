"""Reports browser dialog — GLT + Batch PDF raporlarını tek yerde listeler.

Üç sekme:
  * **GLT Test Raporları** — `pdf_gen.output_dir` içindeki bireysel test PDF'leri
  * **Batch Raporları**   — `pdf_gen.batch_output_dir/<batch_adı>/` altındaki
                             batch özet + üyelik PDF'leri
  * **Audit Trail Raporları** — `reports/audit_trail_*.pdf`

Üstte filtre çubuğu: dosya adı arama + tarih/saat aralığı (from/to). Filtre
üç sekmeye de uygulanır. Her satıra çift tık → in-app PdfViewerDialog açar.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import List, Dict

from PyQt5.QtCore import Qt, QDateTime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QLabel, QAbstractItemView,
    QMessageBox, QLineEdit, QDateTimeEdit, QFrame,
)

from .pdf_viewer_dialog import PdfViewerDialog


_MISSING_TXT = "— silinmiş —"


def _fmt_size(nbytes) -> str:
    if nbytes is None:
        return _MISSING_TXT
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1024 * 1024:
        return f"{nbytes/1024:.1f} KB"
    return f"{nbytes/(1024*1024):.1f} MB"


def _fmt_time(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y  %H:%M")
    except Exception:
        return "-"


def _iso_to_epoch(s: str) -> float:
    """ISO/`YYYY-MM-DD HH:MM:SS` metnini epoch'a çevir (hatada 0.0)."""
    if not s:
        return 0.0
    txt = str(s).strip()
    try:
        return datetime.fromisoformat(txt).timestamp()
    except ValueError:
        for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(txt, fmt).timestamp()
            except ValueError:
                pass
    return 0.0


def _norm_path(p: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(p)))
    except Exception:
        return str(p).lower()


class ReportsBrowserDialog(QDialog):
    """Modal, ~900x600. GLT + Batch PDF listesi.

    Args:
        pdf_gen:  `PDFReportGenerator` — `output_dir` ve `batch_output_dir`
                  attribute'ları okunur.
        parent:   Ata widget.
    """

    def __init__(self, pdf_gen, parent=None, db=None):
        super().__init__(parent)
        self.pdf_gen = pdf_gen
        # DB erişimi (2026-08-06): rapor kayıt defteri (oraps_report_registry)
        # + GLT test kayıtları — PDF silinse bile listede kalır ve çift
        # tıkla yeniden üretilir. None ise eski dosya-taramalı davranış.
        self._db = db
        self._registry_by_path: Dict[str, Dict] = {}
        self._glt_records_cache: List[Dict] | None = None
        # Kullanıcı "Bitiş" filtresini elle değiştirdi mi? Değiştirmediyse
        # Yenile'de bitiş anı "şimdi"ye taşınır — aksi halde dialog açıkken
        # üretilen yeni raporlar filtreye takılıp görünmüyordu.
        self._to_user_touched = False
        self.setWindowTitle("📚 Raporları Görüntüle")
        self.setModal(True)
        self.resize(900, 600)
        # Genel Bakış ile aynı deneyim: tam ekran (maximize) açılır.
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

        self._build_ui()
        self._reload_all()

    # ── UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)

        header = QLabel("Rapor Arşivi")
        header.setStyleSheet(
            "font:700 18px 'Segoe UI'; color:#1f2937;"
        )
        root.addWidget(header)

        subtitle = QLabel(
            "Satıra çift tıklayarak PDF'i uygulama içinde açabilirsiniz."
        )
        subtitle.setStyleSheet("color:#6b7280; font:12px 'Segoe UI';")
        root.addWidget(subtitle)

        # ── Filtre çubuğu ──────────────────────────────────────
        filter_frame = QFrame()
        filter_frame.setStyleSheet(
            "QFrame { background:#f9fafb; border:1px solid #e5e7eb;"
            " border-radius:6px; }"
            " QLabel { color:#374151; font:600 12px 'Segoe UI'; }"
            " QLineEdit, QDateTimeEdit { padding:5px 8px; border:1px solid #d1d5db;"
            " border-radius:5px; background:#ffffff; font:12px 'Segoe UI'; }"
        )
        flt = QHBoxLayout(filter_frame)
        flt.setContentsMargins(12, 10, 12, 10)
        flt.setSpacing(8)

        flt.addWidget(QLabel("🔍 Ara:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Dosya adı (ör: GT_20260101, audit)…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_filter_changed)
        flt.addWidget(self.search_edit, 2)

        flt.addSpacing(8)
        flt.addWidget(QLabel("Başlangıç:"))
        self.from_edit = QDateTimeEdit()
        self.from_edit.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.from_edit.setCalendarPopup(True)
        # Varsayılan: 30 gün öncesi 00:00
        _now = QDateTime.currentDateTime()
        self.from_edit.setDateTime(_now.addDays(-30))
        self.from_edit.dateTimeChanged.connect(self._on_filter_changed)
        flt.addWidget(self.from_edit)

        flt.addWidget(QLabel("Bitiş:"))
        self.to_edit = QDateTimeEdit()
        self.to_edit.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDateTime(_now)
        self.to_edit.dateTimeChanged.connect(self._on_to_changed_by_user)
        flt.addWidget(self.to_edit)

        self.btn_clear_filter = QPushButton("🗑 Temizle")
        self.btn_clear_filter.setCursor(Qt.PointingHandCursor)
        self.btn_clear_filter.setStyleSheet(
            "QPushButton { padding:10px 18px; border:1px solid #d1d5db;"
            " background:#ffffff; border-radius:5px; font:600 16px 'Segoe UI'; }"
            " QPushButton:hover { background:#f3f4f6; }"
        )
        self.btn_clear_filter.clicked.connect(self._on_clear_filter)
        flt.addWidget(self.btn_clear_filter)

        root.addWidget(filter_frame)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #e5e7eb; border-radius:6px; }"
            "QTabBar::tab { padding:12px 22px; font:600 16px 'Segoe UI'; }"
            "QTabBar::tab:selected { background:#eff6ff; color:#1d4ed8; }"
        )
        root.addWidget(self.tabs, 1)

        # ── GLT tab ──
        self.glt_table = self._make_table(
            ["Dosya adı", "Tarih", "Boyut"]
        )
        self.glt_table.cellDoubleClicked.connect(self._on_glt_dbl)
        glt_wrap = QWidget()
        _lay = QVBoxLayout(glt_wrap)
        _lay.setContentsMargins(6, 6, 6, 6)
        _lay.addWidget(self.glt_table)
        self.tabs.addTab(glt_wrap, "🧪 GLT Test Raporları")

        # ── Batch tab ──
        self.batch_table = self._make_table(
            ["Batch adı", "Dosya adı", "Tarih", "Boyut"]
        )
        self.batch_table.cellDoubleClicked.connect(self._on_batch_dbl)
        batch_wrap = QWidget()
        _lay2 = QVBoxLayout(batch_wrap)
        _lay2.setContentsMargins(6, 6, 6, 6)
        _lay2.addWidget(self.batch_table)
        self.tabs.addTab(batch_wrap, "📦 Batch Raporları")

        # ── Özet Raporlar tab ──
        # Kompakt (alarm + port) özet raporlar: BATCH_SUMMARY_*_ozet.pdf
        self.summary_table = self._make_table(
            ["Batch adı", "Dosya adı", "Tarih", "Boyut"]
        )
        self.summary_table.cellDoubleClicked.connect(self._on_summary_dbl)
        summary_wrap = QWidget()
        _lay4 = QVBoxLayout(summary_wrap)
        _lay4.setContentsMargins(6, 6, 6, 6)
        _lay4.addWidget(self.summary_table)
        self.tabs.addTab(summary_wrap, "📋 Özet Raporlar")

        # ── Audit Trail tab ──
        # Audit trail PDF'leri `reports/` klasörüne `audit_trail_*.pdf`
        # olarak yazılıyor. GLT sekmesinden filtrelenir, burada listelenir.
        self.audit_table = self._make_table(
            ["Dosya adı", "Tarih", "Boyut"]
        )
        self.audit_table.cellDoubleClicked.connect(self._on_audit_dbl)
        audit_wrap = QWidget()
        _lay3 = QVBoxLayout(audit_wrap)
        _lay3.setContentsMargins(6, 6, 6, 6)
        _lay3.addWidget(self.audit_table)
        self.tabs.addTab(audit_wrap, "📋 Audit Trail Raporları")

        # ── Bottom bar ──
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)

        self.btn_refresh = QPushButton("🔄 Yenile")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet(
            "QPushButton { padding:12px 22px; border:1px solid #d1d5db;"
            " background:#ffffff; border-radius:6px; font:600 16px 'Segoe UI'; }"
            " QPushButton:hover { background:#f3f4f6; }"
        )
        self.btn_refresh.clicked.connect(self._on_refresh)
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)

        self.btn_close = QPushButton("Kapat")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setFixedSize(160, 52)
        self.btn_close.setStyleSheet(
            "QPushButton { background:#2563eb; color:white; border:none;"
            " border-radius:6px; font:700 17px 'Segoe UI'; }"
            " QPushButton:hover { background:#1d4ed8; }"
        )
        self.btn_close.clicked.connect(self.accept)
        bar.addWidget(self.btn_close)

        root.addLayout(bar)

    def _make_table(self, headers: List[str]) -> QTableWidget:
        t = QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.setStyleSheet(
            "QTableWidget { gridline-color:#e5e7eb; font:16px 'Segoe UI'; }"
            "QHeaderView::section { padding:10px; background:#f9fafb;"
            " border:none; border-bottom:1px solid #e5e7eb;"
            " font:600 16px 'Segoe UI'; color:#374151; }"
        )
        header = t.horizontalHeader()
        for i in range(len(headers)):
            header.setSectionResizeMode(i, QHeaderView.Stretch)
        return t

    # ── Data loading ───────────────────────────────────────────
    def _reload_all(self):
        self._load_glt_and_audit()
        self._load_batch()

    def _current_filter(self) -> Dict:
        """Aktif filtre parametrelerini döndür.
        Return: {'text': str, 'from_ts': float|None, 'to_ts': float|None}
        """
        text = (self.search_edit.text() or '').strip().lower()
        try:
            from_ts = self.from_edit.dateTime().toSecsSinceEpoch()
        except Exception:
            from_ts = None
        try:
            to_ts = self.to_edit.dateTime().toSecsSinceEpoch()
        except Exception:
            to_ts = None
        # Ters yönde girildiyse (Bitiş < Başlangıç) filtre iptal.
        if from_ts is not None and to_ts is not None and to_ts < from_ts:
            from_ts = None
            to_ts = None
        return {'text': text, 'from_ts': from_ts, 'to_ts': to_ts}

    def _row_passes_filter(self, item: Dict, flt: Dict) -> bool:
        text = flt['text']
        if text and text not in str(item.get('name', '')).lower() \
                and text not in str(item.get('batch', '')).lower():
            return False
        ts = float(item.get('mtime', 0))
        if flt['from_ts'] is not None and ts < flt['from_ts']:
            return False
        if flt['to_ts'] is not None and ts > flt['to_ts']:
            return False
        return True

    def _load_glt_and_audit(self):
        """GLT test raporları + audit trail raporlarını listele.

        GLT sekmesi DB tabanlıdır (test_records): PDF diskten silinse bile
        kayıt listede kalır (boyut '— silinmiş —') ve çift tıkla yeniden
        üretilir. Kayıtla eşleşmeyen eski disk dosyaları da eklenir.
        Audit raporları dosya taramalı kalır."""
        flt = self._current_filter()
        glt_rows: List[Dict] = []
        audit_rows: List[Dict] = []
        seen_paths: set = set()
        out_dir = getattr(self.pdf_gen, 'output_dir', '') or ''

        # 1) DB'deki test kayıtları (varsa) — dosya yoksa da listelenir.
        if self._db is not None and out_dir:
            if self._glt_records_cache is None:
                try:
                    self._glt_records_cache = self._db.get_test_records() or []
                except Exception:
                    self._glt_records_cache = []
            for rec in self._glt_records_cache:
                try:
                    safe_id = re.sub(r'[:\\/*?"<>|]', '',
                                     str(rec.get('test_id') or ''))
                    rid = rec.get('id')
                    if not safe_id or rid is None:
                        continue
                    fn = f"{safe_id}_{rid}.pdf"
                    full = os.path.join(out_dir, fn)
                    exists = os.path.isfile(full)
                    st_mtime = (os.stat(full).st_mtime if exists
                                else _iso_to_epoch(
                                    rec.get('test_start_time')
                                    or rec.get('created_at') or ''))
                    item = {
                        'name': fn,
                        'path': full,
                        'mtime': st_mtime,
                        'size': (os.stat(full).st_size if exists else None),
                        'glt_record_id': rid,
                    }
                    seen_paths.add(_norm_path(full))
                    if self._row_passes_filter(item, flt):
                        glt_rows.append(item)
                except Exception:
                    continue

        # 2) Disk taraması — kayıtla eşleşmeyen dosyalar (legacy/lang eki)
        #    + audit trail raporları.
        if out_dir and os.path.isdir(out_dir):
            try:
                for fn in os.listdir(out_dir):
                    if not fn.lower().endswith('.pdf'):
                        continue
                    full = os.path.join(out_dir, fn)
                    if not os.path.isfile(full):
                        continue
                    st = os.stat(full)
                    item = {
                        'name': fn,
                        'path': full,
                        'mtime': st.st_mtime,
                        'size': st.st_size,
                    }
                    if not self._row_passes_filter(item, flt):
                        continue
                    if fn.lower().startswith('audit_trail_'):
                        audit_rows.append(item)
                    elif _norm_path(full) not in seen_paths:
                        glt_rows.append(item)
            except Exception:
                pass
        glt_rows.sort(key=lambda r: r['mtime'], reverse=True)
        audit_rows.sort(key=lambda r: r['mtime'], reverse=True)

        # GLT tab doldur
        self.glt_table.setRowCount(len(glt_rows))
        for r, item in enumerate(glt_rows):
            self._set_cell(self.glt_table, r, 0, item['name'], full_path=item['path'])
            self._set_cell(self.glt_table, r, 1, _fmt_time(item['mtime']))
            self._set_cell(self.glt_table, r, 2, _fmt_size(item['size']))
        if not glt_rows:
            self._show_empty(self.glt_table, "Filtreye uyan GLT test raporu bulunamadı.")

        # Audit tab doldur
        self.audit_table.setRowCount(len(audit_rows))
        for r, item in enumerate(audit_rows):
            self._set_cell(self.audit_table, r, 0, item['name'], full_path=item['path'])
            self._set_cell(self.audit_table, r, 1, _fmt_time(item['mtime']))
            self._set_cell(self.audit_table, r, 2, _fmt_size(item['size']))
        if not audit_rows:
            self._show_empty(self.audit_table, "Filtreye uyan audit trail raporu bulunamadı.")

    def _registry_rows(self) -> List[Dict]:
        """`oraps_report_registry` satırlarını oku (yoksa/tablo yoksa [])."""
        if self._db is None:
            return []
        try:
            conn = self._db.connect()
            cur = conn.cursor()
            cur.execute(
                'SELECT id, report_kind, batch_name, file_path, start_iso, '
                '       end_iso, status, linked_glt_id, created_at '
                'FROM oraps_report_registry ORDER BY created_at DESC'
            )
            rows = [dict(r) for r in cur.fetchall()]
            self._db.close()
            return rows
        except Exception:
            try:
                self._db.close()
            except Exception:
                pass
            return []

    def _load_batch(self):
        """Batch + özet sekmeleri: rapor kayıt defteri (DB) esas alınır —
        PDF silinse bile satır kalır ('— silinmiş —') ve çift tıkla
        yeniden üretilir. Kayıtla eşleşmeyen disk dosyaları (kopyalanan
        bireysel test PDF'leri, eski raporlar) tarama ile eklenir."""
        flt = self._current_filter()
        rows: List[Dict] = []
        summary_rows: List[Dict] = []
        self._registry_by_path = {}
        seen_paths: set = set()

        # 1) Kayıt defteri (DB) — silinmiş dosyalar dahil.
        for reg in self._registry_rows():
            full = str(reg.get('file_path') or '')
            if not full:
                continue
            key = _norm_path(full)
            self._registry_by_path[key] = reg
            if key in seen_paths:
                continue
            seen_paths.add(key)
            exists = os.path.isfile(full)
            item = {
                'batch': str(reg.get('batch_name') or ''),
                'name': os.path.basename(full),
                'path': full,
                'mtime': (os.stat(full).st_mtime if exists
                          else _iso_to_epoch(reg.get('created_at') or '')),
                'size': (os.stat(full).st_size if exists else None),
            }
            if not self._row_passes_filter(item, flt):
                continue
            if str(reg.get('report_kind') or '') == 'ozet':
                summary_rows.append(item)
            else:
                rows.append(item)

        # 2) Disk taraması — kayıt defterinde olmayan dosyalar.
        base = getattr(self.pdf_gen, 'batch_output_dir', '') or ''
        if base and os.path.isdir(base):
            try:
                for batch_name in os.listdir(base):
                    batch_dir = os.path.join(base, batch_name)
                    if not os.path.isdir(batch_dir):
                        continue
                    for fn in os.listdir(batch_dir):
                        if not fn.lower().endswith('.pdf'):
                            continue
                        full = os.path.join(batch_dir, fn)
                        if not os.path.isfile(full):
                            continue
                        if _norm_path(full) in seen_paths:
                            continue
                        st = os.stat(full)
                        item = {
                            'batch': batch_name,
                            'name': fn,
                            'path': full,
                            'mtime': st.st_mtime,
                            'size': st.st_size,
                        }
                        if not self._row_passes_filter(item, flt):
                            continue
                        # Kompakt özet raporlar (_ozet) ayrı sekmede.
                        if '_ozet' in fn.lower():
                            summary_rows.append(item)
                        else:
                            rows.append(item)
            except Exception:
                pass
        rows.sort(key=lambda r: r['mtime'], reverse=True)
        summary_rows.sort(key=lambda r: r['mtime'], reverse=True)

        self.batch_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            self._set_cell(self.batch_table, r, 0, item['batch'])
            self._set_cell(self.batch_table, r, 1, item['name'], full_path=item['path'])
            self._set_cell(self.batch_table, r, 2, _fmt_time(item['mtime']))
            self._set_cell(self.batch_table, r, 3, _fmt_size(item['size']))
        if not rows:
            self._show_empty(self.batch_table, "Filtreye uyan batch raporu bulunamadı.")

        self.summary_table.setRowCount(len(summary_rows))
        for r, item in enumerate(summary_rows):
            self._set_cell(self.summary_table, r, 0, item['batch'])
            self._set_cell(self.summary_table, r, 1, item['name'], full_path=item['path'])
            self._set_cell(self.summary_table, r, 2, _fmt_time(item['mtime']))
            self._set_cell(self.summary_table, r, 3, _fmt_size(item['size']))
        if not summary_rows:
            self._show_empty(self.summary_table,
                             "Filtreye uyan özet rapor bulunamadı.")

    def _set_cell(self, table: QTableWidget, row: int, col: int,
                  text: str, full_path: str | None = None):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        if full_path is not None:
            # Yolu ilk sütunda item.data ile sakla (dosya adı yolla eşleşsin diye).
            item.setData(Qt.UserRole, full_path)
        table.setItem(row, col, item)

    def _show_empty(self, table: QTableWidget, msg: str):
        table.setRowCount(1)
        item = QTableWidgetItem(msg)
        item.setTextAlignment(Qt.AlignCenter)
        item.setForeground(Qt.gray)
        table.setSpan(0, 0, 1, table.columnCount())
        table.setItem(0, 0, item)

    # ── Filter handlers ────────────────────────────────────────
    def _on_filter_changed(self, *_args):
        """Herhangi bir filtre alanı değişince tabloları yeniden yükle."""
        self._reload_all()

    def _on_to_changed_by_user(self, *_args):
        """Kullanıcı 'Bitiş' filtresini elle değiştirdi — Yenile artık
        bu değeri ezmez. (Programatik set'ler blockSignals ile yapılır,
        bu slot'a düşmez.)"""
        self._to_user_touched = True
        self._on_filter_changed()

    def _on_refresh(self):
        """🔄 Yenile — dialog açıkken üretilen yeni raporlar da görünsün
        diye, kullanıcı elle değiştirmediyse 'Bitiş' filtresini şimdiye
        taşıyıp listeyi yeniden yükler."""
        self._glt_records_cache = None   # DB'den taze test listesi
        if not self._to_user_touched:
            self.to_edit.blockSignals(True)
            try:
                self.to_edit.setDateTime(QDateTime.currentDateTime())
            finally:
                self.to_edit.blockSignals(False)
        self._reload_all()

    def _on_clear_filter(self):
        """Filtreyi varsayılana döndür (son 30 gün, arama boş)."""
        # Sinyalleri geçici olarak sustur ki 4 kez _reload_all çağrılmasın
        self.search_edit.blockSignals(True)
        self.from_edit.blockSignals(True)
        self.to_edit.blockSignals(True)
        try:
            self.search_edit.clear()
            _now = QDateTime.currentDateTime()
            self.from_edit.setDateTime(_now.addDays(-30))
            self.to_edit.setDateTime(_now)
        finally:
            self.search_edit.blockSignals(False)
            self.from_edit.blockSignals(False)
            self.to_edit.blockSignals(False)
        self._to_user_touched = False
        self._reload_all()

    # ── Double-click handlers ──────────────────────────────────
    def _on_glt_dbl(self, row: int, _col: int):
        it = self.glt_table.item(row, 0)
        path = it.data(Qt.UserRole) if it else None
        if not path:
            return
        self._open_pdf(path)

    def _on_batch_dbl(self, row: int, _col: int):
        it = self.batch_table.item(row, 1)   # dosya adı sütunu
        path = it.data(Qt.UserRole) if it else None
        if not path:
            return
        self._open_pdf(path)

    def _on_summary_dbl(self, row: int, _col: int):
        it = self.summary_table.item(row, 1)   # dosya adı sütunu
        path = it.data(Qt.UserRole) if it else None
        if not path:
            return
        self._open_pdf(path)

    def _on_audit_dbl(self, row: int, _col: int):
        it = self.audit_table.item(row, 0)
        path = it.data(Qt.UserRole) if it else None
        if not path:
            return
        self._open_pdf(path)

    def _try_regenerate(self, path: str) -> str | None:
        """Silinmiş bir raporu yerinde yeniden üretmeyi dene.

        Öncelik: rapor kayıt defteri (oraps_report_registry) — tüm
        tarihsel batch/özet raporları parametreleriyle yeniden üretilir.
        Defterde yoksa: BATCH_SUMMARY_* için son batch fallback'i, GLT
        test PDF'i için test_records'tan yeniden üretim denenir.
        Return: yeniden üretilen dosyanın yolu veya None."""
        name = os.path.basename(path)
        ov = self.parent()
        # 1) Kayıt defteri — tarihsel batch/özet raporları.
        reg = self._registry_by_path.get(_norm_path(path))
        if reg is not None:
            regen_fn = getattr(ov, 'regenerate_report_from_registry', None)
            if callable(regen_fn):
                try:
                    new_path = regen_fn(reg)
                except Exception:
                    new_path = None
                if new_path and os.path.isfile(new_path):
                    self._reload_all()
                    return new_path
        # 2) Fallback: son batch'in raporu (defter kaydı olmayan eski dosya).
        if name.upper().startswith('BATCH_SUMMARY_'):
            gen = getattr(ov, '_generate_batch_summary_pdf', None)
            if callable(gen):
                compact = '_ozet' in name.lower()
                try:
                    new_path = gen(silent=True, compact=compact)
                except Exception:
                    new_path = None
                if new_path and \
                        os.path.basename(new_path).lower() == name.lower():
                    self._reload_all()
                    return new_path
            return None
        # 3) GLT bireysel test raporu — test_records'tan yeniden üret.
        return self._try_regen_glt(path)

    def _try_regen_glt(self, path: str) -> str | None:
        """Silinmiş GLT test PDF'ini `test_records`'tan yeniden üret.
        Dosya adı deseni: <safe_test_id>_<record_id>[_<lang>].pdf"""
        if self._db is None or self.pdf_gen is None:
            return None
        stem = os.path.basename(path)
        if not stem.lower().endswith('.pdf'):
            return None
        stem = stem[:-4]
        lang = 'tr'
        m_lang = re.match(r'^(.*)_([a-z]{2})$', stem)
        if m_lang and not m_lang.group(2).isdigit() \
                and m_lang.group(2) in ('en', 'tr'):
            stem, lang = m_lang.group(1), m_lang.group(2)
        rid = None
        m_rid = re.match(r'^(.*)_(\d+)$', stem)
        if m_rid:
            stem_wo_rid, rid_txt = m_rid.group(1), m_rid.group(2)
            try:
                rid = int(rid_txt)
            except ValueError:
                rid = None
        try:
            records = (self._glt_records_cache
                       if self._glt_records_cache is not None
                       else (self._db.get_test_records() or []))
        except Exception:
            return None
        record = None
        if rid is not None:
            record = next((r for r in records if r.get('id') == rid), None)
        if record is None:
            # Legacy dosya (rid'siz): sanitize(test_id) eşleşmesi dene.
            record = next(
                (r for r in records
                 if re.sub(r'[:\\/*?"<>|]', '',
                           str(r.get('test_id') or '')) == stem),
                None)
        if record is None:
            return None
        # İmzalar (varsa) — SignatureManager salt-okur kullanılır.
        sigs = []
        try:
            from core.signature import SignatureManager
            ov = self.parent()
            sm = SignatureManager(self._db, getattr(ov, 'auth', None),
                                  getattr(ov, 'audit', None))
            sigs = sm.get_signatures_for_record(
                'test_record', int(record.get('id'))) or []
        except Exception:
            sigs = []
        try:
            new_path = self.pdf_gen.generate_test_report(record, sigs,
                                                         lang=lang)
        except Exception:
            return None
        if new_path and os.path.isfile(new_path):
            self._reload_all()
            return new_path
        return None

    def _open_pdf(self, path: str):
        if not os.path.isfile(path):
            # Dosya silinmiş — kayıt defteri / test kaydından yeniden üret.
            regen = self._try_regenerate(path)
            if regen and os.path.isfile(regen):
                path = regen
            else:
                QMessageBox.warning(
                    self, "Dosya Yok",
                    f"PDF bulunamadı ve yeniden üretilemedi:\n{path}")
                return
        try:
            PdfViewerDialog(path, parent=self).exec_()
        except Exception as e:
            QMessageBox.critical(self, "Açılamadı",
                                 f"PDF görüntüleyici açılamadı:\n{e}")
