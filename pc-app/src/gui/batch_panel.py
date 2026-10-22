"""
Batch (Toplu Test) Panel
Haritada portları sabit olarak gösterir, batch durumuna göre renklendirir.
Sol menüde batch yönetimi, sağda harita görünümü.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
    QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QInputDialog, QGraphicsDropShadowEffect, QAbstractItemView, QLineEdit,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QCheckBox,
    QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QRectF, QSettings
from PyQt5.QtGui import QBrush, QPen, QColor, QFont, QPixmap, QPainter
from datetime import datetime, timedelta
from gui.styles import Styles
from utils.date_format import format_datetime_tr
import os
import shutil
from utils.app_logger import get_logger

_logger = get_logger("batch_panel")


# ═══════════════════════════════════════════════════════════════════
# RENK SABİTLERİ
# ═══════════════════════════════════════════════════════════════════
COLOR_PENDING = '#FBBF24'   # Sarı  — Bekliyor
COLOR_PASS    = '#10B981'   # Yeşil — Geçti
COLOR_FAIL    = '#EF4444'   # Kırmızı — Kaldı
COLOR_DEFAULT = '#6B7280'   # Gri   — Batch'e dahil değil


# ═══════════════════════════════════════════════════════════════════
# BATCH PORT ITEM (Sabit — hareket ettirilemez)
# ═══════════════════════════════════════════════════════════════════
class BatchPortItem(QGraphicsEllipseItem):
    """Non-interactive port circle for batch map"""

    def __init__(self, port_id, name, rfid=None, recipe_name=None):
        super().__init__(-25, -25, 50, 50)
        self.port_id = port_id
        self.name = name
        self.rfid = rfid
        self.recipe_name = recipe_name

        # Görünüm
        self.setBrush(QBrush(QColor(COLOR_DEFAULT)))
        self.setPen(QPen(Qt.white, 2))

        # GÜVENLİK: Hareket ve seçim kapalı, transform bağımsız
        self.setFlags(QGraphicsItem.ItemIgnoresTransformations)
        self.setAcceptHoverEvents(False)

        # Etiket (port numarası)
        display_text = name.replace("Port ", "") if "Port " in name else name.split()[0]
        self.label = QGraphicsTextItem(display_text, self)
        self.label.setDefaultTextColor(Qt.white)
        self.label.setFont(QFont("Arial", 14, QFont.Bold))
        self._center_label()

        # Gölge
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(2, 2)
        self.setGraphicsEffect(shadow)

        # Tooltip
        rfid_text = rfid if rfid else "Yok"
        recipe_text = recipe_name if recipe_name else "Yok"
        self.setToolTip(f"Port: {name}\nRFID: {rfid_text}\nReçete: {recipe_text}")

    def _center_label(self):
        rect = self.label.boundingRect()
        self.label.setPos(-rect.width() / 2, -rect.height() / 2)

    def set_status_color(self, status: str):
        """Duruma göre renk ata"""
        colors = {
            'PENDING': COLOR_PENDING,
            'PASS':    COLOR_PASS,
            'FAIL':    COLOR_FAIL,
        }
        color = colors.get(status, COLOR_DEFAULT)
        self.setBrush(QBrush(QColor(color)))
        self.update()


# ═══════════════════════════════════════════════════════════════════
# BATCH MAP WİDGET (Read-only harita)
# ═══════════════════════════════════════════════════════════════════
class BatchMapWidget(QGraphicsView):
    """Read-only map that displays port status colors for batch"""

    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.db = database
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)

        self.background_item = None
        self.port_items: dict[int, BatchPortItem] = {}  # port_id -> item

        self._load_background()
        self._load_ports()

    def _load_background(self):
        """Arkaplan resmini yükle"""
        try:
            image_path = self.db.get_layout_image()
            if image_path and os.path.exists(image_path):
                pixmap = QPixmap(image_path)
                self.background_item = QGraphicsPixmapItem(pixmap)
                self.background_item.setZValue(-1)
                self.scene.addItem(self.background_item)
                self.setSceneRect(self.background_item.boundingRect())
                self._fit_background()
            else:
                self.scene.addText("Yerleşim planı yüklenmemiş.")
        except Exception as e:
            _logger.error("Background load error: %s", e)

    def _load_ports(self):
        """Veritabanından portları yükle"""
        try:
            ports = self.db.get_all_ports()
            for port in ports:
                item = BatchPortItem(
                    port['id'],
                    port['name'],
                    rfid=port.get('rfid_tag'),
                    recipe_name=port.get('recipe_name')
                )
                item.setPos(port['x_pos'], port['y_pos'])
                self.scene.addItem(item)
                self.port_items[port['id']] = item
        except Exception as e:
            _logger.error("Port load error: %s", e)

    def update_port_color(self, port_id: int, status: str):
        """Belirli portun rengini güncelle"""
        if port_id in self.port_items:
            self.port_items[port_id].set_status_color(status)

    def reset_all_colors(self):
        """Tüm portları varsayılan renge çevir"""
        for item in self.port_items.values():
            item.set_status_color('')

    def refresh(self):
        """Haritayı yeniden yükle (arka plan + portlar)"""
        self.scene.clear()
        self.port_items.clear()
        self.background_item = None
        self._load_background()
        self._load_ports()

    def wheelEvent(self, event):
        """Zoom devre dışı"""
        event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_background()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_background()

    def _fit_background(self):
        """Resmi çerçeveye sığdır (aspect ratio koruyarak)"""
        if self.background_item:
            self.fitInView(self.background_item, Qt.KeepAspectRatio)
            self._reclamp_ports()

    def _get_viewport_scene_rect(self):
        """Viewport'ın scene koordinatındaki karşılığını döndür"""
        vp = self.viewport().rect()
        top_left = self.mapToScene(vp.topLeft())
        bottom_right = self.mapToScene(vp.bottomRight())
        return QRectF(top_left, bottom_right)

    def _reclamp_ports(self):
        """Tüm portları viewport sınırları içine sığdır"""
        vr = self._get_viewport_scene_rect()
        if vr.isEmpty():
            return
        t = self.transform()
        margin = 25.0 / t.m11() if t.m11() > 0 else 25.0
        for item in self.port_items.values():
            pos = item.pos()
            x = max(vr.left() + margin, min(pos.x(), vr.right() - margin))
            y = max(vr.top() + margin, min(pos.y(), vr.bottom() - margin))
            if abs(x - pos.x()) > 0.5 or abs(y - pos.y()) > 0.5:
                item.setPos(x, y)


