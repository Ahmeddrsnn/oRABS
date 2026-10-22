"""Weidmüller IO inner panel (Faz-6a, admin-only).

Live IO monitor + write controls for one or more Weidmüller UR20-FBC-MOD-TCP
couplers. Spawns one `WeidmullerWorker` per active module and renders DI/DO
LEDs and AI/AO bars. Only admins should see this panel; visibility is
enforced by the parent `OrapsMainWidget`.

Threading rules (Plan B):
- Workers poll Modbus and emit `registers_updated`; this panel updates
  UI only and forwards write commands via `worker.write_do/write_ao`.
- DO/AO write events return through `write_completed` and are logged via
  `WeidmullerManager.log_write()` on the GUI thread (ORAPS audit).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QComboBox, QCheckBox, QProgressBar, QDoubleSpinBox,
    QMessageBox, QSizePolicy, QScrollArea,
)

from core.batch_manager import BatchManager
from core.weidmuller_manager import WeidmullerManager
from core.weidmuller_worker import WeidmullerWorker, raw_to_percent


_PANEL_QSS = """
QFrame#ioCard {
    background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px;
}
QFrame#ioCard QLabel#ioCardTitle {
    color: #111827; font-size: 13px; font-weight: 700;
}
QFrame#ioCard QLabel#ioPointLabel {
    color: #374151; font-size: 12px;
}
QFrame#ioCard QLabel#ioPointMeta {
    color: #6B7280; font-size: 11px;
}
QPushButton#ledBtn {
    border: 1px solid #1F2937; border-radius: 14px;
    min-width: 28px; min-height: 28px; max-width: 28px; max-height: 28px;
}
"""

_STATUS_QSS_OK = "color:#065F46; background:#D1FAE5; padding:4px 10px; border-radius:4px;"
_STATUS_QSS_ERR = "color:#7F1D1D; background:#FEE2E2; padding:4px 10px; border-radius:4px;"
_STATUS_QSS_WARN = "color:#92400E; background:#FEF3C7; padding:4px 10px; border-radius:4px;"

_LED_ON = "#22c55e"
_LED_OFF = "#3f3f46"


def _led_style(on: bool, clickable: bool) -> str:
    color = _LED_ON if on else _LED_OFF
    cursor = "pointer" if clickable else "default"
    return (f"#ledBtn {{ background:{color}; }} "
            f"#ledBtn:hover {{ background:{color}; }}")


def _format_point_label(prefix: str, point: Dict) -> str:
    """'DI3 sensor' gibi etiket üret. name == varsayılan ise tekrarı önle."""
    ch_label = f"{prefix}{point['channel'] + 1}"
    name = (point.get('name') or '').strip()
    if not name or name == ch_label:
        return ch_label
    return f"{ch_label}  {name}"


class _DiCell(QFrame):
    def __init__(self, point: Dict, link_label: str = '', parent=None):
        super().__init__(parent)
        self.point = point
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)
        self.led = QPushButton()
        self.led.setObjectName("ledBtn")
        self.led.setEnabled(False)
        self.led.setStyleSheet(_led_style(False, False))
        lay.addWidget(self.led)
        self.label = QLabel(_format_point_label('DI', point))
        self.label.setObjectName("ioPointLabel")
        lay.addWidget(self.label)
        if link_label:
            self.link_lbl = QLabel(f"→ {link_label}")
            self.link_lbl.setObjectName("ioPointMeta")
            lay.addWidget(self.link_lbl)
        lay.addStretch(1)

    def set_value(self, bit: int):
        self.led.setStyleSheet(_led_style(bool(bit), False))


class _DoCell(QFrame):
    def __init__(self, point: Dict, on_toggle, link_label: str = '', parent=None):
        super().__init__(parent)
        self.point = point
        self._on_toggle = on_toggle
        self._state = 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)
        self.led = QPushButton()
        self.led.setObjectName("ledBtn")
        self.led.setStyleSheet(_led_style(False, True))
        self.led.clicked.connect(self._on_click)
        lay.addWidget(self.led)
        self.label = QLabel(_format_point_label('DO', point))
        self.label.setObjectName("ioPointLabel")
        lay.addWidget(self.label)
        if link_label:
            self.link_lbl = QLabel(f"→ {link_label}")
            self.link_lbl.setObjectName("ioPointMeta")
            lay.addWidget(self.link_lbl)
        lay.addStretch(1)

    def _on_click(self):
        new_val = 0 if self._state else 1
        self._on_toggle(self.point['channel'], new_val)

    def set_value(self, bit: int):
        self._state = 1 if bit else 0
        self.led.setStyleSheet(_led_style(bool(bit), True))


class _AiCell(QFrame):
    def __init__(self, point: Dict, link_label: str = '', parent=None):
        super().__init__(parent)
        self.point = point
        lay = QGridLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(2)
        suffix = f"   → {link_label}" if link_label else ''
        self.label = QLabel(_format_point_label('AI', point) + suffix)
        self.label.setObjectName("ioPointLabel")
        lay.addWidget(self.label, 0, 0, 1, 2)
        self.bar = QProgressBar()
        self.bar.setRange(-100, 100)
        self.bar.setValue(0)
        self.bar.setFormat("%v %")
        self.bar.setMaximumHeight(14)
        lay.addWidget(self.bar, 1, 0, 1, 2)
        self.meta = QLabel("—")
        self.meta.setObjectName("ioPointMeta")
        lay.addWidget(self.meta, 2, 0, 1, 2)

    def set_value(self, raw: int, pct: float):
        scale = float(self.point.get('scale', 1.0))
        offset = float(self.point.get('offset', 0.0))
        self.bar.setValue(int(max(-100, min(100, pct))))
        unit = (self.point.get('unit') or '').strip()
        # Scale=1 ve offset=0 ise scaled değeri ham ile aynı → gösterme.
        if abs(scale - 1.0) < 1e-9 and abs(offset) < 1e-9:
            self.meta.setText(f"ham={raw}  {pct:.2f}%")
        else:
            scaled = raw * scale + offset
            unit_disp = unit if unit and unit != '%' else ''
            self.meta.setText(
                f"ham={raw}  {pct:.2f}%  ({scaled:.3f}{(' ' + unit_disp) if unit_disp else ''})"
            )


class _AoCell(QFrame):
    def __init__(self, point: Dict, on_write, link_label: str = '', parent=None):
        super().__init__(parent)
        self.point = point
        self._on_write = on_write
        lay = QGridLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(2)
        suffix = f"   → {link_label}" if link_label else ''
        self.label = QLabel(_format_point_label('AO', point) + suffix)
        self.label.setObjectName("ioPointLabel")
        lay.addWidget(self.label, 0, 0, 1, 3)
        self.bar = QProgressBar()
        self.bar.setRange(-100, 100)
        self.bar.setValue(0)
        self.bar.setFormat("%v %")
        self.bar.setMaximumHeight(14)
        lay.addWidget(self.bar, 1, 0, 1, 3)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(-100.0, 100.0)
        self.spin.setDecimals(1)
        self.spin.setSuffix(" %")
        self.spin.setSingleStep(1.0)
        lay.addWidget(self.spin, 2, 0)
        self.btn = QPushButton("Yaz")
        self.btn.clicked.connect(self._on_click)
        lay.addWidget(self.btn, 2, 1)
        self.meta = QLabel("—")
        self.meta.setObjectName("ioPointMeta")
        lay.addWidget(self.meta, 2, 2)

    def _on_click(self):
        self._on_write(self.point['channel'], float(self.spin.value()))

    def set_value(self, raw: int, pct: float):
        self.bar.setValue(int(max(-100, min(100, pct))))
        self.meta.setText(f"ham={raw}  {pct:.2f}%")


class _ModuleView(QWidget):
    """Tek bir Weidmüller modülünün canlı IO görünümü. Worker'ı 
    dışarıdan (WeidmullerBridge) verilir; view sadece UI tutar."""

    def __init__(self, wm: WeidmullerManager, module: Dict,
                 worker: Optional[WeidmullerWorker] = None, parent=None):
        super().__init__(parent)
        self.wm = wm
        self.module = module
        self.module_id = module['id']
        self.worker: Optional[WeidmullerWorker] = worker
        self._di_cells: Dict[int, _DiCell] = {}
        self._do_cells: Dict[int, _DoCell] = {}
        self._ai_cells: Dict[int, _AiCell] = {}
        self._ao_cells: Dict[int, _AoCell] = {}
        self._build_ui()
        self._reload_points()
        self._wire_worker_signals()

    def _wire_worker_signals(self):
        if self.worker is None:
            return
        self.worker.registers_updated.connect(self._on_registers)
        self.worker.connection_status.connect(self._on_status)
        self.worker.coupler_identified.connect(self._on_coupler)
        self.worker.write_completed.connect(self._on_write_done)

    # ── UI ────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # Header
        head = QHBoxLayout()
        title = QLabel(self.module['name'])
        f = title.font(); f.setPointSize(12); f.setBold(True); title.setFont(f)
        head.addWidget(title)
        meta = QLabel(f"  {self.module['host']}:{self.module['port']}  "
                      f"unit={self.module['unit_id']}")
        meta.setStyleSheet("color:#6B7280;")
        head.addWidget(meta)
        head.addStretch(1)
        self.status_lbl = QLabel("Başlatılıyor…")
        self.status_lbl.setStyleSheet(_STATUS_QSS_WARN)
        head.addWidget(self.status_lbl)
        self.coupler_lbl = QLabel("")
        self.coupler_lbl.setStyleSheet("color:#6B7280; font-size:11px;")
        head.addWidget(self.coupler_lbl)
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedWidth(34)
        self.refresh_btn.setToolTip("Modülü yeniden başlat")
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        head.addWidget(self.refresh_btn)
        root.addLayout(head)

        # 4 grup yatay
        groups = QHBoxLayout()
        groups.setSpacing(10)
        self.di_box = self._make_group("Dijital Girişler (DI)")
        self.do_box = self._make_group("Dijital Çıkışlar (DO)")
        self.ai_box = self._make_group("Analog Girişler (AI)")
        self.ao_box = self._make_group("Analog Çıkışlar (AO)")
        for box in (self.di_box, self.do_box, self.ai_box, self.ao_box):
            groups.addWidget(box['frame'], 1)
        root.addLayout(groups, 1)

    def _make_group(self, title: str) -> Dict:
        frame = QFrame()
        frame.setObjectName("ioCard")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("ioCardTitle")
        outer.addWidget(lbl)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        return {'frame': frame, 'layout': layout, 'inner': inner}

    # ── Points rebuild ──────────────────────────────────────────
    def _reload_points(self):
        # Clear
        for box in (self.di_box, self.do_box, self.ai_box, self.ao_box):
            while box['layout'].count():
                item = box['layout'].takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
        self._di_cells.clear(); self._do_cells.clear()
        self._ai_cells.clear(); self._ao_cells.clear()

        points = self.wm.list_points(module_id=self.module_id, only_visible=True)
        for p in points:
            pt = p['point_type']
            link_label = ''
            if p.get('link_type') and p.get('link_id') is not None:
                try:
                    link_label = self.wm.resolve_link_label(
                        p['link_type'], p['link_id'])
                except Exception:
                    link_label = ''
                role = (p.get('link_role') or '').strip()
                if link_label and role:
                    link_label += f" [{role}]"
            if pt == 'DI':
                cell = _DiCell(p, link_label=link_label)
                self.di_box['layout'].addWidget(cell)
                self._di_cells[p['channel']] = cell
            elif pt == 'DO':
                cell = _DoCell(p, self._on_do_toggle, link_label=link_label)
                self.do_box['layout'].addWidget(cell)
                self._do_cells[p['channel']] = cell
            elif pt == 'AI':
                cell = _AiCell(p, link_label=link_label)
                self.ai_box['layout'].addWidget(cell)
                self._ai_cells[p['channel']] = cell
            elif pt == 'AO':
                cell = _AoCell(p, self._on_ao_write, link_label=link_label)
                self.ao_box['layout'].addWidget(cell)
                self._ao_cells[p['channel']] = cell
        for box in (self.di_box, self.do_box, self.ai_box, self.ao_box):
            box['layout'].addStretch(1)

    # ── Worker lifecycle ────────────────────────────────────────
    # Worker is owned by WeidmullerBridge; view never creates or stops it.
    def attach_worker(self, worker: Optional[WeidmullerWorker]):
        """(Re)bind this view to a freshly-spawned worker. Called by
        IoPanel after bridge.start_all() / reload() so that view status
        labels and live registers come from the actual running thread.
        Idempotent: no-op if same worker already attached."""
        if worker is self.worker:
            return
        if self.worker is not None:
            self.detach_worker()
        self.worker = worker
        self._wire_worker_signals()
        # Worker zaten run() içinde connection_status emit etmiş olabilir
        # (start_all → attach mikro-yarışı). Son snapshot'ı oku ve hemen
        # status_lbl'i hizala ki Overview kartıyla senkron olsun.
        if worker is not None:
            try:
                snap = worker.last_connection()
                if snap is not None:
                    ok, msg = snap
                    self._on_status(self.module_id, ok, msg)
                coupler = worker.last_coupler()
                if coupler:
                    self._on_coupler(self.module_id, coupler)
            except Exception:
                import traceback; traceback.print_exc()

    def detach_worker(self):
        """Disconnect signal handlers before view destruction."""
        w = self.worker
        self.worker = None
        if w is None:
            return
        for sig, slot in (
            (w.registers_updated, self._on_registers),
            (w.connection_status, self._on_status),
            (w.coupler_identified, self._on_coupler),
            (w.write_completed, self._on_write_done),
        ):
            try:
                sig.disconnect(slot)
            except Exception:
                pass

    # ── Signal handlers ─────────────────────────────────────────
    def _on_registers(self, module_id: int, values: dict, ts_iso: str):
        if module_id != self.module_id:
            return
        for ch, bit in values.get('DI', {}).items():
            cell = self._di_cells.get(ch)
            if cell:
                cell.set_value(bit)
        for ch, bit in values.get('DO', {}).items():
            cell = self._do_cells.get(ch)
            if cell:
                cell.set_value(bit)
        for ch, info in values.get('AI', {}).items():
            cell = self._ai_cells.get(ch)
            if cell:
                cell.set_value(info['raw'], info['pct'])
        for ch, info in values.get('AO', {}).items():
            cell = self._ao_cells.get(ch)
            if cell:
                cell.set_value(info['raw'], info['pct'])

    def _on_status(self, module_id: int, ok: bool, msg: str):
        if module_id != self.module_id:
            return
        self.status_lbl.setText(msg)
        self.status_lbl.setStyleSheet(_STATUS_QSS_OK if ok else _STATUS_QSS_ERR)

    def _on_coupler(self, module_id: int, ascii_id: str):
        if module_id != self.module_id:
            return
        self.coupler_lbl.setText(f"[{ascii_id}]" if ascii_id else "")

    def _on_write_done(self, module_id: int, point_type: str, channel: int,
                       value, success: bool, err: str):
        if module_id != self.module_id:
            return
        try:
            self.wm.log_write(module_id, point_type, channel, value, success, err)
        except Exception:
            pass
        # IO write fail QMessageBox geçici olarak devre dışı.
        # Donanım bağlı değilken sürekli popup spam'i önlemek için kapatıldı.
        # TODO: Tekrar aktif edilecek (bkz. repo memory io-write-fail-popup).
        # if not success:
        #     QMessageBox.warning(self, "IO Yazma Hatası",
        #                         f"{point_type}{channel}: {err}")

    # ── User actions ────────────────────────────────────────────
    def _on_do_toggle(self, channel: int, new_value: int):
        if self.worker:
            self.worker.write_do(channel, new_value)

    def _on_ao_write(self, channel: int, percent: float):
        if self.worker:
            self.worker.write_ao(channel, percent=percent)

    def _on_refresh_clicked(self):
        """Manuel modül yeniden başlatma: parent IoPanel üzerinden
        stop→reload→start sırasını çalıştır (DB race önlenir)."""
        p = self.parentWidget()
        while p is not None and not hasattr(p, 'reload_with_bridge'):
            p = p.parentWidget()
        if p is not None:
            p.reload_with_bridge()

    def shutdown(self):
        self.detach_worker()


class IoPanel(QWidget):
    """Admin-only Weidmüller IO panel; tüm aktif modülleri listeler.
    Worker'lar WeidmullerBridge tarafından sahiplenilir; bu panel sadece
    görsel attach yapar."""

    def __init__(self, database, auth_manager, audit_manager,
                 bridge=None, parent=None):
        super().__init__(parent)
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        self.wm = WeidmullerManager(database, auth_manager, audit_manager)
        self.bridge = bridge  # WeidmullerBridge or None (degraded mode)
        self._module_views: List[_ModuleView] = []

        self.setStyleSheet(_PANEL_QSS)
        self._build_ui()
        self._reload_modules()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.unlinked_lbl = QLabel("")
        self.unlinked_lbl.setVisible(False)
        self.unlinked_lbl.setStyleSheet(_STATUS_QSS_WARN)
        self.unlinked_lbl.setToolTip(
            "Henüz hiçbir fiziksel ögeye (kapı / port / LAF) bağlanmamış "
            "IO noktaları var. Ayarlar → IO Noktaları menüsünden 🔗 Bağla "
            "butonuyla eşleyin."
        )
        header.addWidget(self.unlinked_lbl)
        header.addStretch(1)
        self.refresh_btn = QPushButton("↻ Modülleri Yenile")
        self.refresh_btn.clicked.connect(self.reload)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        self.empty_lbl = QLabel("Aktif IO modülü yok. Ayarlar → IO Modülleri "
                                "menüsünden ekleyin.")
        self.empty_lbl.setStyleSheet("color:#6B7280; padding:20px;")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setVisible(False)
        root.addWidget(self.empty_lbl)

        self.modules_container = QWidget()
        self.modules_layout = QVBoxLayout(self.modules_container)
        self.modules_layout.setContentsMargins(0, 0, 0, 0)
        self.modules_layout.setSpacing(16)
        root.addWidget(self.modules_container, 1)

    def _reload_modules(self):
        # Eski view'ları kapat
        for v in self._module_views:
            v.shutdown()
            v.setParent(None)
            v.deleteLater()
        self._module_views.clear()

        modules = self.wm.list_modules(only_active=True)
        if not modules:
            self.empty_lbl.setVisible(True)
            self._update_unlinked_badge()
            return
        self.empty_lbl.setVisible(False)
        # NOT: bridge yaşam döngüsü (start_all / reload / stop_all) ORAPS
        # ana penceresine ait — burada bridge.reload() çağırmıyoruz çünkü
        # Database singleton `self.conn`'u worker thread'leri tarafından
        # kapatılabiliyor ve bu metot ana thread'de çalışırken paralel
        # `wm.list_*` çağrılarını çökertiyor (sqlite3.ProgrammingError:
        # "Cannot operate on a closed database"). View'lar bridge.workers
        # sözlüğünü sadece okur; modül henüz worker'a sahip değilse view
        # boş worker ile açılır ve bir sonraki reload'da kavrar.
        for m in modules:
            worker = None
            if self.bridge is not None:
                worker = self.bridge.workers.get(int(m['id']))
            view = _ModuleView(self.wm, m, worker=worker)
            self.modules_layout.addWidget(view)
            self._module_views.append(view)
        self._update_unlinked_badge()

    def _update_unlinked_badge(self):
        try:
            n = len(self.wm.list_unlinked())
        except Exception:
            n = 0
        if n > 0:
            self.unlinked_lbl.setText(f"⚠ Eşlenmemiş {n} IO")
            self.unlinked_lbl.setVisible(True)
        else:
            self.unlinked_lbl.setVisible(False)

    # ── External hooks ──────────────────────────────────────────
    def reload(self):
        self._reload_modules()

    def attach_workers_from_bridge(self):
        """Bridge.start_all() çağrıldıktan sonra (worker'lar dict'e
        düştükten sonra) çağır. Her view'ı, modül id'sine karşılık
        gelen worker'a bağlar; view'lar yeniden inşa edilmez, sadece
        sinyal kabloları kurulur ve status_lbl ilk poll'da güncellenir."""
        if self.bridge is None:
            return
        for v in self._module_views:
            try:
                w = self.bridge.workers.get(int(v.module_id))
                v.attach_worker(w)
            except Exception:
                import traceback; traceback.print_exc()

    def reload_with_bridge(self):
        """Tam sırada yeniden başlatma: önce worker thread'leri durdur
        (DB conn race önlenir), sonra view'ları DB'den oku, sonra
        worker'ları tekrar başlat. Manuel ↻ butonu bu yolu kullanır."""
        if self.bridge is not None:
            try:
                self.bridge.stop_all()
            except Exception:
                import traceback; traceback.print_exc()
        self._reload_modules()
        if self.bridge is not None:
            try:
                self.bridge.start_all()
            except Exception:
                import traceback; traceback.print_exc()
            self.attach_workers_from_bridge()

    def on_settings_changed(self):
        self.reload()

    def shutdown(self):
        for v in self._module_views:
            v.shutdown()
        self._module_views.clear()
