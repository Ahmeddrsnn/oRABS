"""Door-group configuration editor dialog (Oraps Faz-9).

Admin-only modal used to create or edit a `batch_door_config` row. Operators
never see this dialog; the Batch panel hides the buttons that open it.

Faz-9: Kapı yerine **kapı grubu** seçimi. Kullanıcı grupları oluşturur
(Kapı Eşleme Modu → grup atama) ve batch config'te grupları tek tıkla
"Açık" / "Kilitli" olarak işaretler. Grup içindeki tüm kapılar aynı
state'i alır. Grup yoksa uyarı gösterilir ve Kaydet devre dışı bırakılır.

Layout
------
- Name + description fields at the top
- Grup toggle butonları (2-row grid)
  - 🟢 open / 🔴 locked. Click to flip.
- Quick actions: Open all / Lock all / Invert
- Live counter "X açık grup / Y kilitli grup (toplam Z kapı)"
- OK / Cancel
"""

from __future__ import annotations

import math
from typing import Dict, Optional, List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QFormLayout, QFrame, QMessageBox, QSizePolicy,
    QWidget, QCheckBox, QScrollArea,
)


# UI yerleşim varsayılanı (grup sayısı dinamik gelir; grid burada hesaplanır).
COLS_MAX = 4


_GROUP_QSS_OPEN = (
    "QPushButton { background-color: #10b981; color: white; border: 2px solid #059669;"
    " border-radius: 8px; padding: 12px; font-weight: 600; font-size: 13px; min-height: 60px; }"
    " QPushButton:hover { background-color: #059669; }"
)
_GROUP_QSS_LOCKED = (
    "QPushButton { background-color: #ef4444; color: white; border: 2px solid #b91c1c;"
    " border-radius: 8px; padding: 12px; font-weight: 600; font-size: 13px; min-height: 60px; }"
    " QPushButton:hover { background-color: #dc2626; }"
)