# ═══════════════════════════════════════════════════════════════════
# BATCH PANEL (Ana Widget)
# ═══════════════════════════════════════════════════════════════════
class BatchPanel(QWidget):
    """Toplu Test (Batch) yönetim paneli"""

    def __init__(self, database, esp32_comm, auth_manager, audit_manager, parent=None):
        super().__init__(parent)
        self.db = database
        self.esp32 = esp32_comm
        self.auth = auth_manager
        self.audit = audit_manager

        self.active_batch = None  # Şu anki aktif batch dict
        self.pdf_gen = None  # PDFReportGenerator ref — set_pdf_generator ile atanır
        self._settings = QSettings('UltraGITS', 'BatchPanel')
        self._include_fails_in_report = self._settings.value('include_fails_in_report', True, type=bool)

        self._init_ui()
        self.load_active_batch()

    def set_pdf_generator(self, pdf_gen):
        """PDFReportGenerator referansı — main_window'dan atanır"""
        self.pdf_gen = pdf_gen

    def _open_pdf_inapp(self, pdf_path: str, parent=None):
        """PDF'i uygulama içi tam ekran görüntüleyicide aç.
        WebEngine yoksa sessizce yok sayar (PDF zaten diskte oluşmuş)."""
        try:
            from gui.pdf_viewer_dialog import PdfViewerDialog
            PdfViewerDialog(pdf_path, parent=parent or self).exec_()
        except Exception:
            pass

    # ─────────────────────── UI ───────────────────────
    def _init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Sol Panel (menü + tablo) ──
        left = QWidget()
        left.setFixedWidth(420)
        left.setStyleSheet("background-color: #F9FAFB; border-right: 1px solid #E5E7EB;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(15, 15, 15, 15)
        left_layout.setSpacing(10)

        title = QLabel("📦 Batch")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #1F2937; border: none;")
        left_layout.addWidget(title)

        # Butonlar
        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("▶  Yeni Batch Başlat")
        self.btn_start.setStyleSheet(Styles.get_button_style("success"))
        self.btn_start.clicked.connect(self._on_start_batch)
        btn_row.addWidget(self.btn_start)

        self.btn_finish = QPushButton("⏹  Batch Bitir")
        self.btn_finish.setStyleSheet(Styles.get_button_style("danger"))
        self.btn_finish.clicked.connect(self._on_finish_batch)
        self.btn_finish.setEnabled(False)
        btn_row.addWidget(self.btn_finish)
        left_layout.addLayout(btn_row)

        # Şablon butonları
        tmpl_row = QHBoxLayout()
        self.btn_save_template = QPushButton("📋 Şablon Kaydet")
        self.btn_save_template.setStyleSheet(Styles.get_button_style("primary"))
        self.btn_save_template.clicked.connect(self._on_save_template)
        tmpl_row.addWidget(self.btn_save_template)

        self.btn_delete_template = QPushButton("🗑 Şablon Sil")
        self.btn_delete_template.setStyleSheet(Styles.get_button_style("danger"))
        self.btn_delete_template.clicked.connect(self._on_delete_template)
        tmpl_row.addWidget(self.btn_delete_template)
        left_layout.addLayout(tmpl_row)

        # Durum etiketi
        self.status_label = QLabel("Aktif batch yok.")
        self.status_label.setStyleSheet("color: #6B7280; font-size: 13px; border: none;")
        left_layout.addWidget(self.status_label)

        # Port tablosu
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Port", "RFID", "Durum", "Açıklama"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget { 
                border: 1px solid #E5E7EB; 
                border-radius: 6px; 
                background: white; 
                alternate-background-color: #F9FAFB; 
            }
            QHeaderView::section { 
                background: #F3F4F6; 
                color: #374151; 
                font-weight: bold; 
                padding: 6px; 
                border: none; 
                border-bottom: 2px solid #D1D5DB; 
            }
        """)
        left_layout.addWidget(self.table)

        main_layout.addWidget(left)

        # ── Sağ Panel (harita) ──
        self.map_widget = BatchMapWidget(self.db)
        main_layout.addWidget(self.map_widget, 1)  # stretch=1

        self.setLayout(main_layout)

    # ─────────────────────── VERİ ───────────────────────
    def load_active_batch(self):
        """DB'den aktif batch'i çek, tablo ve haritayı güncelle"""
        try:
            self.active_batch = self.db.get_active_batch()

            if self.active_batch:
                self.status_label.setText(
                    f"🟢 Aktif Batch: {self.active_batch['batch_name']}  "
                    f"(ID: {self.active_batch['id']}, "
                    f"Başlangıç: {format_datetime_tr(self.active_batch['start_time'])})"
                )
                self.btn_start.setEnabled(False)
                self.btn_finish.setEnabled(True)
                self._populate_table(self.active_batch.get('ports', []))
                self._colorize_map(self.active_batch.get('ports', []))
            else:
                self.status_label.setText("Aktif batch yok.")
                self.btn_start.setEnabled(True)
                self.btn_finish.setEnabled(False)
                self.table.setRowCount(0)
                self.map_widget.reset_all_colors()
        except Exception as e:
            _logger.error("load_active_batch error: %s", e)

    def _populate_table(self, ports):
        """Tablo satırlarını doldur"""
        self.table.setRowCount(len(ports))
        for row, p in enumerate(ports):
            # Port adı — DB'deki port bilgisini çek
            port_name = f"Port {p['port_id']}"
            try:
                all_ports = self.db.get_all_ports()
                match = next((x for x in all_ports if x['id'] == p['port_id']), None)
                if match:
                    port_name = match['name']
            except:
                _logger.debug("Port name lookup failed for port_id=%s", p['port_id'])
            self.table.setItem(row, 0, QTableWidgetItem(port_name))
            self.table.setItem(row, 1, QTableWidgetItem(p.get('rfid_tag', '')))

            status = p.get('status', 'PENDING')
            status_display = {'PENDING': 'Bekleniyor', 'PASS': 'Geçti', 'FAIL': 'Kaldı'}.get(status, status)
            status_item = QTableWidgetItem(status_display)
            color_map = {'PENDING': '#92400E', 'PASS': '#065F46', 'FAIL': '#991B1B'}
            status_item.setForeground(QColor(color_map.get(status, '#374151')))
            self.table.setItem(row, 2, status_item)

            self.table.setItem(row, 3, QTableWidgetItem(p.get('explanation', '') or ''))

    def _colorize_map(self, batch_ports):
        """Haritadaki portları batch durumuna göre renklendir"""
        self.map_widget.reset_all_colors()
        for p in batch_ports:
            self.map_widget.update_port_color(p['port_id'], p.get('status', 'PENDING'))

    # ─────────────────────── EYLEMLER ───────────────────────
    def _verify_user_password(self) -> bool:
        """İşlem onayı için kullanıcı şifresini doğrula"""
        if not self.auth.current_user:
            QMessageBox.warning(self, "Yetki", "Lütfen önce oturum açın.")
            return False
        password, ok = QInputDialog.getText(
            self, "Şifre Onayı",
            f"Kullanıcı: {self.auth.current_user['username']}\nİşlemi onaylamak için şifrenizi girin:",
            QLineEdit.Password
        )
        if not ok or not password:
            return False
        if not self.auth.verify_password(password, self.auth.current_user['password_hash']):
            QMessageBox.warning(self, "Hata", "Şifre yanlış!")
            return False
        return True

    def _on_start_batch(self):
        """Yeni batch başlat — şablon seçtir, sonra batch oluştur"""
        if not self.auth.current_user:
            QMessageBox.warning(self, "Yetki", "Lütfen önce oturum açın.")
            return

        # Aktif batch varken yenisi açılamaz — aksi halde DB'de ACTIVE
        # satırlar birikiyor ve "Batch Bitir" sonrası panel bir sonraki
        # eski ACTIVE batch'i yükleyip "batch bitmiyor" izlenimi veriyordu.
        self.load_active_batch()
        if self.active_batch:
            QMessageBox.warning(
                self, "Aktif Batch Var",
                f"Zaten aktif bir batch var: "
                f"'{self.active_batch.get('batch_name')}' "
                f"(ID: {self.active_batch.get('id')}).\n\n"
                "Önce mevcut batch'i bitirin."
            )
            return

        # Kayıtlı şablonları getir
        templates = self.db.get_batch_templates()
        if not templates:
            QMessageBox.information(self, "Şablon Yok",
                "Kayıtlı batch şablonu bulunamadı.\nÖnce '📋 Şablon Kaydet' ile bir şablon oluşturun.")
            return

        # Şablon seçim diyaloğu
        dlg = QDialog(self)
        dlg.setWindowTitle("Batch Şablonu Seç")
        dlg.setMinimumWidth(350)
        dlg_layout = QVBoxLayout(dlg)

        dlg_layout.addWidget(QLabel("Kullanmak istediğiniz şablonu seçin:"))

        tmpl_list = QListWidget()
        for t in templates:
            item = QListWidgetItem(f"{t['template_name']}  ({t['port_count']} port)")
            item.setData(Qt.UserRole, t['id'])
            tmpl_list.addItem(item)
        tmpl_list.setCurrentRow(0)
        dlg_layout.addWidget(tmpl_list)

        # FAIL testleri rapora dahil et checkbox
        fail_cb = QCheckBox("FAIL testleri rapora dahil et")
        fail_cb.setChecked(self._include_fails_in_report)
        fail_cb.setStyleSheet("font-size: 13px; padding: 6px 0;")
        dlg_layout.addWidget(fail_cb)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        dlg_layout.addWidget(buttons)

        if dlg.exec_() != QDialog.Accepted:
            return
        selected = tmpl_list.currentItem()
        if not selected:
            return
        template_id = selected.data(Qt.UserRole)
        template_name = templates[tmpl_list.currentRow()]['template_name']

        # Checkbox durumunu kaydet
        self._include_fails_in_report = fail_cb.isChecked()
        self._settings.setValue('include_fails_in_report', self._include_fails_in_report)

        # Batch adı
        name, ok = QInputDialog.getText(self, "Yeni Batch", "Batch adı girin:")
        if not ok or not name.strip():
            return

        # Otomatik tarih-saat ekle (Türkiye formatı)
        now_str = datetime.now().strftime('%d.%m.%Y %H:%M')
        full_name = f"{name.strip()} — {now_str}"

        # Şifre doğrulama
        if not self._verify_user_password():
            return

        try:
            operator_id = self.auth.current_user['id']
            # Faz-8 birleşik akış: ORABS batch'i çalışıyorsa yeni GLT batch
            # ona bağlanır → ORABS bitirilirken otomatik kapatılır ve port
            # test detayları ORABS batch özet raporuna dahil edilir.
            _linked = 1 if self.db.is_oraps_batch_active() else None
            batch_id = self.db.create_batch(full_name, operator_id,
                                            linked_oraps_batch_id=_linked)
            if not batch_id:
                QMessageBox.critical(self, "Hata", "Batch oluşturulamadı.")
                return

            # Şablondaki portları batch'e ekle
            port_ids = self.db.get_template_ports(template_id)
            all_ports = self.db.get_all_ports()
            all_ports_map = {p['id']: p for p in all_ports} if all_ports else {}

            if not port_ids:
                QMessageBox.warning(self, "Uyarı", "Seçilen şablonda port bulunamadı.")
                self.db.complete_batch(batch_id)
                return

            ports_data = []
            for pid in port_ids:
                port_info = all_ports_map.get(pid)
                if port_info:
                    ports_data.append({
                        'port_id': pid,
                        'rfid_tag': port_info.get('rfid_tag', '')
                    })
            self.db.add_ports_to_batch(batch_id, ports_data)

            self.load_active_batch()

            # Audit trail: Batch başlatıldı
            self.audit.log_action(
                'BATCH_STARTED',
                table_name='test_batches',
                record_id=batch_id,
                description=f"Batch başlatıldı: '{full_name}', şablon: '{template_name}', {len(ports_data)} port"
            )

            QMessageBox.information(self, "Başarılı",
                                    f"'{full_name}' batch'i başlatıldı.\nŞablon: {template_name}\n{len(ports_data)} port eklendi.")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Batch başlatılamadı:\n{e}")

    # ─────────────────────── ŞABLON İŞLEMLERİ ───────────────────────
    def _on_save_template(self):
        """Yeni batch şablonu kaydet: isim + port seçimi + kullanıcı şifresi (Admin/Supervisor)"""
        if not self.auth.current_user:
            QMessageBox.warning(self, "Yetki", "Lütfen önce oturum açın.")
            return

        # Yetki kontrolü — Admin veya Supervisor
        if not self.auth.has_permission('Supervisor'):
            QMessageBox.warning(self, "Yetki", "Şablon kaydetmek için Admin veya Supervisor yetkisi gerekli.")
            return

        # Şablon adı
        tmpl_name, ok = QInputDialog.getText(self, "Şablon Kaydet", "Şablon adı girin:")
        if not ok or not tmpl_name.strip():
            return
        tmpl_name = tmpl_name.strip()

        if self.db.batch_template_name_exists(tmpl_name):
            QMessageBox.warning(self, "Uyarı", f"'{tmpl_name}' isimli bir şablon zaten mevcut.")
            return

        # Port seçim diyaloğu
        all_ports = self.db.get_all_ports()
        if not all_ports:
            QMessageBox.warning(self, "Uyarı", "Sistemde port tanımlı değil.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Port Seçimi — {tmpl_name}")
        dlg.setMinimumSize(350, 400)
        dlg_layout = QVBoxLayout(dlg)

        dlg_layout.addWidget(QLabel("Şablona eklenecek portları seçin:"))

        # Tümünü seç/kaldır
        select_all_cb = QCheckBox("Tümünü Seç")
        dlg_layout.addWidget(select_all_cb)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(4)

        port_checkboxes = []
        import re
        def _port_sort_key(p):
            nums = re.findall(r'\d+', p.get('name', ''))
            return int(nums[0]) if nums else 0
        all_ports.sort(key=_port_sort_key)
        for p in all_ports:
            cb = QCheckBox(f"{p['name']}  (RFID: {p.get('rfid_tag', '-')})")
            cb.setProperty('port_id', p['id'])
            scroll_layout.addWidget(cb)
            port_checkboxes.append(cb)

        scroll_layout.addStretch()
        scroll_content.setLayout(scroll_layout)
        scroll.setWidget(scroll_content)
        dlg_layout.addWidget(scroll)

        def toggle_all(state):
            for cb in port_checkboxes:
                cb.setChecked(state == Qt.Checked)
        select_all_cb.stateChanged.connect(toggle_all)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        dlg_layout.addWidget(buttons)

        if dlg.exec_() != QDialog.Accepted:
            return

        selected_ids = [cb.property('port_id') for cb in port_checkboxes if cb.isChecked()]
        if not selected_ids:
            QMessageBox.warning(self, "Uyarı", "En az bir port seçmelisiniz.")
            return

        # Admin şifre doğrulama
        if not self._verify_user_password():
            return

        try:
            tid = self.db.save_batch_template(tmpl_name, selected_ids, self.auth.current_user['id'])
            if tid:
                # Seçilen portların isimlerini çek
                selected_names = []
                for cb in port_checkboxes:
                    if cb.isChecked():
                        pid = cb.property('port_id')
                        match = next((p for p in all_ports if p['id'] == pid), None)
                        if match:
                            selected_names.append(match['name'])
                port_list_str = ', '.join(selected_names)
                self.audit.log_action(
                    'TEMPLATE_CREATED',
                    table_name='batch_templates',
                    record_id=tid,
                    description=f"Batch şablonu oluşturuldu: '{tmpl_name}', {len(selected_ids)} port: [{port_list_str}]"
                )
                QMessageBox.information(self, "Başarılı",
                    f"'{tmpl_name}' şablonu kaydedildi.\n{len(selected_ids)} port eklendi.")
            else:
                QMessageBox.critical(self, "Hata", "Şablon kaydedilemedi.")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Şablon kaydedilemedi:\n{e}")

    def _on_delete_template(self):
        """Batch şablonu sil — Admin veya Supervisor"""
        if not self.auth.current_user:
            QMessageBox.warning(self, "Yetki", "Lütfen önce oturum açın.")
            return

        if not self.auth.has_permission('Supervisor'):
            QMessageBox.warning(self, "Yetki", "Şablon silmek için Admin veya Supervisor yetkisi gerekli.")
            return

        templates = self.db.get_batch_templates()
        if not templates:
            QMessageBox.information(self, "Bilgi", "Silinecek şablon bulunamadı.")
            return

        # Şablon seçim diyaloğu
        dlg = QDialog(self)
        dlg.setWindowTitle("Şablon Sil")
        dlg.setMinimumWidth(350)
        dlg_layout = QVBoxLayout(dlg)

        dlg_layout.addWidget(QLabel("Silmek istediğiniz şablonu seçin:"))

        tmpl_list = QListWidget()
        for t in templates:
            item = QListWidgetItem(f"{t['template_name']}  ({t['port_count']} port)")
            item.setData(Qt.UserRole, t['id'])
            tmpl_list.addItem(item)
        tmpl_list.setCurrentRow(0)
        dlg_layout.addWidget(tmpl_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        dlg_layout.addWidget(buttons)

        if dlg.exec_() != QDialog.Accepted:
            return
        selected = tmpl_list.currentItem()
        if not selected:
            return

        tid = selected.data(Qt.UserRole)
        tname = templates[tmpl_list.currentRow()]['template_name']

        reply = QMessageBox.question(
            self, "Şablon Sil",
            f"'{tname}' şablonunu silmek istediğinize emin misiniz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # Admin şifre doğrulama
        if not self._verify_user_password():
            return

        try:
            if self.db.delete_batch_template(tid):
                self.audit.log_action(
                    'TEMPLATE_DELETED',
                    table_name='batch_templates',
                    record_id=tid,
                    description=f"Batch şablonu silindi: '{tname}'"
                )
                QMessageBox.information(self, "Başarılı", f"'{tname}' şablonu silindi.")
            else:
                QMessageBox.critical(self, "Hata", "Şablon silinemedi.")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Şablon silinemedi:\n{e}")

    def _on_finish_batch(self):
        """Aktif batch'i tamamla (GLT panel butonu)."""
        if not self.active_batch:
            return
        self.finish_glt_batch_interactive(self.active_batch, parent=self)

    def finish_glt_batch_interactive(self, batch_data: dict,
                                     parent=None,
                                     verify_password: bool = True,
                                     auto_show_pdf: bool = True):
        """GLT batch bitirme akışı — public helper (Faz-8).

        ORABS `_on_quick_finish` bağlı GLT batch için de bu metodu çağırır
        → FAIL açıklama diyaloğu, PENDING otomatik açıklama, complete_batch,
        audit ve özet PDF üretimi tek noktada yapılır.

        Args:
            batch_data:      test_batches satırı (id + ports listesi dahil).
            parent:          diyalog parent widget'ı (varsayılan: self).
            verify_password: True ise onay sonrası kullanıcı şifresi sorulur.
            auto_show_pdf:   True ise üretilen PDF `os.startfile` ile açılır.
        Return: özet PDF path (üretildiyse) veya None.
        """
        if not batch_data:
            return None
        parent_widget = parent if parent is not None else self

        batch_name = batch_data.get('batch_name', 'Batch')
        ports = batch_data.get('ports', []) or []

        # Port adı çözümleme
        all_ports_list = self.db.get_all_ports()
        all_ports_map = {p['id']: p for p in all_ports_list} if all_ports_list else {}

        fail_ports = [p for p in ports if p.get('status') == 'FAIL']
        pending_ports = [p for p in ports if p.get('status') == 'PENDING']

        # Durum bilgisi
        if fail_ports or pending_ports:
            info_parts = []
            if fail_ports:
                info_parts.append(f"{len(fail_ports)} FAIL")
            if pending_ports:
                info_parts.append(f"{len(pending_ports)} test edilmemiş")
            reply = QMessageBox.question(
                parent_widget, "Batch Bitir",
                f"'{batch_name}' batch'inde {', '.join(info_parts)} port var.\n"
                f"Batch'i yine de tamamlamak istiyor musunuz?",
                QMessageBox.Yes | QMessageBox.No
            )
        else:
            reply = QMessageBox.question(
                parent_widget, "Batch Bitir",
                f"'{batch_name}' batch'ini tamamlamak istiyor musunuz?",
                QMessageBox.Yes | QMessageBox.No
            )
        if reply != QMessageBox.Yes:
            return None

        # Şifre doğrulama (opsiyonel)
        if verify_password and not self._verify_user_password():
            return None

        pdf_path = None
        try:
            # ── FAIL portlar için açıklama iste ──
            for p in fail_ports:
                port_id = p.get('port_id', 0)
                port_info = all_ports_map.get(port_id, {})
                port_name = port_info.get('name', f"Port {port_id}")
                explanation, ok = QInputDialog.getText(
                    parent_widget, "FAIL Açıklaması",
                    f"{port_name} (RFID: {p.get('rfid_tag', '?')}) FAIL oldu.\n"
                    f"Açıklama giriniz:"
                )
                if ok and explanation.strip():
                    self.db.update_batch_port_explanation(
                        batch_data['id'], port_id, explanation.strip()
                    )
                else:
                    self.db.update_batch_port_explanation(
                        batch_data['id'], port_id, "FAIL - Açıklama girilmedi"
                    )

            # ── PENDING portlar için otomatik açıklama ──
            for p in pending_ports:
                port_id = p.get('port_id', 0)
                self.db.update_batch_port_explanation(
                    batch_data['id'], port_id, "Test yapılmadı"
                )

            # Batch verilerini yeniden yükle (açıklamalar güncellendi)
            # NOT: Database'de biten batch için get_batch_details yok; direkt
            # SQL ile portları tazeliyoruz.
            try:
                conn = self.db.connect()
                cur = conn.cursor()
                cur.execute(
                    'SELECT bp.* FROM batch_ports bp '
                    'LEFT JOIN test_records tr ON bp.test_record_id = tr.id '
                    'WHERE bp.batch_id = ? '
                    'ORDER BY CASE WHEN tr.test_start_time IS NULL THEN 1 ELSE 0 END, '
                    '         tr.test_start_time ASC',
                    (int(batch_data['id']),)
                )
                refreshed_ports = [dict(r) for r in cur.fetchall()]
                self.db.close()
                if refreshed_ports:
                    batch_data['ports'] = refreshed_ports
            except Exception:
                try:
                    self.db.close()
                except Exception:
                    pass

            safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_'
                                for c in batch_name).strip()

            self.db.complete_batch(batch_data['id'])
            batch_data['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            batch_data['status'] = 'COMPLETED'

            # ── PDF toplama & özet rapor ──
            batch_dir = (os.path.join(self.pdf_gen.batch_output_dir, safe_name)
                         if self.pdf_gen else None)
            try:
                if self.pdf_gen:
                    reports_dir = self.pdf_gen.output_dir  # "reports"
                    os.makedirs(batch_dir, exist_ok=True)

                    # Bireysel test PDF'lerini batch klasörüne kopyala
                    batch_start = batch_data.get('start_time', '')
                    copied_test_ids = set()
                    from core.database import normalize_rfid as _nrfid
                    for p in batch_data.get('ports', []):
                        rfid = p.get('rfid_tag', '')
                        if not rfid:
                            continue
                        try:
                            conn = self.db.connect()
                            cur = conn.cursor()
                            # RFID normalize karşılaştırma: cihaz 'DA0DAE',
                            # PC '0x00DA0DAE' yazar (bug 2026-08-03).
                            cur.execute(
                                """SELECT test_id, glove_batch_number FROM test_records
                                   WHERE test_start_time >= ?
                                   ORDER BY test_start_time ASC""",
                                (batch_start,)
                            )
                            rows = [r for r in cur.fetchall()
                                    if _nrfid(r[1]) == _nrfid(rfid)]
                            self.db.close()
                            for row in rows:
                                if row[0] and row[0] not in copied_test_ids:
                                    src = os.path.join(reports_dir, f"{row[0]}.pdf")
                                    if os.path.exists(src):
                                        shutil.copy2(src, os.path.join(batch_dir, f"{row[0]}.pdf"))
                                        copied_test_ids.add(row[0])
                        except Exception:
                            _logger.debug("PDF copy failed for rfid %s", rfid)

                    # Özet PDF üret
                    all_ports = self.db.get_all_ports()
                    all_ports_dict = {p['id']: p for p in all_ports}
                    _report_lang = (self.db.get_language()
                                    if hasattr(self.db, 'get_language') else 'tr')
                    pdf_path = self.pdf_gen.generate_batch_summary_report(
                        batch_data, all_ports_dict=all_ports_dict,
                        include_fails=self._include_fails_in_report,
                        lang=_report_lang,
                        audit_records=self._collect_glt_batch_audits(batch_data),
                    )
            except Exception as pdf_err:
                _logger.error("PDF generation error: %s", pdf_err, exc_info=True)
                QMessageBox.warning(parent_widget, "PDF Hatası",
                                    f"Batch raporu oluşturulamadı:\n{pdf_err}")

            # UI refresh — çağrı GLT panel dışından geldiyse zaten no-op olur.
            try:
                self.load_active_batch()
            except Exception:
                pass

            # Audit trail: Batch tamamlandı
            pass_count = sum(1 for p in batch_data.get('ports', [])
                             if p.get('status') == 'PASS')
            fail_count = sum(1 for p in batch_data.get('ports', [])
                             if p.get('status') == 'FAIL')
            pending_count = sum(1 for p in batch_data.get('ports', [])
                                if p.get('status') == 'PENDING')
            self.audit.log_action(
                'BATCH_COMPLETED',
                table_name='test_batches',
                record_id=batch_data['id'],
                description=(
                    f"Batch tamamlandı: '{batch_name}', "
                    f"PASS: {pass_count}, FAIL: {fail_count}, "
                    f"Test yapılmadı: {pending_count}"
                )
            )

            # Audit trail PDF'ini batch klasörüne at
            try:
                self._export_batch_audit_trail(batch_data, batch_dir)
            except Exception:
                pass

            msg = "Batch başarıyla tamamlandı."
            if pdf_path and os.path.exists(pdf_path):
                msg += f"\n\nÖzet rapor: {pdf_path}"
            QMessageBox.information(parent_widget, "Tamamlandı", msg)

            # PDF'i uygulama içinde aç (tam ekran viewer).
            if auto_show_pdf and pdf_path and os.path.exists(pdf_path):
                self._open_pdf_inapp(pdf_path, parent=parent_widget)
        except Exception as e:
            QMessageBox.critical(parent_widget, "Hata",
                                 f"Batch tamamlanamadı:\n{e}")

        return pdf_path

    # ─────────────────────── DIŞARIDAN GÜNCELLEME ───────────────────────
    def update_port_status(self, rfid_tag: str, status: str,
                           test_record_id: int = None, explanation: str = None):
        """
        Dışarıdan çağrılarak (örn. test tamamlandığında) port durumunu günceller.
        rfid_tag: portun RFID etiketi
        status: 'PASS' | 'FAIL'
        """
        # Panel cache'i (self.active_batch) bayat olabilir — özellikle batch
        # ORABS tarafından OTOMATİK başlatıldıysa panel henüz haberdar olmaz
        # ve güncelleme sessizce atlanırdı (bug 2026-08-03). DB'den tazele.
        if not self.active_batch:
            try:
                self.load_active_batch()
            except Exception:
                pass
        if not self.active_batch:
            return
        try:
            ok = self.db.update_batch_port_status(
                self.active_batch['id'], rfid_tag, status,
                test_record_id=test_record_id,
                explanation=explanation
            )
            if not ok:
                _logger.warning(
                    "update_port_status: eşleşme yok (batch=%s rfid=%s)",
                    self.active_batch.get('id'), rfid_tag)
            self.load_active_batch()  # Tablo + harita yenile
        except Exception as e:
            _logger.error("update_port_status error: %s", e)

    def _auto_complete_batch(self):
        """Tüm portlar test edildiyse batch'i otomatik tamamla ve rapor üret"""
        if not self.active_batch:
            return
        try:
            batch_data = self.active_batch  # snapshot
            batch_name = batch_data.get('batch_name', 'Batch')
            safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in batch_name).strip()

            self.db.complete_batch(batch_data['id'])
            batch_data['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            batch_data['status'] = 'COMPLETED'

            # ── PDF toplama & özet rapor ──
            pdf_path = None
            batch_dir = os.path.join(self.pdf_gen.batch_output_dir, safe_name) if self.pdf_gen else None
            try:
                if self.pdf_gen:
                    reports_dir = self.pdf_gen.output_dir
                    os.makedirs(batch_dir, exist_ok=True)

                    # Bireysel test PDF'lerini batch klasörüne kopyala (rapor klasöründe de kalsın)
                    # Tüm RFID tag'lerine ait testleri kopyala (sadece son test değil)
                    batch_start = batch_data.get('start_time', '')
                    copied_test_ids = set()
                    from core.database import normalize_rfid as _nrfid
                    for p in batch_data.get('ports', []):
                        rfid = p.get('rfid_tag', '')
                        if not rfid:
                            continue
                        try:
                            conn = self.db.connect()
                            cur = conn.cursor()
                            # RFID normalize karşılaştırma (bug 2026-08-03).
                            cur.execute(
                                """SELECT test_id, glove_batch_number FROM test_records
                                   WHERE test_start_time >= ?
                                   ORDER BY test_start_time ASC""",
                                (batch_start,)
                            )
                            rows = [r for r in cur.fetchall()
                                    if _nrfid(r[1]) == _nrfid(rfid)]
                            self.db.close()
                            for row in rows:
                                if row[0] and row[0] not in copied_test_ids:
                                    src = os.path.join(reports_dir, f"{row[0]}.pdf")
                                    if os.path.exists(src):
                                        shutil.copy2(src, os.path.join(batch_dir, f"{row[0]}.pdf"))
                                        copied_test_ids.add(row[0])
                        except Exception:
                            _logger.debug("Auto-complete PDF copy failed")

                    # Özet PDF üret
                    all_ports = self.db.get_all_ports()
                    all_ports_dict = {p['id']: p for p in all_ports}
                    _report_lang = self.db.get_language() if hasattr(self.db, 'get_language') else 'tr'
                    pdf_path = self.pdf_gen.generate_batch_summary_report(
                        batch_data, all_ports_dict=all_ports_dict,
                        include_fails=self._include_fails_in_report,
                        lang=_report_lang,
                        audit_records=self._collect_glt_batch_audits(batch_data),
                    )
            except Exception as pdf_err:
                _logger.error("Auto-complete PDF error: %s", pdf_err)

            self.load_active_batch()

            # Audit trail PDF'ini batch klasörüne at
            self._export_batch_audit_trail(batch_data, batch_dir)

            msg = f"Tüm portlar test edildi.\n'{batch_name}' batch'i otomatik tamamlandı."
            if pdf_path and os.path.exists(pdf_path):
                msg += f"\n\nÖzet rapor: {pdf_path}"
            QMessageBox.information(self, "Batch Otomatik Tamamlandı", msg)

            if pdf_path and os.path.exists(pdf_path):
                self._open_pdf_inapp(pdf_path, parent=self)
        except Exception as e:
            _logger.error("_auto_complete_batch error: %s", e)

    def _collect_glt_batch_audits(self, batch_data) -> list:
        """GLT batch raporu denetim izi: batch aralığındaki GLT + USER
        kategorili audit kayıtları (ORAPS/LAF GİRMEZ — kullanıcı isteği
        2026-08-05). Timestamp normalizasyonu _export_batch_audit_trail
        ile aynı (audit ISO 'T', batch_data ise boşluk ayırmaçlı)."""
        try:
            start_time = batch_data.get('start_time', '') or ''
            end_time = (batch_data.get('end_time', '') or
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            if not start_time:
                return []
            _fmts = ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                     '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S')
            dt_start = dt_end = None
            for fmt in _fmts:
                if dt_start is None:
                    try:
                        dt_start = datetime.strptime(start_time, fmt)
                    except ValueError:
                        pass
                if dt_end is None:
                    try:
                        dt_end = datetime.strptime(end_time, fmt)
                    except ValueError:
                        pass
            start_iso = ((dt_start - timedelta(seconds=2)).isoformat()
                         if dt_start else start_time.replace(' ', 'T'))
            end_iso = ((dt_end + timedelta(seconds=5)).isoformat()
                       if dt_end else end_time.replace(' ', 'T'))
            return self.audit.get_audit_trail({
                'date_from': start_iso,
                'date_to': end_iso,
                'categories': ['GLT', 'USER'],
            }) or []
        except Exception:
            return []

    def _export_batch_audit_trail(self, batch_data, batch_dir):
        """Batch başlangıç-bitiş arasındaki audit trail kayıtlarını batch klasörüne PDF olarak atar"""
        try:
            if not self.pdf_gen or not batch_dir:
                return
            start_time = batch_data.get('start_time', '')
            end_time = batch_data.get('end_time', '')
            if not start_time or not end_time:
                return

            # ── Timestamp normalisation ──────────────────────────────────
            # audit_trail timestamps: datetime.isoformat() → '...T...' (T-separator)
            # batch_data end_time  : strftime('%Y-%m-%d %H:%M:%S') → space separator
            # String comparison 'T' > ' ' causes all records to be excluded.
            # Parse both, apply ±margin, reformat as ISO to guarantee
            # BATCH_STARTED and BATCH_COMPLETED records are captured.
            _fmts = ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                     '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S')
            dt_start = dt_end = None
            for fmt in _fmts:
                if dt_start is None:
                    try:
                        dt_start = datetime.strptime(start_time, fmt)
                    except ValueError:
                        pass
                if dt_end is None:
                    try:
                        dt_end = datetime.strptime(end_time, fmt)
                    except ValueError:
                        pass

            if dt_start:
                start_time = (dt_start - timedelta(seconds=2)).isoformat()
            else:
                start_time = start_time.replace(' ', 'T')
            if dt_end:
                end_time = (dt_end + timedelta(seconds=5)).isoformat()
            else:
                end_time = end_time.replace(' ', 'T')

            # Audit trail sorgula (batch başlangıç ≤ timestamp ≤ batch bitiş)
            filters = {
                'date_from': start_time,
                'date_to': end_time
            }
            records = self.audit.get_audit_trail(filters)
            if not records:
                print("[BatchPanel] Batch audit trail: Kayıt bulunamadı.")
                return

            print(f"[BatchPanel] Batch audit trail: {len(records)} kayıt bulundu ({start_time} → {end_time})")

            # PDF üret — doğrudan batch klasörüne yaz. Şirket adı ayarlardan
            # (report_company_name) alınır; sabit metin geçilmez.
            audit_pdf = self.pdf_gen.generate_audit_trail_report(
                records,
                output_dir=batch_dir
            )
            print(f"[BatchPanel] Batch audit trail PDF: {audit_pdf}")
        except Exception as e:
            _logger.error("Batch audit trail export error: %s", e, exc_info=True)

    def refresh_map(self):
        """Sekme değiştiğinde çağrılır (main_window.on_tab_changed uyumu)"""
        self.map_widget.refresh()
        self.load_active_batch()
