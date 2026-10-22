"""LAF inner panel (Faz-5).

Live readings from the clean-room monitor board, plus an alarm log and a
PDF report button. Owns the LafWorker QThread instance and wires it up
to LafManager for DB snapshots.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout,
    QPushButton, QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QDateTimeEdit, QDialog, QDialogButtonBox, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from core.laf_manager import LafManager
from core.laf_worker import LafWorker


_CARD_QSS = """
QFrame#lafCard {
    background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px;
}
QFrame#lafCard QLabel#lafCardLabel {
    color: #6B7280; font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.5px;
}
QFrame#lafCard QLabel#lafCardValue {
    color: #111827; font-size: 26px; font-weight: 700;
}
QFrame#lafCard QLabel#lafCardUnit {
    color: #6B7280; font-size: 13px;
}
"""

_STATUS_QSS_OK = "color:#065F46; background:#D1FAE5; padding:4px 10px; border-radius:4px;"
_STATUS_QSS_ERR = "color:#7F1D1D; background:#FEE2E2; padding:4px 10px; border-radius:4px;"
_STATUS_QSS_WARN = "color:#92400E; background:#FEF3C7; padding:4px 10px; border-radius:4px;"


class _SensorCard(QFrame):
    def __init__(self, sensor: Dict, parent=None):
        super().__init__(parent)
        self.setObjectName("lafCard")
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.sensor = sensor

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)

        self.label = QLabel(sensor['label'])
        self.label.setObjectName("lafCardLabel")
        lay.addWidget(self.label)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.value = QLabel("—")
        self.value.setObjectName("lafCardValue")
        self.unit = QLabel(sensor.get('unit', '') or '')
        self.unit.setObjectName("lafCardUnit")
        self.unit.setAlignment(Qt.AlignBottom)
        row.addWidget(self.value)
        row.addWidget(self.unit)
        row.addStretch(1)
        lay.addLayout(row)

        self.meta = QLabel("")
        self.meta.setStyleSheet("color:#9CA3AF; font-size:11px;")
        lay.addWidget(self.meta)

    def set_value(self, value: Optional[float], ts_iso: str):
        if value is None:
            self.value.setText("—")
            self.meta.setText("okuma yok")
            return
        if isinstance(value, float) and abs(value) < 1000:
            txt = f"{value:.2f}".rstrip('0').rstrip('.')
        else:
            txt = f"{value:.0f}" if isinstance(value, float) else str(value)
        self.value.setText(txt)
        try:
            ts = datetime.fromisoformat(ts_iso)
            self.meta.setText(ts.strftime("%H:%M:%S"))
        except Exception:
            self.meta.setText("")


class LafPanel(QWidget):
    """LAF live view + alarm log."""

    def __init__(self, database, auth_manager, audit_manager, parent=None):
        super().__init__(parent)
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        self.laf = LafManager(database, auth_manager, audit_manager)

        self.worker: Optional[LafWorker] = None
        self._cards: Dict[int, _SensorCard] = {}
        self._last_snapshot_ts: Optional[datetime] = None
        self._snapshot_period_sec = 300
        self._latest_readings: Dict[int, Optional[float]] = {}

        self.setStyleSheet(_CARD_QSS)
        self._build_ui()
        self._reload_sensors()
        self._start_worker()

    # ── UI ────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Status bar
        header = QHBoxLayout()
        title = QLabel("Laminar Air Flow Ünitesi")
        f = title.font(); f.setPointSize(13); f.setBold(True); title.setFont(f)
        header.addWidget(title)
        header.addStretch(1)
        self.status_lbl = QLabel("Başlatılıyor…")
        self.status_lbl.setStyleSheet(_STATUS_QSS_WARN)
        header.addWidget(self.status_lbl)
        self.refresh_btn = QPushButton("↻ Yenile")
        self.refresh_btn.clicked.connect(self.restart_worker)
        header.addWidget(self.refresh_btn)
        self.overview_btn = QPushButton("🏠 Ana Ekran Sensörleri…")
        self.overview_btn.setToolTip(
            "ORAPS Genel Bakış sekmesinde gösterilecek sensörleri seç"
        )
        self.overview_btn.clicked.connect(self._on_pick_overview_sensors)
        header.addWidget(self.overview_btn)
        root.addLayout(header)

        # Cards grid
        self.cards_frame = QFrame()
        self.cards_layout = QGridLayout(self.cards_frame)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setHorizontalSpacing(12)
        self.cards_layout.setVerticalSpacing(12)
        root.addWidget(self.cards_frame)

        # Alarm log + report row
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        alarm_box = QFrame()
        alarm_box.setObjectName("lafCard")
        ab = QVBoxLayout(alarm_box)
        ab.setContentsMargins(14, 12, 14, 12)
        ab_title = QLabel("Cihaz Alarmları")
        ab_title.setObjectName("lafCardLabel")
        ab.addWidget(ab_title)
        self.alarm_list = QListWidget()
        self.alarm_list.setMinimumHeight(140)
        self.alarm_list.setStyleSheet(
            "QListWidget { border:1px solid #E5E7EB; border-radius:6px; }"
        )
        ab.addWidget(self.alarm_list)
        bottom.addWidget(alarm_box, 2)

        # Actions
        actions = QFrame()
        actions.setObjectName("lafCard")
        av = QVBoxLayout(actions)
        av.setContentsMargins(14, 12, 14, 12)
        av.setSpacing(8)
        ac_title = QLabel("Eylemler")
        ac_title.setObjectName("lafCardLabel")
        av.addWidget(ac_title)
        self.report_btn = QPushButton("📄 Tarih Aralığı Raporu (CSV)")
        self.report_btn.clicked.connect(self._on_export_report)
        av.addWidget(self.report_btn)
        self.snapshot_btn = QPushButton("💾 Şimdi Snapshot Al")
        self.snapshot_btn.clicked.connect(self._snapshot_now)
        av.addWidget(self.snapshot_btn)
        self.snapshot_info = QLabel("Snapshot periyodu: 5 dk")
        self.snapshot_info.setStyleSheet("color:#6B7280; font-size:11px;")
        av.addWidget(self.snapshot_info)
        av.addStretch(1)
        bottom.addWidget(actions, 1)

        root.addLayout(bottom)

        # Refresh alarms list every 30 s
        self._alarm_timer = QTimer(self)
        self._alarm_timer.setInterval(30_000)
        self._alarm_timer.timeout.connect(self._refresh_alarms)
        self._alarm_timer.start()

    # ── Sensor cards rebuild ─────────────────────────────────────
    def _reload_sensors(self):
        # Clear current cards
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cards.clear()

        sensors = self.laf.list_sensors(only_visible=True)
        cols = 3
        for i, s in enumerate(sensors):
            card = _SensorCard(s)
            r, c = divmod(i, cols)
            self.cards_layout.addWidget(card, r, c)
            self._cards[s['id']] = card

        # Snapshot period from settings
        try:
            cfg = self.laf.get_settings()
            self._snapshot_period_sec = max(60, int(cfg.get('laf_snapshot_sec', '300')))
        except Exception:
            self._snapshot_period_sec = 300
        self.snapshot_info.setText(
            f"Snapshot periyodu: {self._snapshot_period_sec // 60} dk"
        )

        self._refresh_alarms()

    # ── Worker lifecycle ─────────────────────────────────────────
    def _start_worker(self):
        if self.worker is not None:
            return
        self.worker = LafWorker(self.laf)
        self.worker.readings_updated.connect(self._on_readings)
        self.worker.alarm_received.connect(self._on_alarm)
        self.worker.connection_status.connect(self._on_status)
        self.worker.start()

    def stop_worker(self):
        if self.worker is None:
            return
        self.worker.stop()
        if not self.worker.wait(3000):
            self.worker.terminate()
        self.worker = None

    def restart_worker(self):
        self.stop_worker()
        self._reload_sensors()
        self._start_worker()

    # ── Signal handlers ──────────────────────────────────────────
    def _on_readings(self, readings: dict, ts_iso: str):
        self._latest_readings = dict(readings)
        for sid, card in self._cards.items():
            card.set_value(readings.get(sid), ts_iso)

        # Snapshot to DB?
        try:
            now = datetime.fromisoformat(ts_iso)
        except Exception:
            now = datetime.now()
        if (self._last_snapshot_ts is None
                or (now - self._last_snapshot_ts).total_seconds() >= self._snapshot_period_sec):
            self.laf.add_snapshot(readings, timestamp=ts_iso)
            self._last_snapshot_ts = now

    def _on_alarm(self, flag_code: str, message: str):
        self.laf.add_alarm(flag_code, message)
        self._refresh_alarms()

    def _on_status(self, ok: bool, msg: str):
        self.status_lbl.setText(msg)
        self.status_lbl.setStyleSheet(_STATUS_QSS_OK if ok else _STATUS_QSS_ERR)

    # ── Helpers ──────────────────────────────────────────────────
    def _refresh_alarms(self):
        self.alarm_list.clear()
        try:
            rows = self.laf.list_recent_alarms(20)
        except Exception:
            rows = []
        if not rows:
            self.alarm_list.addItem(QListWidgetItem("(alarm yok)"))
            return
        for a in rows:
            try:
                ts = datetime.fromisoformat(a['timestamp']).strftime("%d.%m %H:%M")
            except Exception:
                ts = a['timestamp']
            mark = "✓" if a.get('cleared_at') else "⚠"
            txt = f"{mark} {ts}  [{a['flag_code']}]  {a.get('message') or ''}".rstrip()
            self.alarm_list.addItem(QListWidgetItem(txt))

    def _snapshot_now(self):
        if not self._latest_readings:
            QMessageBox.information(self, "Snapshot", "Henüz okuma yok.")
            return
        ts = datetime.now().isoformat()
        self.laf.add_snapshot(self._latest_readings, timestamp=ts)
        self._last_snapshot_ts = datetime.fromisoformat(ts)
        QMessageBox.information(self, "Snapshot",
                                f"{len(self._latest_readings)} sensör kaydedildi.")

    def _on_pick_overview_sensors(self):
        """ORAPS Genel Bakış sekmesinde gösterilecek LAF sensörlerini
        seçmek için diyalog aç."""
        try:
            all_sensors = self.laf.list_sensors()
        except Exception as e:
            QMessageBox.warning(self, "LAF", f"Sensörler okunamadı:\n{e}")
            return
        dlg = _LafOverviewPickerDialog(all_sensors, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        selection = dlg.get_selection()
        errors = []
        for sid, show in selection.items():
            try:
                self.laf.update_sensor(sid, show_on_overview=1 if show else 0)
            except Exception as e:
                errors.append(f"#{sid}: {e}")
        if errors:
            QMessageBox.warning(self, "LAF",
                                "Bazı sensörler güncellenemedi:\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "LAF",
                                    "Ana ekran seçimi kaydedildi.")

    def _on_export_report(self):
        dlg = _DateRangeDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        start, end = dlg.get_range()
        rows = self.laf.query_readings(start.isoformat(), end.isoformat())
        if not rows:
            QMessageBox.information(self, "Rapor", "Bu aralıkta kayıt yok.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV Olarak Kaydet",
            f"laf_rapor_{start:%Y%m%d}_{end:%Y%m%d}.csv",
            "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                import csv
                w = csv.writer(f, delimiter=';')
                w.writerow(['timestamp', 'sensor_id', 'label', 'value', 'unit'])
                for r in rows:
                    w.writerow([r['timestamp'], r['sensor_id'], r['label'],
                                '' if r['value'] is None else r['value'],
                                r.get('unit') or ''])
            QMessageBox.information(self, "Rapor", f"{len(rows)} satır yazıldı:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Rapor", f"Hata: {e}")

    # ── Outside hooks ────────────────────────────────────────────
    def on_settings_changed(self):
        """Called when LAF settings or sensor list changes."""
        self.restart_worker()

    def shutdown(self):
        """Call before app exit to release the serial port + thread."""
        self._alarm_timer.stop()
        self.stop_worker()


class _DateRangeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tarih Aralığı Seç")
        self.setMinimumWidth(360)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Başlangıç:"))
        self.start = QDateTimeEdit(datetime.now() - timedelta(days=1))
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat("dd.MM.yyyy HH:mm")
        lay.addWidget(self.start)
        lay.addWidget(QLabel("Bitiş:"))
        self.end = QDateTimeEdit(datetime.now())
        self.end.setCalendarPopup(True)
        self.end.setDisplayFormat("dd.MM.yyyy HH:mm")
        lay.addWidget(self.end)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def get_range(self):
        return (self.start.dateTime().toPyDateTime(),
                self.end.dateTime().toPyDateTime())


class _LafOverviewPickerDialog(QDialog):
    """ORAPS Genel Bakış sekmesinde gösterilecek LAF sensörlerini
    işaretlemek için basit checkbox listesi."""

    def __init__(self, sensors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ana Ekran Sensörleri")
        self.setMinimumSize(520, 420)
        self._sensors = list(sensors)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "ORAPS <b>Genel Bakış</b> sekmesinde gösterilecek sensörleri seçin:"
        ))

        self.table = QTableWidget(len(self._sensors), 3, self)
        self.table.setHorizontalHeaderLabels(["Etiket", "Tip", "Ana Ekran"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)

        for r, s in enumerate(self._sensors):
            it_label = QTableWidgetItem(s.get('label', ''))
            it_label.setData(Qt.UserRole, s['id'])
            it_type = QTableWidgetItem(s.get('sensor_type', '') or '')
            it_chk = QTableWidgetItem('')
            it_chk.setFlags(it_chk.flags() | Qt.ItemIsUserCheckable)
            it_chk.setCheckState(
                Qt.Checked if s.get('show_on_overview') else Qt.Unchecked
            )
            it_chk.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 0, it_label)
            self.table.setItem(r, 1, it_type)
            self.table.setItem(r, 2, it_chk)

        lay.addWidget(self.table)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def get_selection(self) -> Dict[int, bool]:
        out: Dict[int, bool] = {}
        for r in range(self.table.rowCount()):
            sid = self.table.item(r, 0).data(Qt.UserRole)
            checked = self.table.item(r, 2).checkState() == Qt.Checked
            out[int(sid)] = checked
        return out
