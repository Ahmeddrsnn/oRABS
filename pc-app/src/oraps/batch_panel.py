"""Oraps Batch panel (Faz-4).

Shows the active batch banner, lists door-lock configurations, and lets
the operator start a new batch using any active configuration. Admin gets
additional buttons to create/edit/delete configurations.

Emits `batch_changed` whenever the active batch row mutates so the
parent OrapsMain can refresh the 3D viewer in the Overview tab.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QLineEdit, QComboBox,
    QMessageBox, QSizePolicy,
)

from core.batch_manager import BatchManager, PermissionDenied, BatchInProgress
from .batch_config_dialog import BatchConfigDialog


_STATUS_LABEL = {
    'idle':     ('—',          '#6b7280'),
    'running':  ('🟢 ÇALIŞIYOR', '#059669'),
    'paused':   ('⏸ DURAKLATILDI', '#d97706'),
    'finished': ('✓ Bitti',    '#6b7280'),
}


class OrapsBatchPanel(QWidget):
    batch_changed = pyqtSignal()

    def __init__(self, database, auth_manager, audit_manager, parent=None):
        super().__init__(parent)
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        self.bm = BatchManager(database, auth_manager, audit_manager)
        # Weidmüller bridge — batch config dialog'unda yalnızca DO (kilit)
        # çıkışına bağlı kapı gruplarını göstermek için kullanılır. oraps_main
        # tarafından `set_io_bridge` ile enjekte edilir; None ise filtre
        # devre dışı (tüm gruplar gösterilir).
        self._io_bridge = None

        self._build_ui()
        self.refresh()

    def set_io_bridge(self, bridge):
        """oraps_main → WeidmullerBridge örneğini bağla. Bridge'in
        `get_lock_output_targets()` metodu batch config diyaloğunda grup
        filtreleme için kullanılır."""
        self._io_bridge = bridge

    # ── UI ──────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(25, 25, 25, 25)
        root.setSpacing(18)

        # Header
        header = QLabel("🔢 Batch Yönetimi")
        header.setStyleSheet("font-size: 22px; font-weight: 700; color: #1f2937;")
        root.addWidget(header)

        subtitle = QLabel(
            "Her batch için hangi kapıların açık / kilitli olacağı önceden "
            "tanımlanır. Operatör batch başlatırken konfigi seçer."
        )
        subtitle.setStyleSheet("color: #6b7280; font-size: 13px;")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # ── Active batch card ──
        self.active_card = QFrame()
        self.active_card.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e5e7eb;"
            " border-radius: 10px; padding: 16px; }"
        )
        active_layout = QVBoxLayout(self.active_card)
        active_layout.setSpacing(10)

        active_title = QLabel("Aktif Batch")
        active_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #374151;")
        active_layout.addWidget(active_title)

        self.active_info = QLabel()
        self.active_info.setStyleSheet("font-size: 13px; color: #1f2937;")
        self.active_info.setTextFormat(Qt.RichText)
        self.active_info.setWordWrap(True)
        active_layout.addWidget(self.active_info)

        active_btns = QHBoxLayout()
        self.btn_pause = QPushButton("⏸ Duraklat")
        self.btn_resume = QPushButton("▶ Devam Et")
        self.btn_finish = QPushButton("⏹ Bitir")
        for b in (self.btn_pause, self.btn_resume, self.btn_finish):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton { padding: 7px 14px; border: 1px solid #d1d5db;"
                " background: #ffffff; border-radius: 6px; font-size: 12px; }"
                " QPushButton:hover { background: #f3f4f6; }"
            )
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_resume.clicked.connect(self._on_resume)
        self.btn_finish.clicked.connect(self._on_finish)
        active_btns.addWidget(self.btn_pause)
        active_btns.addWidget(self.btn_resume)
        active_btns.addWidget(self.btn_finish)
        active_btns.addStretch()
        active_layout.addLayout(active_btns)

        root.addWidget(self.active_card)

        # ── Configurations table ──
        configs_header = QHBoxLayout()
        ch_label = QLabel("Kapı Konfigürasyonları")
        ch_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #374151;")
        configs_header.addWidget(ch_label)
        configs_header.addStretch()

        self.btn_new = QPushButton("+ Yeni Konfig")
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.setStyleSheet(
            "QPushButton { background: #2563eb; color: white; border: none;"
            " padding: 7px 14px; border-radius: 6px; font-weight: 600; font-size: 12px; }"
            " QPushButton:hover { background: #1d4ed8; }"
        )
        self.btn_new.clicked.connect(self._on_new_config)
        configs_header.addWidget(self.btn_new)
        root.addLayout(configs_header)

        self.config_table = QTableWidget(0, 6)
        self.config_table.setHorizontalHeaderLabels(
            ['Ad', 'Açık', 'Kilitli', 'Açıklama', '', '']
        )
        self.config_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.config_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for col in (1, 2, 4, 5):
            self.config_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.config_table.verticalHeader().setVisible(False)
        self.config_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.config_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.config_table.setAlternatingRowColors(True)
        self.config_table.setStyleSheet(
            "QTableWidget { background:#ffffff; border:1px solid #e5e7eb; border-radius:8px; }"
            " QHeaderView::section { background:#f9fafb; padding:8px; border:none;"
            " border-bottom:1px solid #e5e7eb; font-weight:600; color:#374151; }"
        )
        root.addWidget(self.config_table)

        # ── Start-new-batch row ──
        start_frame = QFrame()
        start_frame.setStyleSheet(
            "QFrame { background:#f0f9ff; border:1px solid #bae6fd; border-radius:8px; padding:14px; }"
        )
        start_layout = QHBoxLayout(start_frame)
        start_layout.setSpacing(10)

        start_label = QLabel("Yeni Batch:")
        start_label.setStyleSheet("font-weight:600; color:#0c4a6e;")
        start_layout.addWidget(start_label)

        self.batch_name_edit = QLineEdit()
        self.batch_name_edit.setPlaceholderText("Batch adı (örn: Penisilin-001)")
        self.batch_name_edit.setMinimumWidth(220)
        start_layout.addWidget(self.batch_name_edit)

        self.config_combo = QComboBox()
        self.config_combo.setMinimumWidth(220)
        start_layout.addWidget(self.config_combo)

        self.btn_start = QPushButton("▶ Başlat")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setStyleSheet(
            "QPushButton { background:#059669; color:white; border:none;"
            " padding:8px 18px; border-radius:6px; font-weight:600; }"
            " QPushButton:hover { background:#047857; }"
        )
        self.btn_start.clicked.connect(self._on_start)
        start_layout.addWidget(self.btn_start)
        start_layout.addStretch()
        root.addWidget(start_frame)

    # ── Refresh ─────────────────────────────────────────────────
    def refresh(self):
        """Reload active batch + configurations from DB and update UI."""
        self._refresh_active_card()
        self._refresh_configs_table()
        self._refresh_combo()
        self._apply_permissions()

    def _refresh_active_card(self):
        ab = self.bm.get_active_batch()
        if not ab or ab.get('status') in ('idle', 'finished') or not ab.get('batch_name'):
            self.active_info.setText(
                "<span style='color:#6b7280;'>Aktif batch yok. "
                "Aşağıdan yeni bir batch başlatın.</span>"
            )
            self._set_active_buttons(running=False, paused=False)
            return
        status = ab.get('status', 'idle')
        label, color = _STATUS_LABEL.get(status, ('—', '#6b7280'))
        cfg_name = ab.get('config_name') or '(silinmiş konfig)'
        started_by = ab.get('started_by_name') or '?'
        started_at = (ab.get('started_at') or '')[:19].replace('T', ' ')
        self.active_info.setText(
            f"<b>Batch:</b> {ab.get('batch_name')}<br>"
            f"<b>Konfig:</b> {cfg_name} &nbsp; "
            f"<b>Durum:</b> <span style='color:{color};font-weight:600;'>{label}</span><br>"
            f"<b>Başlatan:</b> {started_by} &nbsp;&nbsp; "
            f"<b>Başlangıç:</b> {started_at}"
        )
        self._set_active_buttons(
            running=(status == 'running'),
            paused=(status == 'paused'),
        )

    def _set_active_buttons(self, *, running: bool, paused: bool):
        active_exists = running or paused
        self.btn_pause.setVisible(running)
        self.btn_resume.setVisible(paused)
        self.btn_finish.setVisible(active_exists)
        self.btn_start.setEnabled(not active_exists)
        self.batch_name_edit.setEnabled(not active_exists)
        self.config_combo.setEnabled(not active_exists)

    def _refresh_configs_table(self):
        configs = self.bm.list_configs(include_inactive=False)
        self.config_table.setRowCount(0)
        can_manage = self.auth.get_current_user_role() in ('Admin', 'Supervisor')
        active_id = (self.bm.get_active_batch() or {}).get('config_id')

        for cfg in configs:
            row = self.config_table.rowCount()
            self.config_table.insertRow(row)
            name_item = QTableWidgetItem(cfg['config_name'])
            if cfg['id'] == active_id:
                name_item.setText(f"★ {cfg['config_name']}")
            self.config_table.setItem(row, 0, name_item)
            open_item = QTableWidgetItem(
                f"{cfg['open_count']} / {cfg['open_count'] + cfg['locked_count']}"
            )
            open_item.setTextAlignment(Qt.AlignCenter)
            self.config_table.setItem(row, 1, open_item)
            locked_item = QTableWidgetItem(str(cfg['locked_count']))
            locked_item.setTextAlignment(Qt.AlignCenter)
            self.config_table.setItem(row, 2, locked_item)
            desc_item = QTableWidgetItem(cfg.get('description') or '')
            self.config_table.setItem(row, 3, desc_item)

            edit_btn = QPushButton("✏ Düzenle")
            edit_btn.setCursor(Qt.PointingHandCursor)
            edit_btn.clicked.connect(lambda _c, cid=cfg['id']: self._on_edit_config(cid))
            self.config_table.setCellWidget(row, 4, edit_btn)
            del_btn = QPushButton("🗑 Sil")
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.clicked.connect(lambda _c, cid=cfg['id']: self._on_delete_config(cid))
            self.config_table.setCellWidget(row, 5, del_btn)

            if not can_manage:
                edit_btn.setEnabled(False)
                del_btn.setEnabled(False)
                edit_btn.setToolTip("Sadece admin veya supervisor değiştirebilir")
                del_btn.setToolTip("Sadece admin veya supervisor silebilir")

    def _refresh_combo(self):
        prev = self.config_combo.currentData()
        self.config_combo.blockSignals(True)
        self.config_combo.clear()
        for cfg in self.bm.list_configs(include_inactive=False):
            label = f"{cfg['config_name']} ({cfg['open_count']} açık / {cfg['locked_count']} kilitli)"
            self.config_combo.addItem(label, cfg['id'])
        if prev is not None:
            idx = self.config_combo.findData(prev)
            if idx >= 0:
                self.config_combo.setCurrentIndex(idx)
        self.config_combo.blockSignals(False)

    def _apply_permissions(self):
        can_manage = self.auth.get_current_user_role() in ('Admin', 'Supervisor')
        self.btn_new.setVisible(can_manage)

    # ── Handlers ──────────────────────────────────
    def _collect_door_groups(self):
        """Faz-9: Kapı gruplarını `door_indices` üye listesiyle birlikte
        hazırla (BatchConfigDialog için). `get_door_labels()` her satırda
        `group_id` içerir; buradan grup üyeliği türetilir. `list_door_groups`
        grup adı/id'sini verir.

        DO (kilit) çıkışına bağlı olmayan gruplar/kapılar filtrelenir —
        kullanıcı yalnızca gerçekten output'a bağlı olan kapı gruplarını
        batch konfigüne dahil etsin diye. Filtre bridge üzerinden
        (`get_lock_output_targets`) yapılır; bridge yoksa filtre devre
        dışıdır.

        Return: List[Dict{id, name, description, door_indices: List[int]}]
        """
        try:
            groups = self.bm.list_door_groups() or []
        except Exception:
            groups = []
        try:
            labels = self.bm.get_door_labels() or []
        except Exception:
            labels = []
        # DO'ya bağlı kapı/grup setleri — bridge yoksa filtre yapma.
        doors_with_do: set = set()
        groups_with_do: set = set()
        _filter_active = False
        try:
            if self._io_bridge is not None:
                d_set, g_set = self._io_bridge.get_lock_output_targets()
                doors_with_do = {int(x) for x in d_set}
                groups_with_do = {int(x) for x in g_set}
                _filter_active = True
        except Exception:
            _filter_active = False
        # group_id → [door_index...] (gruba atanmış TÜM kapılar — isimsiz dahil).
        # Batch config grup bazlı çalıştığı için bir kapı gruba atandığında
        # label'i olsun olmasın, o grubun DO kanalına yazılır. Eski davranış
        # sadece isimli kapıları dahil ediyordu → isimsiz kapılar kilitlenmiyordu.
        members: dict = {}
        for row in labels:
            gid = row.get('group_id')
            didx = row.get('door_index')
            if gid is None or didx is None:
                continue
            try:
                gid = int(gid); didx = int(didx)
            except (TypeError, ValueError):
                continue
            # Kapı seviyesinde filtre: eğer grubun kendisi DO'ya bağlı değilse
            # yalnızca DO'ya bağlı kapıları grubun üyesi olarak dahil et.
            if _filter_active and gid not in groups_with_do:
                if didx not in doors_with_do:
                    continue
            members.setdefault(gid, []).append(didx)
        out = []
        for g in groups:
            gid = g.get('id')
            if gid is None:
                continue
            try:
                gid_i = int(gid)
            except (TypeError, ValueError):
                continue
            mem = sorted(members.get(gid_i, []))
            if not mem:
                continue   # üyesi olmayan grup config'e dahil edilmez
            # Grup seviyesinde filtre: grubun kendisi DO'ya bağlı değil VE
            # hiçbir üyesi DO'ya bağlı değilse grubu gizle.
            if _filter_active:
                if gid_i not in groups_with_do and not any(
                        m in doors_with_do for m in mem):
                    continue
            out.append({
                'id': gid_i,
                'name': g.get('name') or f'Grup #{gid_i}',
                'description': g.get('description') or '',
                'door_indices': mem,
            })
        return out

    def _collect_available_ports(self) -> list:
        """RFID eşleştirilmiş portları döndür (batch config port seçimi için).
        Return: [{port_index, label, rfid_tag}, ...]"""
        try:
            ports = self.bm.get_port_labels() or []
        except Exception:
            return []
        return [
            {'port_index': p['port_index'],
             'label': (p.get('label') or '').strip() or f"Port {p['port_index']}",
             'rfid_tag': (p.get('rfid_tag') or '').strip()}
            for p in ports
            if (p.get('rfid_tag') or '').strip()
        ]

    def _collect_stop_groups(self) -> list:
        """Faz-10: machine_stop DO'suna bağlı kapı gruplarını hazırla
        (BatchConfigDialog'daki "Makine Durdurma Grupları" bölümü için).
        Bridge yoksa boş döner (bölüm gizlenir).
        Return: List[Dict{id, name, door_indices}]"""
        if self._io_bridge is None:
            return []
        try:
            _doors, stop_gids = self._io_bridge.get_machine_stop_targets()
            stop_gids = {int(x) for x in stop_gids}
        except Exception:
            return []
        if not stop_gids:
            return []
        try:
            groups = self.bm.list_door_groups() or []
        except Exception:
            groups = []
        try:
            labels = self.bm.get_door_labels() or []
        except Exception:
            labels = []
        members: dict = {}
        for row in labels:
            gid = row.get('stop_group_id')   # Faz-10b: durdurma üyeliği
            didx = row.get('door_index')
            if gid is None or didx is None:
                continue
            try:
                members.setdefault(int(gid), []).append(int(didx))
            except (TypeError, ValueError):
                continue
        out = []
        for g in groups:
            try:
                gid = int(g.get('id'))
            except (TypeError, ValueError):
                continue
            if gid not in stop_gids:
                continue
            out.append({
                'id': gid,
                'name': g.get('name') or f'Grup #{gid}',
                'door_indices': sorted(members.get(gid, [])),
            })
        return out

    def _on_new_config(self):
        if self.auth.get_current_user_role() not in ('Admin', 'Supervisor'):
            QMessageBox.warning(self, "Yetki Yok",
                                "Yeni konfig oluşturmak için admin veya supervisor olmalısınız.")
            return
        dlg = BatchConfigDialog(
            self,
            door_groups=self._collect_door_groups(),
            available_ports=self._collect_available_ports(),
            stop_groups=self._collect_stop_groups(),
            is_edit=False,
        )
        if dlg.exec_() != dlg.Accepted:
            return
        try:
            self.bm.create_config(
                dlg.get_name(), dlg.get_description(), dlg.get_door_states(),
                port_indices=dlg.get_selected_ports(),
                stop_group_ids=dlg.get_selected_stop_groups(),
                wait_glt_pass=dlg.get_wait_glt_pass(),
            )
        except (PermissionDenied, ValueError) as e:
            QMessageBox.warning(self, "Hata", str(e))
            return
        self.refresh()
        self.batch_changed.emit()

    def _on_edit_config(self, config_id: int):
        cfg = self.bm.get_config(config_id)
        if not cfg:
            QMessageBox.warning(self, "Hata", "Konfig bulunamadı.")
            return
        dlg = BatchConfigDialog(
            self,
            door_groups=self._collect_door_groups(),
            initial_name=cfg['config_name'],
            initial_description=cfg.get('description', '') or '',
            initial_states=cfg.get('door_states', {}),
            initial_port_indices=cfg.get('port_indices') or [],
            available_ports=self._collect_available_ports(),
            stop_groups=self._collect_stop_groups(),
            initial_stop_group_ids=cfg.get('stop_group_ids'),
            initial_wait_glt=bool(cfg.get('wait_glt_pass')),
            is_edit=True,
        )
        if dlg.exec_() != dlg.Accepted:
            return
        try:
            self.bm.update_config(
                config_id, dlg.get_name(), dlg.get_description(),
                dlg.get_door_states(),
                port_indices=dlg.get_selected_ports(),
                stop_group_ids=dlg.get_selected_stop_groups(),
                wait_glt_pass=dlg.get_wait_glt_pass(),
            )
        except (PermissionDenied, BatchInProgress, ValueError) as e:
            QMessageBox.warning(self, "Hata", str(e))
            return
        self.refresh()
        self.batch_changed.emit()

    def _on_delete_config(self, config_id: int):
        cfg = self.bm.get_config(config_id)
        if not cfg:
            return
        if QMessageBox.question(
            self, "Konfig Sil",
            f"'{cfg['config_name']}' konfigürasyonunu silmek istediğinizden emin misiniz?\n\n"
            "(Geçmiş batch'lerin izlenebilirliği için soft delete uygulanır.)",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        try:
            self.bm.delete_config(config_id)
        except (PermissionDenied, BatchInProgress) as e:
            QMessageBox.warning(self, "Hata", str(e))
            return
        self.refresh()
        self.batch_changed.emit()

    def _on_start(self):
        name = self.batch_name_edit.text().strip()
        cfg_id = self.config_combo.currentData()
        if not name:
            QMessageBox.warning(self, "Eksik Bilgi", "Batch adı zorunludur.")
            return
        if cfg_id is None:
            QMessageBox.warning(self, "Eksik Bilgi", "Bir konfig seçin.")
            return
        try:
            self.bm.start_batch(name, cfg_id)
        except (PermissionDenied, BatchInProgress, ValueError) as e:
            QMessageBox.warning(self, "Hata", str(e))
            return
        self.batch_name_edit.clear()
        self.refresh()
        self.batch_changed.emit()

    def _on_pause(self):
        try: self.bm.pause_batch()
        except (PermissionDenied, BatchInProgress) as e:
            QMessageBox.warning(self, "Hata", str(e)); return
        self.refresh(); self.batch_changed.emit()

    def _on_resume(self):
        try: self.bm.resume_batch()
        except (PermissionDenied, BatchInProgress) as e:
            QMessageBox.warning(self, "Hata", str(e)); return
        self.refresh(); self.batch_changed.emit()

    def _on_finish(self):
        # Faz-8: ORABS bitirme akışının tamamı (onay + bağlı GLT batch'in
        # kendi bitirme mantığı + ORABS özet PDF) overview'daki hızlı
        # bitirme ile aynı olsun diye oraya delege edilir.
        ov = getattr(getattr(self.window(), 'oraps_panel', None),
                     'overview', None)
        if ov is not None and hasattr(ov, '_on_quick_finish'):
            ov._on_quick_finish()
            self.refresh()
            self.batch_changed.emit()
            return
        # Fallback (overview erişilemedi): eski basit akış.
        if QMessageBox.question(
            self, "Batch Bitir",
            "Aktif batch'i bitirmek istediğinizden emin misiniz?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        try: self.bm.finish_batch()
        except (PermissionDenied, BatchInProgress) as e:
            QMessageBox.warning(self, "Hata", str(e)); return
        self.refresh(); self.batch_changed.emit()