class BatchConfigDialog(QDialog):
    """Create or edit a door-group based lock configuration (Faz-9).

    Args:
        door_groups: List[Dict] — her satır: {id, name, door_indices: List[int]}
        initial_states: Kaydedilmiş {door_index: 'open'|'locked'} map — grup
            state'i grup üyelerinin çoğunluğuna göre deduce edilir.
    """

    def __init__(self, parent=None,
                 door_groups: Optional[List[Dict]] = None,
                 initial_name: str = '',
                 initial_description: str = '',
                 initial_states: Optional[Dict[str, str]] = None,
                 initial_port_indices: Optional[List[int]] = None,
                 available_ports: Optional[List[Dict]] = None,
                 stop_groups: Optional[List[Dict]] = None,
                 initial_stop_group_ids: Optional[List[int]] = None,
                 initial_wait_glt: bool = False,
                 is_edit: bool = False):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Kapı Konfigürasyonu Düzenle" if is_edit else "Yeni Kapı Konfigürasyonu")
        self.setMinimumWidth(640)
        # Çok port/grup eklenince alt kısım taşıyordu — tam ekran açılır.
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

        # Kapı gruplarını yerel yapıya sakla — id → {name, door_indices}.
        self._groups: Dict[int, Dict] = {}
        for g in (door_groups or []):
            try:
                gid = int(g.get('id'))
            except (TypeError, ValueError):
                continue
            name = (g.get('name') or '').strip()
            members = [int(x) for x in (g.get('door_indices') or [])
                       if isinstance(x, (int, float, str)) and str(x).strip()]
            if not name or not members:
                continue
            self._groups[gid] = {'name': name, 'door_indices': members}
        # Sıralı liste — grid + counter için.
        self._group_ids: List[int] = sorted(
            self._groups.keys(),
            key=lambda gid: (self._groups[gid]['name'] or '').lower()
        )

        # Grup state'i (id → 'open'|'locked'). initial_states verilirse
        # grup içindeki kapıların ÇOĞUNLUĞUNA göre deduce et; eşitse 'open'.
        self._states: Dict[int, str] = {}
        for gid in self._group_ids:
            self._states[gid] = self._deduce_group_state(
                gid, initial_states or {}
            )

        self._buttons: Dict[int, QPushButton] = {}
        self._btn_save: Optional[QPushButton] = None

        # Port seçimi: sadece RFID atanmış portlar seçilebilir.
        # available_ports: [{port_index, label, rfid_tag}, ...]
        self._available_ports: List[Dict] = [
            p for p in (available_ports or [])
            if (p.get('rfid_tag') or '').strip()
        ]
        self._port_checks: Dict[int, 'QCheckBox'] = {}
        self._init_ports = set(initial_port_indices or [])

        # Faz-10: makine durdurma grupları (machine_stop DO'suna bağlı
        # gruplar). initial None = seçim yapılmamış → hepsi işaretli gelir.
        self._stop_groups: List[Dict] = list(stop_groups or [])
        self._stop_checks: Dict[int, 'QCheckBox'] = {}
        self._init_stop_ids = (None if initial_stop_group_ids is None
                               else {int(x) for x in initial_stop_group_ids})
        self._init_wait_glt = bool(initial_wait_glt)

        # Grid boyutu grup sayısına göre.
        n_groups = max(1, len(self._group_ids))
        self._cols = min(COLS_MAX, n_groups)
        self._rows = int(math.ceil(n_groups / self._cols))

        self._build_ui(initial_name, initial_description)
        self._refresh_buttons()
        self._refresh_counter()

    def _deduce_group_state(self, gid: int,
                            initial_states: Dict) -> str:
        """Kaydedilmiş {door_index: state} map'inden grubun state'ini çıkar.
        Grup üyelerinin en az yarısı 'locked' ise 'locked', aksi 'open'."""
        members = self._groups[gid]['door_indices']
        if not members:
            return 'open'
        locked = 0
        for didx in members:
            raw = (initial_states.get(str(didx))
                   or initial_states.get(didx) or 'open')
            if str(raw).lower() == 'locked':
                locked += 1
        return 'locked' if locked * 2 >= len(members) else 'open'

    # ── UI ──────────────────────────────────────────────────────
    def _build_ui(self, name: str, description: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # Header form
        form = QFormLayout()
        form.setSpacing(8)
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("örn: Penisilin Standart")
        self.desc_edit = QLineEdit(description)
        self.desc_edit.setPlaceholderText("Bu konfig ne için kullanılıyor? (opsiyonel)")
        form.addRow("Konfig Adı:", self.name_edit)
        form.addRow("Açıklama:", self.desc_edit)
        root.addLayout(form)

        # Grup yoksa uyarı ekranı + Kaydet devre dışı
        if not self._group_ids:
            warn = QFrame()
            warn.setStyleSheet(
                "QFrame { background:#fef3c7; border:2px solid #f59e0b;"
                " border-radius:10px; padding:14px; }"
            )
            wl = QVBoxLayout(warn)
            wl.setSpacing(6)
            title = QLabel("⚠ Kapı grubu bulunamadı")
            title.setStyleSheet(
                "color:#92400e; font-weight:700; font-size:14px;"
            )
            wl.addWidget(title)
            msg = QLabel(
                "Batch konfigürasyonu grup bazlı düzenleniyor. Önce en az "
                "bir kapı grubu oluşturun:<br><br>"
                "&nbsp;&nbsp;<b>1.</b> Genel Bakış → <b>🚪 Kapı Eşleme Modu</b>'nu açın.<br>"
                "&nbsp;&nbsp;<b>2.</b> 3D modelde bir kapıya tıklayın.<br>"
                "&nbsp;&nbsp;<b>3.</b> Grup satırında <b>➕</b> ile yeni grup oluşturun.<br>"
                "&nbsp;&nbsp;<b>4.</b> İlgili kapıları aynı gruba atayın.<br><br>"
                "Grup(lar)ı oluşturduktan sonra bu diyaloğu tekrar açın."
            )
            msg.setTextFormat(Qt.RichText)
            msg.setStyleSheet("color:#78350f; font-size:12px;")
            msg.setWordWrap(True)
            wl.addWidget(msg)
            root.addWidget(warn)
        else:
            # Hint
            hint = QLabel(
                "Sadece <b>oluşturulmuş kapı grupları</b> batch konfigüne "
                "dahil edilebilir. Bir grubun butonuna tıklayarak grubun "
                "içindeki tüm kapıları aynı anda açık/kilitli yapabilirsiniz."
                "<br>🟢 = Açık (operatör kullanabilir) &nbsp;&nbsp;"
                "🔴 = Kilitli (kilit aktif)"
            )
            hint.setTextFormat(Qt.RichText)
            hint.setStyleSheet("color: #6b7280; font-size: 12px;")
            hint.setWordWrap(True)
            root.addWidget(hint)

            # Group grid
            grid_frame = QFrame()
            grid_frame.setStyleSheet(
                "background: #f9fafb; border-radius: 10px; padding: 12px;"
            )
            grid = QGridLayout(grid_frame)
            grid.setSpacing(10)
            for pos, gid in enumerate(self._group_ids):
                row = pos // self._cols
                col = pos % self._cols
                btn = QPushButton()
                btn.setCursor(Qt.PointingHandCursor)
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                btn.clicked.connect(
                    lambda _checked, g=gid: self._toggle_group(g)
                )
                self._buttons[gid] = btn
                grid.addWidget(btn, row, col)
            root.addWidget(grid_frame)

            # Quick actions
            actions = QHBoxLayout()
            btn_open_all = QPushButton("Hepsini Aç")
            btn_open_all.setCursor(Qt.PointingHandCursor)
            btn_open_all.clicked.connect(self._open_all)
            btn_lock_all = QPushButton("Hepsini Kilitle")
            btn_lock_all.setCursor(Qt.PointingHandCursor)
            btn_lock_all.clicked.connect(self._lock_all)
            btn_invert = QPushButton("Tersine Çevir")
            btn_invert.setCursor(Qt.PointingHandCursor)
            btn_invert.clicked.connect(self._invert)
            for b in (btn_open_all, btn_lock_all, btn_invert):
                b.setStyleSheet(
                    "QPushButton { padding: 8px 14px; border: 1px solid #d1d5db;"
                    " background: #ffffff; border-radius: 6px; font-size: 12px; }"
                    " QPushButton:hover { background: #f3f4f6; }"
                )
                actions.addWidget(b)
            actions.addStretch()
            self.counter_label = QLabel()
            self.counter_label.setStyleSheet(
                "color: #1f2937; font-weight: 600; font-size: 12px;"
            )
            actions.addWidget(self.counter_label)
            root.addLayout(actions)

        # ── Port Seçimi ────────────────────────────────────────────
        # Sadece RFID eşleştirilmiş portlar listelenir.
        port_section = QFrame()
        port_section.setStyleSheet(
            "QFrame { background:#f0f9ff; border:1px solid #bae6fd;"
            " border-radius:8px; padding:12px; }"
        )
        port_lay = QVBoxLayout(port_section)
        port_lay.setSpacing(6)
        port_title = QLabel("<b>Port Seçimi</b> — Batch'e dahil edilecek portlar")
        port_title.setStyleSheet("color:#0c4a6e; font-size:12px;")
        port_lay.addWidget(port_title)
        port_hint = QLabel(
            "Sadece RFID eşleştirilmiş portlar seçilebilir. "
            "Seçili portların testleri tamamlanmadan batch bitmez."
        )
        port_hint.setStyleSheet("color:#64748b; font-size:11px;")
        port_hint.setWordWrap(True)
        port_lay.addWidget(port_hint)

        if not self._available_ports:
            no_port = QLabel("⚠ RFID eşleştirilmiş port bulunamadı.")
            no_port.setStyleSheet("color:#92400e; font-size:14px; padding:12px;")
            port_lay.addWidget(no_port)
        else:
            port_scroll = QScrollArea()
            port_scroll.setWidgetResizable(True)
            port_scroll.setMaximumHeight(280)
            port_scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
            port_inner = QWidget()
            port_grid = QGridLayout(port_inner)
            port_grid.setSpacing(8)
            port_grid.setContentsMargins(6, 6, 6, 6)
            _pcols = 2
            _cb_qss = (
                "QCheckBox { font-size:14px; padding:8px 6px; spacing:8px; }"
                " QCheckBox::indicator { width:22px; height:22px; }"
            )
            for i, p in enumerate(self._available_ports):
                pidx = int(p['port_index'])
                lbl = (p.get('label') or '').strip() or f"Port {pidx}"
                rfid = (p.get('rfid_tag') or '').strip()
                cb = QCheckBox(f"{lbl}  ({rfid[:14]})")
                cb.setStyleSheet(_cb_qss)
                cb.setCursor(Qt.PointingHandCursor)
                cb.setChecked(pidx in self._init_ports)
                self._port_checks[pidx] = cb
                port_grid.addWidget(cb, i // _pcols, i % _pcols)
            port_scroll.setWidget(port_inner)
            port_lay.addWidget(port_scroll)
            # Tümünü seç / temizle
            pact = QHBoxLayout()
            pact.setSpacing(8)
            btn_sel_all = QPushButton("Tümünü Seç")
            btn_sel_all.setCursor(Qt.PointingHandCursor)
            btn_sel_all.setStyleSheet(
                "font-size:13px; padding:8px 16px; border:1px solid #d1d5db;"
                " border-radius:6px; background:#ffffff;"
            )
            btn_sel_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self._port_checks.values()])
            btn_clr_all = QPushButton("Temizle")
            btn_clr_all.setCursor(Qt.PointingHandCursor)
            btn_clr_all.setStyleSheet(
                "font-size:13px; padding:8px 16px; border:1px solid #d1d5db;"
                " border-radius:6px; background:#ffffff;"
            )
            btn_clr_all.clicked.connect(lambda: [cb.setChecked(False) for cb in self._port_checks.values()])
            pact.addWidget(btn_sel_all)
            pact.addWidget(btn_clr_all)
            pact.addStretch()
            port_lay.addLayout(pact)
        root.addWidget(port_section)

        # ── Makine Durdurma Grupları (Faz-10) ─────────────────────
        # Yalnızca machine_stop DO'suna bağlı gruplar listelenir. Seçili
        # grupların kapıları batch sırasında açılırsa makine durdurulur.
        if self._stop_groups:
            stop_section = QFrame()
            stop_section.setStyleSheet(
                "QFrame { background:#fef2f2; border:1px solid #fecaca;"
                " border-radius:8px; padding:12px; }"
            )
            stop_lay = QVBoxLayout(stop_section)
            stop_lay.setSpacing(6)
            stop_title = QLabel("<b>🛑 Makine Durdurma Grupları</b> — "
                                "bu batch'te izlenecek gruplar")
            stop_title.setStyleSheet("color:#7f1d1d; font-size:12px;")
            stop_lay.addWidget(stop_title)
            stop_hint = QLabel(
                "Seçili gruplardaki bir kapı batch sırasında açılırsa bağlı "
                "röle çeker ve makine durdurulur. Seçilmeyen gruplar bu "
                "batch'te makine durdurmaz."
            )
            stop_hint.setStyleSheet("color:#64748b; font-size:11px;")
            stop_hint.setWordWrap(True)
            stop_lay.addWidget(stop_hint)
            _scb_qss = (
                "QCheckBox { font-size:14px; padding:8px 6px; spacing:8px; }"
                " QCheckBox::indicator { width:22px; height:22px; }"
            )
            stop_grid = QGridLayout()
            stop_grid.setSpacing(8)
            _scols = 2
            for i, g in enumerate(self._stop_groups):
                gid = int(g['id'])
                n_doors = len(g.get('door_indices') or [])
                cb = QCheckBox(f"{g.get('name') or f'Grup #{gid}'}  "
                               f"({n_doors} kapı)")
                cb.setStyleSheet(_scb_qss)
                cb.setCursor(Qt.PointingHandCursor)
                cb.setChecked(self._init_stop_ids is None
                              or gid in self._init_stop_ids)
                self._stop_checks[gid] = cb
                stop_grid.addWidget(cb, i // _scols, i % _scols)
            stop_lay.addLayout(stop_grid)
            root.addWidget(stop_section)

        # ── İki aşamalı akış (Faz-12) ────────────────────────────
        flow_section = QFrame()
        flow_section.setStyleSheet(
            "QFrame { background:#eef2ff; border:1px solid #c7d2fe;"
            " border-radius:8px; padding:12px; }"
        )
        flow_lay = QVBoxLayout(flow_section)
        flow_lay.setSpacing(6)
        self.wait_glt_chk = QCheckBox(
            "⏳ Önce GLT batch'i tamamlansın (iki aşamalı akış)"
        )
        self.wait_glt_chk.setStyleSheet(
            "QCheckBox { font-size:14px; font-weight:600; padding:4px 2px;"
            " spacing:8px; color:#3730a3; }"
            " QCheckBox::indicator { width:22px; height:22px; }"
        )
        self.wait_glt_chk.setCursor(Qt.PointingHandCursor)
        self.wait_glt_chk.setChecked(self._init_wait_glt)
        flow_lay.addWidget(self.wait_glt_chk)
        flow_hint = QLabel(
            "İşaretliyse: batch GLT aşamasında başlar — tüm kapılar açık, "
            "makine durdurma röleleri aktif. Batch'teki tüm portlar test "
            "edilmeden (PASS, FAIL için açıklama girilir) ORABS aşamasına "
            "geçilemez ve makine başlayamaz. Geçişte kilitlenecek kapıların "
            "kapalı olması istenir."
        )
        flow_hint.setStyleSheet("color:#64748b; font-size:11px;")
        flow_hint.setWordWrap(True)
        flow_lay.addWidget(flow_hint)
        root.addWidget(flow_section)

        # Dialog buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("İptal")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        self._btn_save = QPushButton("Kaydet")
        self._btn_save.setCursor(Qt.PointingHandCursor)
        self._btn_save.setDefault(True)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_save.setStyleSheet(
            "QPushButton { background: #2563eb; color: white; border: none;"
            " padding: 9px 22px; border-radius: 6px; font-weight: 600; }"
            " QPushButton:hover { background: #1d4ed8; }"
            " QPushButton:disabled { background:#9ca3af; }"
        )
        btn_cancel.setStyleSheet(
            "QPushButton { background: #ffffff; color: #374151; border: 1px solid #d1d5db;"
            " padding: 9px 22px; border-radius: 6px; }"
            " QPushButton:hover { background: #f3f4f6; }"
        )
        # Grup yoksa Kaydet devre dışı — kullanıcı önce grup oluşturmalı.
        if not self._group_ids:
            self._btn_save.setEnabled(False)
            self._btn_save.setToolTip(
                "Önce en az bir kapı grubu oluşturun (uyarı kutusundaki adımlar)."
            )
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self._btn_save)
        root.addLayout(btn_row)

    # ── State ops ───────────────────────────────────────────────
    def _toggle_group(self, gid: int):
        self._states[gid] = 'locked' if self._states[gid] == 'open' else 'open'
        self._refresh_buttons()
        self._refresh_counter()

    def _open_all(self):
        for g in self._states:
            self._states[g] = 'open'
        self._refresh_buttons(); self._refresh_counter()

    def _lock_all(self):
        for g in self._states:
            self._states[g] = 'locked'
        self._refresh_buttons(); self._refresh_counter()

    def _invert(self):
        for g in self._states:
            self._states[g] = 'locked' if self._states[g] == 'open' else 'open'
        self._refresh_buttons(); self._refresh_counter()

    def _refresh_buttons(self):
        for gid, btn in self._buttons.items():
            info = self._groups.get(gid, {})
            name = info.get('name') or f"Grup #{gid}"
            n = len(info.get('door_indices') or [])
            state = self._states[gid]
            icon = '🟢' if state == 'open' else '🔴'
            btn.setText(f"{icon} {name}\n({n} kapı)")
            btn.setStyleSheet(
                _GROUP_QSS_OPEN if state == 'open' else _GROUP_QSS_LOCKED
            )

    def _refresh_counter(self):
        if not hasattr(self, 'counter_label'):
            return
        n_groups = len(self._states)
        open_n = sum(1 for s in self._states.values() if s == 'open')
        locked_n = n_groups - open_n
        total_doors = sum(
            len(self._groups[g]['door_indices']) for g in self._states
        )
        self.counter_label.setText(
            f"Önizleme: {open_n} açık grup · {locked_n} kilitli grup "
            f"(toplam {total_doors} kapı)"
        )

    # ── Save ────────────────────────────────────────────────────
    def _on_save(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Eksik Bilgi", "Konfig adı zorunludur.")
            return
        if not self._group_ids:
            QMessageBox.warning(
                self, "Grup Yok",
                "Önce en az bir kapı grubu oluşturun."
            )
            return
        if not self.get_selected_ports():
            QMessageBox.warning(
                self, "Port Seçilmedi",
                "En az bir port seçmelisiniz (RFID eşleştirilmiş portlar)."
            )
            return
        self.accept()

    # ── Public output ───────────────────────────────────────────
    def get_name(self) -> str:
        return self.name_edit.text().strip()

    def get_description(self) -> str:
        return self.desc_edit.text().strip()

    def get_door_states(self) -> Dict[str, str]:
        """Grup state'ini içindeki tüm kapılara yansıt.
        Return: {door_index_str: 'open'|'locked'} — sadece gruplu kapılar."""
        out: Dict[str, str] = {}
        for gid, state in self._states.items():
            members = self._groups.get(gid, {}).get('door_indices') or []
            for didx in members:
                out[str(int(didx))] = state
        return out

    def get_selected_ports(self) -> List[int]:
        """Seçili port indekslerini döndür (sadece checkbox'u işaretli olanlar)."""
        return sorted(
            pidx for pidx, cb in self._port_checks.items() if cb.isChecked()
        )

    def get_selected_stop_groups(self) -> Optional[List[int]]:
        """Seçili makine durdurma grubu id'leri. Dialog'da hiç durdurma
        grubu listelenmediyse None döner (= seçim yapılmadı → tümü aktif
        semantiği korunur)."""
        if not self._stop_checks:
            return None
        return sorted(
            gid for gid, cb in self._stop_checks.items() if cb.isChecked()
        )

    def get_wait_glt_pass(self) -> int:
        """1 = önce GLT batch'i tamamlansın (iki aşamalı akış)."""
        return 1 if self.wait_glt_chk.isChecked() else 0
