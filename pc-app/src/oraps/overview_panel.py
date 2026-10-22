"""Oraps Overview panel (Faz-4).

Top:    küçük cihaz görüntüleyici (sabit ön/arka/sol/sağ kameralar,
        Ayarlar → Oraps'tan açılıp kapatılır).
Bottom: yarı genişlik Aktif Batch + LAF Ünitesi kartları (sol kolon),
        Bağlı GLT Cihazları kartı (sağ kolon, GLT ana ekranındaki
        DeviceCard kopyaları — tıklayınca GLT ana sekmesine atlar).

Weidmüller bağlantı LED'i artık burada DEĞİL — ana pencere status bar'ında
(`MainWindow._refresh_wm_status` üzerinden).

Public API
----------
refresh_from_settings()   Reload GLB path/unit + enabled views from settings.
refresh_active_batch()    Re-apply current active batch door states to viewer.
refresh_laf_info()        Refresh LAF sensor values + active alarms card.
refresh_glt_devices()     Refresh connected GLT device cards (right column).

Sinyaller
---------
glt_card_clicked(str)     Bir GLT cihaz kartına tıklandığında cihaz adıyla
                          fırlatılır. MainWindow GLT ana sekmesine geçer.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QGroupBox, QSizePolicy, QScrollArea, QGridLayout,
    QPushButton, QDialog, QDialogButtonBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
    QLineEdit, QComboBox, QInputDialog, QFormLayout,
    QStackedWidget, QCheckBox,
)

from core.batch_manager import BatchManager, PermissionDenied, BatchInProgress
from core.laf_manager import LafManager
from gui.device_card import DeviceCard
from .viewer_3d import Viewer3D


class OrapsOverviewPanel(QWidget):
    """Sabit-kameralı 3D viewer + Aktif Batch / LAF / GLT cihaz kartları."""

    # Cihaz kartına tıklandığında MainWindow'a haber ver (cihaz adı ile)
    glt_card_clicked = pyqtSignal(str)

    def __init__(self, database, auth_manager, audit_manager,
                 pdf_generator=None, esp32_comm=None,
                 esp_now_control=None, parent=None):
        super().__init__(parent)
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        self.pdf_gen = pdf_generator
        self.esp32 = esp32_comm
        # GLT ana ekran filtresi: device_cards.keys() ile slave_devices'ı
        # filtrele — sadece HELLO/STREAM ile onaylanmış cihazlar gösterilir.
        # None ise filtre uygulanmaz (defansif fallback).
        self.esp_now_control = esp_now_control
        self.bm = BatchManager(database, auth_manager, audit_manager)
        self.laf = LafManager(database, auth_manager, audit_manager)
        self._last_loaded_glb: str | None = None
        # LAF ana ekran chip cache — 5sn'lik info_timer her tetikte chip'leri
        # silip yeniden inşa ediyordu → LAF kartı boyut titremesi → viewer
        # cascade resize. Şimdi chip'leri saklayıp sadece değer label'ını
        # güncelliyoruz; sensör listesi değişmedikçe layout'a dokunmuyor.
        self._laf_chips: dict[int, QFrame] = {}
        self._laf_chips_key: tuple | None = None
        self._laf_alarms_html: str | None = None
        self._laf_status_html: str | None = None
        # Son Olaylar kartı için cache (Faz 7) — aynı HTML ise setText çağrılmaz.
        self._events_html: str | None = None
        # LAF GLB overlay cache (Faz 5) — viewer'a sadece değişen değerleri
        # push etmek için. Three.js sahnesine dokunmuyoruz; render etkilenmez.
        self._last_overlay_key: tuple | None = None
        self._last_overlay_values: dict = {}

        # GLT cihaz kartlarını (DeviceCard) isimle indexliyoruz; reload'da
        # yeniden create etmek yerine update_status ile güncelliyoruz.
        self._glt_cards: dict[str, DeviceCard] = {}

        # RFID → port_index cache (esp_now_control rfid_state_changed sinyalinden
        # gelen RFID'leri hızlıca port'a eşlemek için). Port eşlemesi her
        # değiştiğinde _invalidate_rfid_cache ile sıfırlanır.
        self._rfid_to_port: dict[str, int] | None = None
        # device_name → en son aktif RFID (clear için)
        self._device_active_rfid: dict[str, str] = {}

        # IO bridge (WeidmullerBridge) — oraps_main tarafından
        # set_io_bridge() ile geçilir. None olduğu sürece sensör
        # üzerine renkleme yapılmaz.
        self._io_bridge = None
        # door_idx → 0/1 son bilinen DI sensör durumu (cache).
        self._door_sensor_states: dict[int, int] = {}
        # barrier_id → 0/1 son bilinen bariyer durumu (canlı cache; audit
        # tablosuna değil bridge.barrier_event_recorded sinyaline dayanır).
        # Başlangıçta boş → hiçbir bariyer aktif değil. 24V gelince (state=1)
        # bağlı kapılar turuncu boyanır; 0V dönünce temizlenir.
        self._barrier_states: dict[int, int] = {}
        # Acil stop durumu (bridge sinyalinden güncellenir).
        self._estop_active: bool = False
        # Kablosuz IR bariyer sensöründen gelen port motion cache'i (Faz-7).
        # E1 → set'e eklenir + 3D'de mavi; N sn (barrier_motion_hold_ms) sonra
        # ya da E0 gelince temizlenir.
        self._barrier_motion_ports: set[int] = set()

        # Aktif alarm banner (Faz-7 uzantısı): kritik bir olay ya da aktif LAF
        # alarm olduğunda üst şeritte görünür, yanıp söner. Operatör
        # "Tamam" ile session-lokal onaylar (audit'e ALARM_ACKED düşer,
        # tekrar tetiklenirse yine görünür). Ses YOK.
        self._ack_audit_ids: set[int] = set()   # onaylanmış audit_trail id'leri
        self._ack_laf_codes: set[str] = set()   # onaylanmış LAF alarm 'code' + sensor_id
        self._banner_key: tuple | None = None   # diff-check ile güncelleme
        self._banner_blink_state: bool = False

        self._build_ui()
        # Defer initial load until the QWebEngine page is ready.
        self.viewer.ready.connect(self._on_viewer_ready)
        self.viewer.model_loaded.connect(self._on_model_loaded)
        self.viewer.port_picked.connect(self._on_port_picked)
        self.viewer.door_picked.connect(self._on_door_picked)
        # Faz-5d: LAF chip drag-place → DB'ye pozisyon kaydet.
        try:
            self.viewer.laf_position_changed.connect(
                self._on_laf_position_changed
            )
        except Exception:
            pass
        # Faz-5: kapı/port 3D ad etiketi sürükleme → DB'ye ofset kaydet.
        try:
            self.viewer.door_position_changed.connect(self._on_door_position_changed)
            self.viewer.port_position_changed.connect(self._on_port_position_changed)
        except Exception:
            pass

        # Periodic refresh for the LAF + GLT cards (every 5s — cheap DB reads
        # and an in-memory list traversal). WM bağlantı LED'i status bar'da.
        self._info_timer = QTimer(self)
        self._info_timer.setInterval(5_000)
        self._info_timer.timeout.connect(self._refresh_info_cards)
        self._info_timer.start()
        QTimer.singleShot(500, self._refresh_info_cards)

        # Aktif batch süresi — 1 sn'de bir YALNIZCA özet etiketindeki süre
        # değerini günceller (viewer/chip'lere dokunmaz → titreme yok).
        # Şablon + başlangıç refresh_active_batch'te doldurulur.
        self._summary_template: str | None = None
        self._summary_started_at: str | None = None
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1_000)
        self._duration_timer.timeout.connect(self._tick_batch_duration)
        self._duration_timer.start()

    # ── UI ──────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(10)

        # ── Aktif alarm banner (üst şerit) ─────────────────
        # Kritik olay/LAF alarm olduğunda görünür; "Tamam" ile session-lokal
        # onaylanır. QTimer 600ms'de bir arka planını toggle eder (yanıp sönme).
        self.alarm_banner = QFrame()
        self.alarm_banner.setVisible(False)
        self.alarm_banner.setStyleSheet(
            "QFrame { background:#dc2626; border:2px solid #7f1d1d;"
            " border-radius:6px; }"
        )
        _ab = QHBoxLayout(self.alarm_banner)
        _ab.setContentsMargins(12, 6, 8, 6)
        _ab.setSpacing(10)
        self.alarm_banner_lbl = QLabel("")
        self.alarm_banner_lbl.setTextFormat(Qt.RichText)
        self.alarm_banner_lbl.setStyleSheet(
            "color:white;font-weight:700;font-size:14px;"
        )
        self.alarm_banner_lbl.setWordWrap(True)
        _ab.addWidget(self.alarm_banner_lbl, 1)
        self.alarm_banner_ack_btn = QPushButton("✓ Tamam")
        self.alarm_banner_ack_btn.setCursor(Qt.PointingHandCursor)
        self.alarm_banner_ack_btn.setStyleSheet(
            "QPushButton { background:white; color:#991b1b; border:none;"
            " border-radius:4px; padding:4px 12px; font-weight:700; font-size:12px; }"
            "QPushButton:hover { background:#f3f4f6; }"
        )
        self.alarm_banner_ack_btn.clicked.connect(self._on_alarm_ack)
        _ab.addWidget(self.alarm_banner_ack_btn)
        root.addWidget(self.alarm_banner)
        # Yanıp sönme timer'ı (600ms). Sadece banner görünürken çalışır.
        self._alarm_blink_timer = QTimer(self)
        self._alarm_blink_timer.setInterval(600)
        self._alarm_blink_timer.timeout.connect(self._toggle_alarm_blink)

        # Header: just the title (WM status moved to MainWindow status bar)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Cihaz Görünümü")
        title.setStyleSheet("color:#1f2937;font-weight:600;font-size:13px;")
        header.addWidget(title)
        header.addStretch()
        # RFID eşleme modu toggle butonu (admin onaylı açılır)
        self.pick_mode_btn = QPushButton("🏷 RFID Eşleme Modu")
        self.pick_mode_btn.setCheckable(True)
        self.pick_mode_btn.setCursor(Qt.PointingHandCursor)
        self.pick_mode_btn.setToolTip(
            "Açıkken 3D modeldeki bir glove port'a tıklayın; "
            "GLT'de kayıtlı RFID listesinden seçim yapın."
        )
        self.pick_mode_btn.setStyleSheet(
            "QPushButton { background:#eff6ff; color:#1d4ed8; "
            "border:1px solid #bfdbfe; border-radius:6px; "
            "padding:8px 16px; font-weight:600; font-size:13px; }"
            "QPushButton:hover { background:#dbeafe; }"
            "QPushButton:checked { background:#1d4ed8; color:white; "
            "border-color:#1d4ed8; }"
        )
        self.pick_mode_btn.toggled.connect(self._on_pick_mode_toggled)
        header.addWidget(self.pick_mode_btn)

        # Kapı eşleme modu toggle butonu (admin onaylı; pick_mode ile mutex)
        self.door_pick_btn = QPushButton("🚪 Kapı Eşleme Modu")
        self.door_pick_btn.setCheckable(True)
        self.door_pick_btn.setCursor(Qt.PointingHandCursor)
        self.door_pick_btn.setToolTip(
            "Açıkken 3D modeldeki bir kapıya tıklayın; "
            "kapı adı + grup atamasını düzenleyin."
        )
        self.door_pick_btn.setStyleSheet(
            "QPushButton { background:#fef3c7; color:#92400e; "
            "border:1px solid #fcd34d; border-radius:6px; "
            "padding:8px 16px; font-weight:600; font-size:13px; "
            "margin-left:6px; }"
            "QPushButton:hover { background:#fde68a; }"
            "QPushButton:checked { background:#92400e; color:white; "
            "border-color:#92400e; }"
        )
        self.door_pick_btn.toggled.connect(self._on_door_pick_mode_toggled)
        header.addWidget(self.door_pick_btn)

        # Bariyer Eşleme Modu (Faz-7) — port'a tıkla, elini sensörün önünden
        # geçir → otomatik eşleme. Admin/Supervisor açabilir; pick mode'larla
        # mutex.
        self.barrier_pair_btn = QPushButton("🔔 Bariyer Eşleme Modu")
        self.barrier_pair_btn.setCheckable(True)
        self.barrier_pair_btn.setCursor(Qt.PointingHandCursor)
        self.barrier_pair_btn.setToolTip(
            "Açıkken 3D modeldeki bir port'a tıklayın; ardından ilgili "
            "IR bariyer sensörünün önünden elinizi geçirin — sistem sensörü "
            "otomatik tanır ve port'a bağlar."
        )
        self.barrier_pair_btn.setStyleSheet(
            "QPushButton { background:#dbeafe; color:#1e40af; "
            "border:1px solid #93c5fd; border-radius:6px; "
            "padding:8px 16px; font-weight:600; font-size:13px; "
            "margin-left:6px; }"
            "QPushButton:hover { background:#bfdbfe; }"
            "QPushButton:checked { background:#1e40af; color:white; "
            "border-color:#1e40af; }"
        )
        self.barrier_pair_btn.toggled.connect(self._on_barrier_pair_mode_toggled)
        header.addWidget(self.barrier_pair_btn)

        # 🔄 Döndür — pick modu (RFID/Kapı) açıkken görünür; toggle ile
        # GLB serbest 360° döndürülebilir. Kapatılınca modelRoot rotasyonu
        # otomatik sıfırlanır (viewer.js setPickMode('') içinde).
        self.rotate_btn = QPushButton("🔄 Döndür")
        self.rotate_btn.setCheckable(True)
        self.rotate_btn.setCursor(Qt.PointingHandCursor)
        self.rotate_btn.setToolTip(
            "Açıkken 3D GLB'yi pointer ile sürükleyip döndürebilirsiniz. "
            "Kapalıyken tıklama = pick."
        )
        self.rotate_btn.setStyleSheet(
            "QPushButton { background:#ede9fe; color:#5b21b6; "
            "border:1px solid #c4b5fd; border-radius:6px; "
            "padding:8px 16px; font-weight:600; font-size:13px; "
            "margin-left:6px; }"
            "QPushButton:hover { background:#ddd6fe; }"
            "QPushButton:checked { background:#5b21b6; color:white; "
            "border-color:#5b21b6; }"
        )
        self.rotate_btn.toggled.connect(self._on_rotate_toggled)
        self.rotate_btn.setVisible(False)   # sadece pick modu açıkken göster
        header.addWidget(self.rotate_btn)

        # Yerleşim Modu (Faz-5d) — LAF chip'leri GLB üzerinde drag-place edilir.
        # Admin/Supervisor açabilir. Mutex: pick mode'lar ile çakışmaz.
        self.layout_mode_btn = QPushButton("📍 Yerleşim Modu")
        self.layout_mode_btn.setCheckable(True)
        self.layout_mode_btn.setCursor(Qt.PointingHandCursor)
        self.layout_mode_btn.setToolTip(
            "Açıkken GLB üzerindeki LAF sensör chip'lerini sürükleyip yerleştirebilirsiniz."
        )
        self.layout_mode_btn.setStyleSheet(
            "QPushButton { background:#dcfce7; color:#166534; "
            "border:1px solid #86efac; border-radius:6px; "
            "padding:8px 16px; font-weight:600; font-size:13px; "
            "margin-left:6px; }"
            "QPushButton:hover { background:#bbf7d0; }"
            "QPushButton:checked { background:#166534; color:white; "
            "border-color:#166534; }"
        )
        self.layout_mode_btn.toggled.connect(self._on_layout_mode_toggled)
        header.addWidget(self.layout_mode_btn)

        # Kapı/port ad etiketleri (Faz-5) — 3D sprite etiketleri aç/kapa.
        self.door_labels_btn = QPushButton("🏷 Ad Etiketleri")
        self.door_labels_btn.setCheckable(True)
        self.door_labels_btn.setChecked(True)
        self.door_labels_btn.setCursor(Qt.PointingHandCursor)
        self.door_labels_btn.setToolTip(
            "Kapı/port adlarını 3D modelde mesh'in üstünde göster/gizle.\n"
            "İsim vermek için ilgili eşleme modunda mesh'e tıklayın."
        )
        self.door_labels_btn.setStyleSheet(
            "QPushButton { background:#e0e7ff; color:#3730a3; "
            "border:1px solid #a5b4fc; border-radius:6px; "
            "padding:8px 16px; font-weight:600; font-size:13px; "
            "margin-left:6px; }"
            "QPushButton:hover { background:#c7d2fe; }"
            "QPushButton:checked { background:#3730a3; color:white; "
            "border-color:#3730a3; }"
        )
        self.door_labels_btn.toggled.connect(self._on_door_labels_toggled)
        header.addWidget(self.door_labels_btn)
        root.addLayout(header)

        # Viewer container — Faz-9: sabit 800px yükseklik. Kartlar arasında
        # bir şeyler değişirken viewer boyu titremesin diye setFixedHeight.
        # Kullanıcı büyük/küçük bulursa `_VIEWER_FIXED_HEIGHT` değeri değişir.
        self.viewer_frame = QFrame()
        self.viewer_frame.setStyleSheet(
            "QFrame { background:#111827; border:1px solid #1f2937; border-radius:10px; }"
        )
        self.viewer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.viewer_frame.setFixedHeight(500)
        viewer_layout = QVBoxLayout(self.viewer_frame)
        viewer_layout.setContentsMargins(2, 2, 2, 2)
        self.viewer = Viewer3D()
        self.viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        viewer_layout.addWidget(self.viewer)
        root.addWidget(self.viewer_frame, 0)

        # ── Info row: 50/50 split below the viewer ──
        #   Left column : Aktif Batch (top) + LAF Ünitesi (bottom)
        #   Right column: Bağlı GLT Cihazları
        info_row = QHBoxLayout()
        info_row.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        # Active batch card
        batch_group = QGroupBox("Aktif Batch")
        batch_group.setStyleSheet(self._card_qss())
        batch_layout = QVBoxLayout(batch_group)
        self.batch_summary = QLabel("Henüz aktif batch yok.")
        self.batch_summary.setStyleSheet("color:#374151;font-size:20px;")
        self.batch_summary.setWordWrap(True)
        self.batch_summary.setTextFormat(Qt.RichText)
        self.batch_summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        # Aktif Batch container aynı boyutta kalsın diye scroll area ile
        # sarmalıyoruz: font %50 büyüyünce içerik taşarsa dikey scroll
        # oluşur; kart boyutu (dolayısıyla altındaki buton satırının konumu)
        # değişmez. Yatay scroll bar kapalı; word-wrap devrede.
        self._batch_summary_scroll = QScrollArea()
        self._batch_summary_scroll.setWidget(self.batch_summary)
        self._batch_summary_scroll.setWidgetResizable(True)
        self._batch_summary_scroll.setFrameShape(QFrame.NoFrame)
        self._batch_summary_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self._batch_summary_scroll.setFixedHeight(150)
        self._batch_summary_scroll.setStyleSheet(
            "QScrollArea { background:transparent; border:none; }"
            " QScrollArea > QWidget > QWidget { background:transparent; }"
        )
        batch_layout.addWidget(self._batch_summary_scroll)

        # ── Hızlı batch kontrolü (Operator ana ekrandan başlat/bitir) ──
        # Aktif batch yokken: ad + konfig + başlat satırı görünür.
        self.batch_start_row = QWidget()
        start_layout = QHBoxLayout(self.batch_start_row)
        start_layout.setContentsMargins(0, 6, 0, 0)
        start_layout.setSpacing(6)
        self.quick_name_edit = QLineEdit()
        self.quick_name_edit.setPlaceholderText("Batch adı")
        self.quick_name_edit.setStyleSheet(
            "QLineEdit { border:1px solid #d1d5db; border-radius:6px;"
            " padding:12px 10px; background:#ffffff; font-size:15px; }"
        )
        start_layout.addWidget(self.quick_name_edit, 2)
        self.quick_config_combo = QComboBox()
        self.quick_config_combo.setStyleSheet(
            "QComboBox { border:1px solid #d1d5db; border-radius:6px;"
            " padding:12px 10px; background:#ffffff; font-size:15px;"
            " color:#1f2937; }"
            " QComboBox QAbstractItemView {"
            " background:#ffffff; color:#1f2937;"
            " selection-background-color:#2563eb;"
            " selection-color:#ffffff;"
            " outline:0; }"
        )
        start_layout.addWidget(self.quick_config_combo, 2)
        self.btn_quick_start = QPushButton("▶ Başlat")
        self.btn_quick_start.setCursor(Qt.PointingHandCursor)
        self.btn_quick_start.setStyleSheet(
            "QPushButton { background:#059669; color:white; border:none;"
            " padding:12px 24px; border-radius:8px; font-weight:700; font-size:15px; }"
            " QPushButton:hover { background:#047857; }"
        )
        self.btn_quick_start.clicked.connect(self._on_quick_start)
        start_layout.addWidget(self.btn_quick_start)
        # Stack içinde saklandığı için batch_layout'a doğrudan eklenmiyor.

        # Aktif batch varken: pause/resume/finish satırı görünür.
        self.batch_active_row = QWidget()
        active_layout = QHBoxLayout(self.batch_active_row)
        active_layout.setContentsMargins(0, 6, 0, 0)
        active_layout.setSpacing(8)
        # Rapor butonuyla aynı boyut (padding:10px 20px, font:14px bold, radius:7px)
        _pause_qss = (
            "QPushButton { padding:10px 20px; border:1px solid #d1d5db;"
            " background:#ffffff; border-radius:7px; font-weight:700; font-size:14px; }"
            " QPushButton:hover { background:#f3f4f6; }"
        )
        self.btn_quick_pause = QPushButton("⏸ Duraklat")
        self.btn_quick_pause.setCursor(Qt.PointingHandCursor)
        self.btn_quick_pause.setStyleSheet(_pause_qss)
        self.btn_quick_pause.clicked.connect(self._on_quick_pause)
        self.btn_quick_resume = QPushButton("▶ Devam")
        self.btn_quick_resume.setCursor(Qt.PointingHandCursor)
        self.btn_quick_resume.setStyleSheet(
            "QPushButton { background:#059669; color:white; border:none;"
            " padding:10px 20px; border-radius:7px; font-weight:700; font-size:14px; }"
            " QPushButton:hover { background:#047857; }"
        )
        self.btn_quick_resume.clicked.connect(self._on_quick_resume)
        self.btn_quick_finish = QPushButton("⏹ Bitir")
        self.btn_quick_finish.setCursor(Qt.PointingHandCursor)
        self.btn_quick_finish.setStyleSheet(
            "QPushButton { background:#dc2626; color:white; border:none;"
            " padding:10px 20px; border-radius:7px; font-weight:700; font-size:14px; }"
            " QPushButton:hover { background:#b91c1c; }"
        )
        self.btn_quick_finish.clicked.connect(self._on_quick_finish)
        # Kilit Aç — sadece paused durumda görünür.
        self.btn_quick_unlock = QPushButton("🔓 Kilit Aç")
        self.btn_quick_unlock.setCursor(Qt.PointingHandCursor)
        self.btn_quick_unlock.setToolTip(
            "Batch duraklatılmışken seçtiğiniz kapı grubunun kilidini açar.\n"
            "Açıklama girmeniz zorunludur (audit trail'e kaydedilir)."
        )
        self.btn_quick_unlock.setStyleSheet(
            "QPushButton { background:#f59e0b; color:white; border:none;"
            " padding:10px 20px; border-radius:7px; font-weight:700; font-size:14px; }"
            " QPushButton:hover { background:#d97706; }"
        )
        self.btn_quick_unlock.clicked.connect(self._on_quick_unlock)
        # Kilitle — sadece paused durumda görünür.
        self.btn_quick_lock = QPushButton("🔒 Kilitle")
        self.btn_quick_lock.setCursor(Qt.PointingHandCursor)
        self.btn_quick_lock.setToolTip(
            "Batch duraklatılmışken seçtiğiniz kapı grubunu tekrar kilitler.\n"
            "Açıklama girmeniz zorunludur (audit trail'e kaydedilir)."
        )
        self.btn_quick_lock.setStyleSheet(
            "QPushButton { background:#7c3aed; color:white; border:none;"
            " padding:10px 20px; border-radius:7px; font-weight:700; font-size:14px; }"
            " QPushButton:hover { background:#6d28d9; }"
        )
        self.btn_quick_lock.clicked.connect(self._on_quick_lock)
        # Faz-12: GLT aşamasından ORABS aşamasına geçiş — yalnız
        # phase='glt' iken görünür; tüm portlar test edilince aktifleşir.
        self.btn_quick_advance = QPushButton("▶ ORABS'a Geç")
        self.btn_quick_advance.setCursor(Qt.PointingHandCursor)
        self.btn_quick_advance.setStyleSheet(
            "QPushButton { background:#4f46e5; color:white; border:none;"
            " padding:10px 20px; border-radius:7px; font-weight:700; font-size:14px; }"
            " QPushButton:hover { background:#4338ca; }"
            " QPushButton:disabled { background:#a5b4fc; }"
        )
        self.btn_quick_advance.clicked.connect(self._on_advance_phase)
        active_layout.addWidget(self.btn_quick_advance)
        active_layout.addWidget(self.btn_quick_pause)
        active_layout.addWidget(self.btn_quick_resume)
        active_layout.addWidget(self.btn_quick_unlock)
        active_layout.addWidget(self.btn_quick_lock)
        active_layout.addWidget(self.btn_quick_finish)
        active_layout.addStretch(1)
        # Stack içinde saklandığı için batch_layout'a doğrudan eklenmiyor.

        # QStackedWidget — start_row ve active_row tek bir sabit yükseklikli
        # alanda yer alır. setCurrentIndex() ile sayfalar değişir; kart
        # boyutu değişmediği için viewer'a cascade resize gönderilmez.
        self.batch_quick_stack = QStackedWidget()
        self.batch_quick_stack.addWidget(self.batch_start_row)   # index 0
        self.batch_quick_stack.addWidget(self.batch_active_row)  # index 1
        # Stack yüksekliği en büyük sayfaya göre sabit — boyut titremesi yok.
        self.batch_quick_stack.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Fixed
        )
        batch_layout.addWidget(self.batch_quick_stack)

        # Rapor butonları — kompakt, sağa yaslı ayrı satır.
        # Sol: "Raporları Görüntüle" (arşiv), sağ: "Rapor" (aktif batch raporu).
        report_row = QHBoxLayout()
        report_row.setContentsMargins(0, 4, 0, 0)
        report_row.addStretch(1)

        self.btn_reports_browser = QPushButton("📚 Raporları Görüntüle")
        self.btn_reports_browser.setCursor(Qt.PointingHandCursor)
        self.btn_reports_browser.setToolTip(
            "GLT test raporları ve batch raporlarını uygulama içinde görüntüle."
        )
        self.btn_reports_browser.setStyleSheet(
            "QPushButton { background:#f3f4f6; color:#1f2937;"
            " border:1px solid #d1d5db;"
            " padding:10px 18px; border-radius:7px; font-weight:700; font-size:14px; }"
            " QPushButton:hover { background:#e5e7eb; }"
        )
        self.btn_reports_browser.clicked.connect(self._on_open_reports_browser)
        report_row.addWidget(self.btn_reports_browser)

        self.btn_quick_summary = QPushButton("📋 Özet Rapor")
        self.btn_quick_summary.setCursor(Qt.PointingHandCursor)
        self.btn_quick_summary.setToolTip(
            "Kompakt rapor: yalnızca alarmlar ve port test sonuçları."
        )
        self.btn_quick_summary.setStyleSheet(
            "QPushButton { background:#eff6ff; color:#1d4ed8;"
            " border:1px solid #bfdbfe;"
            " padding:10px 18px; border-radius:7px; font-weight:700; font-size:14px; }"
            " QPushButton:hover { background:#dbeafe; }"
        )
        self.btn_quick_summary.clicked.connect(self._on_quick_report_compact)
        report_row.addWidget(self.btn_quick_summary)

        self.btn_quick_report = QPushButton("📄 Rapor")
        self.btn_quick_report.setCursor(Qt.PointingHandCursor)
        self.btn_quick_report.setStyleSheet(
            "QPushButton { background:#2563eb; color:white; border:none;"
            " padding:10px 20px; border-radius:7px; font-weight:700; font-size:14px; }"
            " QPushButton:hover { background:#1d4ed8; }"
        )
        self.btn_quick_report.clicked.connect(self._on_quick_report)
        report_row.addWidget(self.btn_quick_report)
        batch_layout.addLayout(report_row)

        # Faz-9: Aktif Batch tek başına sol kolonda — dikeyde içeriği kadar
        # yer kaplar; kalan boşluk stretch'e gider. Böylece LAF kartı
        # gizlendiğinde batch kartı gereksiz büyümez.
        left_col.addWidget(batch_group, 0)
        left_col.addStretch(1)

        # ── LAF Ünitesi kartı (Faz-9: orta kolonda aşağıda yaratılıyor). ──
        # Sol kolondan kaldırıldı. Sadece widget'ın oluşturulduğu blok
        # aşağıda middle_col altnda; sonrası kod bu widget'ı kullanır.

        left_wrap = QWidget()
        left_wrap.setLayout(left_col)
        info_row.addWidget(left_wrap, 2)

        # ── Middle column: Son Olaylar (Faz-9) ─────────────────────
        # Batch/LAF container ile GLT container arasına yerleştirildi.
        middle_col = QVBoxLayout()
        middle_col.setSpacing(12)
        events_group = QGroupBox("Son Olaylar")
        events_group.setStyleSheet(self._card_qss())
        events_layout = QVBoxLayout(events_group)
        events_layout.setSpacing(4)
        events_layout.setContentsMargins(10, 8, 10, 8)
        self.events_lbl = QLabel(
            "<span style='color:#9ca3af;font-size:16px;'>Henüz olay yok.</span>"
        )
        self.events_lbl.setStyleSheet("font-size:16px;")
        self.events_lbl.setWordWrap(True)
        self.events_lbl.setTextFormat(Qt.RichText)
        self.events_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        # Son Olaylar karttını yukarı doğru itmesin diye label'ı scroll
        # area içine sarıyoruz. Karta ayrılan alan içerikten küçükse
        # dikey scroll bar çıkar; yatay scroll kapalı.
        self._events_scroll = QScrollArea()
        self._events_scroll.setWidget(self.events_lbl)
        self._events_scroll.setWidgetResizable(True)
        self._events_scroll.setFrameShape(QFrame.NoFrame)
        self._events_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._events_scroll.setStyleSheet(
            "QScrollArea { background:transparent; border:none; }"
            " QScrollArea > QWidget > QWidget { background:transparent; }"
        )
        events_layout.addWidget(self._events_scroll, 1)
        middle_col.addWidget(events_group, 1)

        # ── LAF Ünitesi (Faz-9: orta kolon, Son Olayların altında) ──
        # Ayarlar → ORABS → `LAF kartını göster` toggle'ı
        # (`overview_show_laf`) refresh_from_settings içinde uygulanır.
        self.laf_group = QGroupBox("LAF Ünitesi")
        self.laf_group.setStyleSheet(self._card_qss())
        self.laf_group.setMaximumHeight(110)
        laf_layout = QVBoxLayout(self.laf_group)
        laf_layout.setSpacing(4)
        laf_layout.setContentsMargins(10, 8, 10, 8)

        self.laf_status_lbl = QLabel("LAF verileri yükleniyor…")
        self.laf_status_lbl.setStyleSheet("color:#6b7280;font-size:11px;")
        self.laf_status_lbl.setTextFormat(Qt.RichText)
        laf_layout.addWidget(self.laf_status_lbl)

        # Sensor values grid gizli — GLB overlay'de görünür (geriye uyum).
        self.laf_values_frame = QFrame()
        self.laf_values_frame.setStyleSheet("QFrame{background:transparent;}")
        self.laf_values_frame.setVisible(False)
        self.laf_values_layout = QGridLayout(self.laf_values_frame)
        self.laf_values_layout.setContentsMargins(0, 0, 0, 0)
        laf_layout.addWidget(self.laf_values_frame)

        self.laf_alarms_lbl = QLabel("")
        self.laf_alarms_lbl.setStyleSheet("color:#374151;font-size:11px;")
        self.laf_alarms_lbl.setWordWrap(True)
        self.laf_alarms_lbl.setTextFormat(Qt.RichText)
        laf_layout.addWidget(self.laf_alarms_lbl)

        middle_col.addWidget(self.laf_group, 0)

        middle_wrap = QWidget()
        middle_wrap.setLayout(middle_col)
        info_row.addWidget(middle_wrap, 1)

        # ── Right column: GLT devices (Faz-9: dar, sağa yaslı) ─────
        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        glt_group = QGroupBox("Bağlı GLT Cihazları")
        glt_group.setStyleSheet(self._card_qss())
        glt_layout = QVBoxLayout(glt_group)
        glt_layout.setSpacing(6)

        # Cihaz özet metni (gizli; refresh_glt_devices yine setText çağırıyor).
        self.glt_summary = QLabel("")
        self.glt_summary.setStyleSheet("color:#6b7280;font-size:12px;")
        self.glt_summary.setTextFormat(Qt.RichText)
        self.glt_summary.setVisible(False)
        glt_layout.addWidget(self.glt_summary)

        # Scrollable card grid
        self.glt_scroll = QScrollArea()
        self.glt_scroll.setWidgetResizable(True)
        self.glt_scroll.setFrameShape(QFrame.NoFrame)
        self.glt_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.glt_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.glt_scroll.setStyleSheet(
            "QScrollArea { background:transparent; border:none; }"
            " QScrollArea > QWidget > QWidget { background:transparent; }"
        )
        self.glt_grid_wrap = QWidget()
        self.glt_grid_layout = QGridLayout(self.glt_grid_wrap)
        self.glt_grid_layout.setContentsMargins(0, 6, 0, 6)
        self.glt_grid_layout.setHorizontalSpacing(10)
        self.glt_grid_layout.setVerticalSpacing(10)
        self.glt_grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.glt_scroll.setWidget(self.glt_grid_wrap)
        glt_layout.addWidget(self.glt_scroll, 1)
        right_col.addWidget(glt_group, 1)

        right_wrap = QWidget()
        right_wrap.setLayout(right_col)
        right_wrap.setFixedWidth(320)
        info_row.addWidget(right_wrap, 0)

        # stretch=2 → info kartları toplam dikey alanın ~%40'ını kaplar
        root.addLayout(info_row, 2)

    @staticmethod
    def _card_qss() -> str:
        return (
            "QGroupBox { background:#ffffff; border:1px solid #e5e7eb;"
            " border-radius:10px; margin-top:10px; padding:10px;"
            " font-weight:600; color:#1f2937; font-size:13px; }"
            " QGroupBox::title { subcontrol-origin: margin; left:12px; padding:0 6px; }"
        )

    def resizeEvent(self, event):
        """Faz-9: viewer sabit 800px (setFixedHeight). Pencere boyutu
        değişse de içerik değişse de viewer boyu titremesin. Dinamik
        tavan hesabı kaldırıldı."""
        super().resizeEvent(event)

    # ── Refresh API ─────────────────────────────────────────────
    _ALLOWED_VIEWS = ('front', 'back', 'left', 'right')

    def set_io_bridge(self, bridge):
        """oraps_main → WeidmullerBridge örneğini bağla. Bridge
        door_sensor_changed sinyali burada dinlenir, cache güncellenir
        ve viewer yeniden boyanır."""
        self._io_bridge = bridge
        if bridge is None:
            return
        try:
            bridge.door_sensor_changed.connect(self._on_door_sensor_changed)
        except Exception:
            pass
        try:
            bridge.barrier_event_recorded.connect(self._on_barrier_event)
        except Exception:
            pass
        try:
            bridge.estop_triggered.connect(self._on_estop_triggered)
        except Exception:
            pass
        # Bridge'in mevcut cache'i varsa şimdi al (ör. uygulama açıldıktan
        # sonra bağlanıyorsa bazı DI edge'ler zaten geçmiş olabilir).
        try:
            initial = bridge.get_door_sensor_states() or {}
            for k, v in initial.items():
                self._door_sensor_states[int(k)] = int(v)
            if initial:
                self.refresh_active_batch()
        except Exception:
            pass

    def _on_door_sensor_changed(self, door_idx: int, state: int):
        """Bridge'den DI edge geldi → cache güncelle, viewer'ı tazele."""
        self._door_sensor_states[int(door_idx)] = int(state)
        self.refresh_active_batch()

    def _on_barrier_event(self, barrier_id: int, state: int, ts: str):
        """Bridge'den bariyer edge geldi (barrier_event_recorded) → cache
        güncelle, viewer'da bağlı kapıları turuncu boya (state=1) veya
        temizle (state=0). Kanlı sinyal → audit tablosuna değil in-memory
        cache'e bakıyoruz: başlangıçta hiç event yoksa hiçbir bariyer aktif
        değildir (kullanıcı istediği davranış: yalnızca gerçek 24V geldiğinde
        turuncu)."""
        self._barrier_states[int(barrier_id)] = int(state)
        self.refresh_active_batch()

    # ── Acil stop ────────────────────────────────────────────────
    def _on_estop_triggered(self, state: int, ts: str):
        """Bridge'den acil stop sinyali. state=1 → basıldı, state=0 → serbest."""
        self._estop_active = bool(state)
        if state:
            self._start_estop_beep()
        else:
            self._stop_estop_beep()
        # Banner ve batch durumunu yenile.
        self.refresh_active_batch()
        self.refresh_events()

    def _start_estop_beep(self):
        """PC hoparlöründen tekrarlayan alarm sesi başlat (500ms aralık)."""
        if hasattr(self, '_estop_beep_timer') and self._estop_beep_timer.isActive():
            return  # zaten çalıyor
        self._estop_beep_timer = QTimer(self)
        self._estop_beep_timer.setInterval(600)
        self._estop_beep_timer.timeout.connect(self._play_estop_beep)
        self._estop_beep_timer.start()
        self._play_estop_beep()  # ilk beep hemen

    def _stop_estop_beep(self):
        """PC alarm sesini durdur."""
        if hasattr(self, '_estop_beep_timer'):
            self._estop_beep_timer.stop()
        # Çalmakta olan async bip'i de kes.
        try:
            import sys
            if sys.platform.startswith('win'):
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def _play_estop_beep(self):
        """Tek bir alarm bip'i çal.

        Eski `winsound.Beep` sistem bip'i düşük genlikliydi (kullanıcı
        2026-08-03: 'ses çok az geliyor'). Şimdi bellekte üretilen TAM
        GENLİKLİ kare dalga WAV, `PlaySound(SND_MEMORY|SND_ASYNC)` ile
        çalınıyor — aynı 2 kHz ton, belirgin şekilde daha gür. (Nihai
        seviye yine Windows ses ayarına tabidir.)"""
        try:
            import sys
            if not sys.platform.startswith('win'):
                return
            import winsound
            if getattr(self, '_estop_wav', None) is None:
                self._estop_wav = self._build_alarm_wav()
            # SND_MEMORY: buffer canlı kalmalı → self üzerinde saklanıyor.
            winsound.PlaySound(self._estop_wav,
                               winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            pass

    @staticmethod
    def _build_alarm_wav(freq: int = 2000, ms: int = 450,
                         rate: int = 44100, amp: int = 30000) -> bytes:
        """Bellekte 16-bit mono WAV üret — tam genlik kare dalga (gür alarm).
        Kısa fade-in/out ile başlangıç/bitiş 'tık' sesi önlenir."""
        import io
        import struct
        import wave
        n = int(rate * ms / 1000)
        period = rate / float(freq)
        frames = bytearray()
        for i in range(n):
            v = amp if (i % period) < (period / 2.0) else -amp
            edge = min(i, n - i)
            if edge < 200:                      # ~4.5 ms rampa
                v = int(v * edge / 200.0)
            frames += struct.pack('<h', v)
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
        return buf.getvalue()

    # ── Kablosuz bariyer sensör motion (Faz-7) ───────────────────
    def on_barrier_port_motion(self, port_index: int, is_broken: bool):
        """BarrierManager'dan gelen port motion olayı. `is_broken=True` →
        3D'de mavi 'motion' boyaması + `_barrier_motion_ports` cache;
        `barrier_motion_hold_ms` sonrası otomatik temizlenir. `is_broken=False`
        → hemen temizlenir.

        Not: `bm.log_port_motion_event` zaten BarrierManager tarafından
        çağrılıyor (audit + is_occupied). Bu slot sadece 3D viewer'daki
        mavi kısa-hold gösterimini yönetir.
        """
        try:
            pidx = int(port_index)
        except (TypeError, ValueError):
            return
        if is_broken:
            self._barrier_motion_ports.add(pidx)
            try:
                self.viewer.apply_port_states({str(pidx): 'motion'})
            except Exception:
                pass
            # Otomatik expire (varsayılan 5 sn)
            try:
                hold_ms = int(
                    self.db.get_setting('barrier_motion_hold_ms', '5000') or '5000'
                )
            except Exception:
                hold_ms = 5000
            QTimer.singleShot(max(500, hold_ms),
                              lambda p=pidx: self._expire_barrier_motion(p))
        else:
            self._expire_barrier_motion(pidx)

    def _expire_barrier_motion(self, port_index: int):
        """Bariyer motion cache'inden port çıkar, viewer'da nötr rengine dön."""
        self._barrier_motion_ports.discard(int(port_index))
        # Occupancy/batch state'ini restore etmek için port chip refresh:
        try:
            self._push_port_chips()
        except Exception:
            pass

    def refresh_from_settings(self):
        """Reload GLB path/unit + enabled views from settings."""
        glb_path = self.db.get_setting('oraps_glb_path', '')

        raw = self.db.get_setting('oraps_overview_views', 'front,back,left,right') or ''
        views = [v.strip().lower() for v in raw.split(',') if v.strip()]
        views = [v for v in views if v in self._ALLOWED_VIEWS]
        if not views:
            views = list(self._ALLOWED_VIEWS)

        # Faz-9: Viewer artık `_build_ui`'de sabit yüksekliğe (setFixedHeight)
        # bağlanıyor. Görünüm sayısına göre dinamik yükseklik ayarı KALDIRILDI
        # — aksi halde setMinimumHeight çağrısı setFixedHeight'ı ezip
        # viewer'ı küçültüyordu.

        # Faz-9: LAF kartının görünürlüğü — Ayarlar → ORABS → `LAF kartını
        # göster` toggle'ı (`overview_show_laf`) burada uygulanır.
        try:
            show_laf = str(self.db.get_setting(
                'overview_show_laf', '1'
            )).strip() not in ('0', 'false', 'False')
            if hasattr(self, 'laf_group'):
                self.laf_group.setVisible(show_laf)
        except Exception:
            pass

        self.viewer.set_enabled_views(views)
        # Only reload the GLB when the path actually changed. Reloading on
        # every settings-save tears down + recreates WebGL state and has
        # crashed the QtWebEngine GPU process on some systems.
        if glb_path != self._last_loaded_glb:
            self.viewer.load_model(glb_path)
            self._last_loaded_glb = glb_path

    def refresh_active_batch(self):
        """Re-read active batch and push door states to the viewer."""
        # Defansif: her refresh'te bridge'in canlı DI cache'inden sensör
        # durumlarını çek. Böylece signal timing / seed sırası ne olursa
        # olsun (uygulama açılışında zaten açık olan kapılar dahil) viewer
        # her zaman güncel görünür.
        try:
            if getattr(self, '_io_bridge', None) is not None:
                latest = self._io_bridge.get_door_sensor_states() or {}
                for k, v in latest.items():
                    self._door_sensor_states[int(k)] = int(v)
        except Exception:
            pass
        ab = self.bm.get_active_batch()
        active = bool(ab and ab.get('status') in ('running', 'paused')
                      and ab.get('batch_name'))
        # Yalnızca IO'ya (DO kilit çıkışına) bağlı kapılar 3D'de
        # state rengi alır. IO'ya bağlı olmayan kapılar nötr kalır.
        # IO bağlantısı: doğrudan link_type='door' VEYA link_type='door_group'
        # üzerinden gruba bağlı. Gruba dahil olmayan ama DO'ya doğrudan
        # bağlı iç kapaklar da renklendirilir (isimli olsun olmasın).
        try:
            named_indices = {
                int(d['door_index']) for d in self.bm.get_door_labels()
                if (d.get('label') or '').strip()
            }
        except Exception:
            named_indices = set()
        # IO'ya bağlı kapı indeksleri: doğrudan DO bağlı + grup DO bağlı
        # olan grupların üyeleri.
        io_linked_indices: set = set()
        try:
            bridge = getattr(self, '_io_bridge', None)
            if bridge is not None:
                doors_do, groups_do = bridge.get_lock_output_targets()
                io_linked_indices.update(int(d) for d in doors_do)
                # Grup DO'ya bağlıysa gruptaki tüm kapıları dahil et.
                if groups_do:
                    all_labels = self.bm.get_door_labels() or []
                    for lbl_row in all_labels:
                        gid = lbl_row.get('group_id')
                        didx = lbl_row.get('door_index')
                        if gid is not None and didx is not None:
                            try:
                                if int(gid) in groups_do:
                                    io_linked_indices.add(int(didx))
                            except (TypeError, ValueError):
                                pass
        except Exception:
            pass
        # Renklendirme filtresi: IO'ya bağlı olanlar (isimli olsun olmasın).
        # IO bridge yoksa fallback: sadece isimli kapılar.
        colorable_indices = io_linked_indices if io_linked_indices else named_indices

        if not active:
            self.batch_summary.setText(
                "<span style='color:#6b7280;'>Henüz aktif batch yok.</span>"
            )
            # Süre ticker'ını durdur (batch yok).
            self._summary_template = None
            self._summary_started_at = None
        # Batch açık veya kapalı olsun DI sensör durumu üzerine sarı işaretleme
        # her zaman gösterilsin (kullanıcı fiziksel kapı açıkken her zaman görmeli).
        states: dict[str, str] = {}
        if active:
            raw = ab.get('door_states', {}) or {}
            _phase = (ab.get('phase') or 'orabs')
            # Faz-12: GLT aşamasında kilitler UYGULANMAZ — tüm kapılar açık
            # gösterilir (fiziksel durum da böyle: bridge kilit yazmaz).
            if _phase == 'glt':
                raw = {k: 'open' for k in raw}
            # Grup genişletme: config'te bir grubun herhangi bir üyesi
            # 'locked' ise, aynı gruptaki TÜM kapılar da 'locked' olmalı.
            # Bu, eski config'lerin (isimsiz kapı eksik) görsel uyumunu sağlar
            # ve IO DO kanalı grup bazlı çalıştığı için fiziksel durumla
            # viewer'ı senkron tutar.
            try:
                _all_labels = self.bm.get_door_labels() or []
                # group_id → [door_index, ...]
                _grp_members: dict = {}
                for _row in _all_labels:
                    _gid = _row.get('group_id')
                    _didx = _row.get('door_index')
                    if _gid is not None and _didx is not None:
                        _grp_members.setdefault(int(_gid), []).append(int(_didx))
                # Her grup için: üyelerden biri raw'da 'locked' ise tümünü 'locked' yap
                for _gid, _members in _grp_members.items():
                    group_state = None
                    for _m in _members:
                        st = raw.get(str(_m))
                        if st == 'locked':
                            group_state = 'locked'
                            break
                    if group_state is None:
                        # Hiçbiri 'locked' değilse, herhangi biri 'open' mi?
                        for _m in _members:
                            st = raw.get(str(_m))
                            if st == 'open':
                                group_state = 'open'
                                break
                    if group_state:
                        for _m in _members:
                            raw[str(_m)] = group_state
            except Exception:
                pass
            # Sadece IO'ya bağlı kapıların state'ini al.
            for k, v in raw.items():
                try:
                    if int(k) in colorable_indices:
                        states[str(k)] = v
                except (TypeError, ValueError):
                    pass
            open_n = sum(1 for s in states.values() if s == 'open')
            locked_n = len(states) - open_n
            cfg_name = ab.get('config_name') or '(silinmiş konfig)'
            status_label = {
                'running':  '<span style="color:#059669;font-weight:600;">🟢 ÇALIŞIYOR</span>',
                'paused':   '<span style="color:#d97706;font-weight:600;">⏸ Duraklatıldı</span>',
            }.get(ab.get('status', ''), ab.get('status', '-'))
            # Bağlı GLT batch varsa port test sayacını göster: toplam, geçti,
            # başarısız, bekleyen. `_batch_member_port_status()` → dict[idx: st].
            _bstatus = self._batch_member_port_status()
            n_total = len(_bstatus)
            n_pass  = sum(1 for s in _bstatus.values() if s == 'PASS')
            n_fail  = sum(1 for s in _bstatus.values() if s == 'FAIL')
            n_pend  = n_total - n_pass - n_fail
            if n_total:
                port_line = (
                    f"<br>Port: <b>{n_total}</b> toplam · "
                    f"<span style='color:#059669;font-weight:600;'>✓ {n_pass} geçti</span> · "
                    f"<span style='color:#b91c1c;font-weight:600;'>✗ {n_fail} başarısız</span> · "
                    f"<span style='color:#7c3aed;font-weight:600;'>⏳ {n_pend} bekliyor</span>"
                )
            else:
                port_line = ''
            # Faz-12: GLT aşaması göstergesi — kalan port (süre artık her
            # batch'te ayrı satırda canlı gösteriliyor).
            phase_line = ''
            if _phase == 'glt':
                _remain = n_pend if n_total else 0
                phase_line = (
                    "<br><span style='color:#4f46e5;font-weight:700;'>"
                    "🧪 GLT AŞAMASI</span> — "
                    f"kalan: <b>{_remain}</b> port"
                    " · kapılar açık, makine durdurma aktif"
                )
            # Canlı süre satırı: şablonda %%SURE%% → 1 sn'lik ticker doldurur.
            _tpl = (
                f"<b>{ab.get('batch_name')}</b><br>"
                f"Konfig: {cfg_name}<br>"
                f"Durum: {status_label} · ⏱ Süre: <b>%%SURE%%</b>"
                f"{phase_line}<br>"
                f"Kapı: {open_n} açık · {locked_n} kilitli"
                f"{port_line}"
            )
            self._summary_template = _tpl
            self._summary_started_at = ab.get('started_at')
            self.batch_summary.setText(
                _tpl.replace('%%SURE%%', self._format_batch_elapsed())
            )
        # DI sensör = 1 olan kapıları sarı (sensor_open) — yalnızca IO'ya
        # bağlı + isimli kapılar için.
        for door_idx, val in self._door_sensor_states.items():
            if int(val) == 1 and int(door_idx) in colorable_indices:
                states[str(door_idx)] = 'sensor_open'
        # Aktif ışık bariyerleri: bağlı tüm kapıları turuncu (barrier) boya.
        # Bariyer emniyet-kritik → isim filtresi UYGULANMAZ; adsız kapıya
        # bağlı bariyer tetiklenirse de uyarı görünür.
        for door_idx in self._active_barrier_door_set():
            states[str(door_idx)] = 'barrier'
        # Her zaman apply_door_states çağır — JS tarafı statesObj'de
        # bulunmayan kapıları otomatik olarak neutral'e (gri) döndürür.
        self.viewer.apply_door_states(states)
        # Kapı bilgi chip'lerini de güncelle (durum değişikliği anında yansısın).
        self._push_door_chips()

        # ── Hızlı batch kontrol satırlarının görünürlüğü ──
        status = (ab.get('status', '') if ab else '') or ''
        running = active and status == 'running'
        paused = active and status == 'paused'
        if hasattr(self, 'batch_quick_stack'):
            # Stack sayfasını değiştir (boyut sabit, viewer'a cascade yok).
            self.batch_quick_stack.setCurrentIndex(1 if active else 0)
            # Aktif sayfa içindeki butonların görünürlüğü — aynı satırın
            # içinde değiştikleri için stack yüksekliğini etkilemezler.
            self.btn_quick_pause.setVisible(running)
            self.btn_quick_resume.setVisible(paused)
            self.btn_quick_unlock.setVisible(paused)
            self.btn_quick_lock.setVisible(paused)
            self.btn_quick_finish.setVisible(active)
            # Faz-12: ORABS'a Geç — yalnız GLT aşamasında görünür;
            # bekleyen (PENDING) port kalmayınca aktifleşir.
            _phase_now = (ab.get('phase') or 'orabs') if ab else 'orabs'
            _is_glt = active and _phase_now == 'glt'
            self.btn_quick_advance.setVisible(_is_glt)
            if _is_glt:
                _bs = self._batch_member_port_status()
                _pend = sum(1 for s in _bs.values() if s == 'PENDING')
                _ready = len(_bs) > 0 and _pend == 0
                self.btn_quick_advance.setEnabled(_ready)
                self.btn_quick_advance.setToolTip(
                    "Tüm portlar test edildi — ORABS aşamasına geçebilirsiniz."
                    if _ready else
                    f"Bekleyen {_pend} port var. Tüm portlar test edilmeden "
                    "ORABS aşamasına geçilemez."
                )
            # Konfig combo'yu sadece batch yokken (start_row görünürken) doldur.
            if not active:
                self._refresh_quick_config_combo()

    def _format_batch_elapsed(self) -> str:
        """started_at → 'HH:MM:SS' geçen süre (hata/eksikte '—')."""
        try:
            from datetime import datetime as _dt
            t0 = _dt.fromisoformat(self._summary_started_at)
            sec = max(0, int((_dt.now() - t0).total_seconds()))
            return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"
        except Exception:
            return '—'

    def _tick_batch_duration(self):
        """1 sn'lik ticker — yalnız batch özeti etiketindeki süreyi yeniler.
        Viewer/chip/DB'ye dokunmaz; şablon yoksa (aktif batch yok) no-op.
        Metin uzunluğu sabit olduğu için kart yüksekliği değişmez
        (cascade resize / viewer titremesi yok)."""
        if not self._summary_template or not self._summary_started_at:
            return
        try:
            self.batch_summary.setText(
                self._summary_template.replace(
                    '%%SURE%%', self._format_batch_elapsed())
            )
        except Exception:
            pass

    def _refresh_quick_config_combo(self):
        """Hızlı kontrol satırındaki konfig dropdown'ını mevcut aktif
        konfigürasyonlarla doldurur."""
        if not hasattr(self, 'quick_config_combo'):
            return
        prev = self.quick_config_combo.currentData()
        self.quick_config_combo.blockSignals(True)
        self.quick_config_combo.clear()
        try:
            configs = self.bm.list_configs(include_inactive=False)
        except Exception:
            configs = []
        for cfg in configs:
            self.quick_config_combo.addItem(
                f"{cfg['config_name']}", cfg['id']
            )
        if prev is not None:
            idx = self.quick_config_combo.findData(prev)
            if idx >= 0:
                self.quick_config_combo.setCurrentIndex(idx)
        self.quick_config_combo.blockSignals(False)

    # ── Hızlı batch handler'ları ─────────────────────────────────
    def _on_quick_start(self):
        name = (self.quick_name_edit.text() or '').strip()
        cfg_id = self.quick_config_combo.currentData()
        if not name:
            QMessageBox.warning(self, "Eksik Bilgi", "Batch adı zorunludur.")
            return
        if cfg_id is None:
            QMessageBox.warning(self, "Eksik Bilgi", "Bir konfig seçin.")
            return
        try:
            self.bm.start_batch(name, int(cfg_id))
        except (PermissionDenied, BatchInProgress, ValueError) as e:
            QMessageBox.warning(self, "Hata", str(e))
            return

        self.quick_name_edit.clear()
        self.refresh_active_batch()
        self._notify_batch_changed()

    def _on_advance_phase(self):
        """Faz-12: GLT aşaması → ORABS aşaması geçişi.

        Sıra:
          1. Bekleyen (PENDING) port varsa geçiş reddedilir.
          2. FAIL portlar için operatörden açıklama istenir (audit +
             batch_ports.explanation) — kullanıcı onayıyla geçilebilir.
          3. Config'te 'locked' olan kapıların FİZİKSEL olarak kapalı olması
             istenir (DI sensör). Açık kapı varsa isim listesiyle uyarılır.
          4. bm.advance_to_orabs_phase() → kilitler yazılır, makine durdurma
             normal mantığa döner.
        """
        ab = self.bm.get_active_batch()
        if not ab or ab.get('status') not in ('running', 'paused') \
                or (ab.get('phase') or 'orabs') != 'glt':
            return
        # 1) PENDING kontrolü
        bstatus = self._batch_member_port_status()
        n_pend = sum(1 for s in bstatus.values() if s == 'PENDING')
        if not bstatus or n_pend:
            QMessageBox.warning(
                self, "ORABS'a Geç",
                f"Bekleyen {n_pend} port var. Tüm portlar test edilmeden "
                "ORABS aşamasına geçilemez." if bstatus else
                "Port test durumu okunamadı (bağlı GLT batch bulunamadı)."
            )
            return
        # 2) FAIL portlar → açıklama zorunlu
        fail_idx = sorted(i for i, s in bstatus.items() if s == 'FAIL')
        if fail_idx:
            if QMessageBox.question(
                self, "FAIL Portlar",
                f"{len(fail_idx)} port FAIL durumda (port: "
                f"{', '.join(str(i) for i in fail_idx)}).\n\n"
                "Her FAIL port için açıklama girerek yine de ORABS "
                "aşamasına geçebilirsiniz. Devam edilsin mi?",
                QMessageBox.Yes | QMessageBox.No
            ) != QMessageBox.Yes:
                return
            # Bağlı GLT batch'in FAIL port satırlarına açıklama yaz.
            try:
                linked = self.db.find_active_linked_glt_batch(1)
                det = self.db.get_batch_details(int(linked['id'])) \
                    if linked else None
            except Exception:
                det = None
            if det:
                try:
                    all_ports = {p['id']: p for p in
                                 (self.db.get_all_ports() or [])}
                except Exception:
                    all_ports = {}
                from PyQt5.QtWidgets import QInputDialog
                for p in det.get('ports', []):
                    if (p.get('status') or '').upper() != 'FAIL':
                        continue
                    pid = p.get('port_id', 0)
                    pname = (all_ports.get(pid, {}) or {}).get(
                        'name', f"Port {pid}")
                    text, ok = QInputDialog.getText(
                        self, "FAIL Açıklaması",
                        f"{pname} (RFID: {p.get('rfid_tag', '?')}) FAIL.\n"
                        "Açıklama girin (zorunlu):"
                    )
                    expl = (text or '').strip() if ok else ''
                    if not expl:
                        QMessageBox.warning(
                            self, "ORABS'a Geç",
                            "Açıklama girilmeden geçiş yapılamaz."
                        )
                        return
                    try:
                        self.db.update_batch_port_explanation(
                            det['id'], pid, expl)
                    except Exception:
                        pass
        # 3) Kilitlenecek kapılar fiziksel kapalı mı? (DI sensör: 1 = açık)
        locked_doors = sorted(
            int(k) for k, v in (ab.get('door_states') or {}).items()
            if str(v).lower() == 'locked'
        )
        sensor = {}
        try:
            bridge = getattr(self, '_io_bridge', None)
            if bridge is not None:
                sensor = bridge.get_door_sensor_states() or {}
        except Exception:
            sensor = {}
        open_locked = [d for d in locked_doors
                       if int(sensor.get(int(d), 0)) == 1]
        if open_locked:
            try:
                labels = {int(r['door_index']): (r.get('label') or '').strip()
                          for r in self.bm.get_door_labels()}
            except Exception:
                labels = {}
            names = ', '.join(
                labels.get(d) or f"Kapı {d}" for d in open_locked
            )
            QMessageBox.warning(
                self, "Kapıları Kapatın",
                "ORABS aşamasında kilitlenecek şu kapılar hâlâ AÇIK:\n\n"
                f"{names}\n\nLütfen kapıları kapatıp tekrar deneyin."
            )
            return
        # 4) Geçiş
        if QMessageBox.question(
            self, "ORABS'a Geç",
            "GLT aşaması tamamlandı. ORABS aşamasına geçilsin mi?\n"
            "(Kilitler uygulanacak, makine çalışabilir duruma gelecek.)",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        try:
            self.bm.advance_to_orabs_phase()
        except (PermissionDenied, BatchInProgress) as e:
            QMessageBox.warning(self, "Hata", str(e))
            return
        self.refresh_active_batch()
        self._notify_batch_changed()
        QMessageBox.information(
            self, "ORABS Aşaması",
            "ORABS aşaması başladı — kilitler uygulandı."
        )

    # Faz-9: Ana ekrandan yapılan batch mutate'ini ORABS batch panel'in
    # `batch_changed` sinyaline emit et — aksi halde io_bridge.on_batch_changed
    # çağrılmaz ve DO kilit yazımları kapı durumuna göre güncellenmez.
    def _notify_batch_changed(self):
        mw = self.window()
        batch_panel = getattr(getattr(mw, 'oraps_panel', None), 'batch', None)
        if batch_panel is not None and hasattr(batch_panel, 'batch_changed'):
            try:
                batch_panel.batch_changed.emit()
                return
            except Exception:
                pass
        # Fallback: bridge'e doğrudan bildir.
        bridge = getattr(getattr(mw, 'oraps_panel', None), 'io_bridge', None)
        if bridge is not None and hasattr(bridge, 'on_batch_changed'):
            try:
                bridge.on_batch_changed()
            except Exception:
                pass

    def _on_quick_pause(self):
        try:
            self.bm.pause_batch()
        except (PermissionDenied, BatchInProgress) as e:
            QMessageBox.warning(self, "Hata", str(e))
            return
        self.refresh_active_batch()
        self._notify_batch_changed()

    def _on_quick_unlock(self):
        """Batch duraklatılmışken seçilen kapı grubunun kilidini aç.
        Açıklama zorunlu (audit trail'e kaydedilir)."""
        ab = self.bm.get_active_batch()
        if not ab or ab.get('status') != 'paused':
            QMessageBox.warning(self, "Kilit Aç",
                                "Kilit açma yalnızca batch duraklatılmışken yapılabilir.")
            return

        # Kapı gruplarını al
        try:
            groups = self.bm.list_door_groups() or []
        except Exception:
            groups = []
        if not groups:
            QMessageBox.warning(self, "Kilit Aç", "Tanımlı kapı grubu bulunamadı.")
            return

        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QComboBox, QTextEdit, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("🔓 Kapı Grubu Kilidi Aç")
        dlg.setMinimumSize(780, 520)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 20)

        info = QLabel(
            "Batch duraklatılmışken seçtiğiniz grubun kilidini geçici olarak "
            "açabilirsiniz. Bu işlem audit trail'e kaydedilir."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#374151; font-size:16px;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(14)
        _lbl_qss = "font-size:17px; font-weight:600; color:#1f2937;"

        group_combo = QComboBox()
        group_combo.setCursor(Qt.PointingHandCursor)
        group_combo.setMinimumHeight(52)
        group_combo.setStyleSheet(
            "QComboBox { border:1px solid #d1d5db; border-radius:8px;"
            " padding:12px 14px; background:#ffffff; font-size:17px;"
            " color:#1f2937; }"
            " QComboBox::drop-down { width:44px; }"
            " QComboBox QAbstractItemView { background:#ffffff;"
            " color:#1f2937; font-size:17px;"
            " selection-background-color:#2563eb;"
            " selection-color:#ffffff; outline:0; }"
        )
        for g in groups:
            gid = g.get('id')
            name = g.get('name') or f"Grup #{gid}"
            group_combo.addItem(name, gid)
        _lbl_grp = QLabel("Kapı Grubu:")
        _lbl_grp.setStyleSheet(_lbl_qss)
        form.addRow(_lbl_grp, group_combo)

        reason_edit = QTextEdit()
        reason_edit.setPlaceholderText("Kilidi neden açıyorsunuz? (zorunlu)")
        reason_edit.setMinimumHeight(140)
        reason_edit.setStyleSheet(
            "QTextEdit { border:1px solid #d1d5db; border-radius:8px;"
            " padding:10px; background:#ffffff; font-size:16px; }"
        )
        _lbl_rsn = QLabel("Açıklama:")
        _lbl_rsn.setStyleSheet(_lbl_qss)
        form.addRow(_lbl_rsn, reason_edit)
        layout.addLayout(form)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Kilidi Aç")
        buttons.button(QDialogButtonBox.Cancel).setText("İptal")
        for _b in (buttons.button(QDialogButtonBox.Ok),
                   buttons.button(QDialogButtonBox.Cancel)):
            _b.setCursor(Qt.PointingHandCursor)
            _b.setMinimumSize(160, 52)
            _b.setStyleSheet("font-size:17px; font-weight:600;")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec_() != QDialog.Accepted:
            return

        reason = reason_edit.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Kilit Aç", "Açıklama zorunludur.")
            return

        selected_gid = group_combo.currentData()
        if selected_gid is None:
            return

        # Gruptaki kapıları bul
        try:
            all_labels = self.bm.get_door_labels() or []
            member_indices = [
                int(row['door_index']) for row in all_labels
                if row.get('group_id') is not None and int(row['group_id']) == int(selected_gid)
            ]
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Grup üyeleri okunamadı:\n{e}")
            return

        if not member_indices:
            QMessageBox.warning(self, "Kilit Aç", "Seçilen grupta kapı bulunamadı.")
            return

        # Mevcut state kontrolü — zaten açıksa uyar, boşa işlem yapma.
        door_states = dict(ab.get('door_states', {}) or {})
        already_open = all(
            door_states.get(str(idx), 'open') == 'open' for idx in member_indices
        )
        if already_open:
            QMessageBox.information(
                self, "Kilit Aç",
                f"'{group_combo.currentText()}' grubu zaten açık durumda."
            )
            return

        # Aktif batch'in door_states'ini güncelle (üyeleri 'open' yap)
        try:
            for idx in member_indices:
                door_states[str(idx)] = 'open'
            self.bm.update_batch_door_states(door_states)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Batch state güncellenemedi:\n{e}")
            return

        # IO bridge'e bildir — DO kanallarını güncelle
        try:
            bridge = getattr(self, '_io_bridge', None)
            if bridge is not None:
                bridge.apply_door_locks(door_states)
        except Exception:
            pass

        # Audit log
        try:
            group_name = group_combo.currentText()
            self.audit.log_action(
                'BATCH_DOOR_UNLOCK',
                description=(
                    f"Kapı grubu kilidi açıldı: '{group_name}' "
                    f"({len(member_indices)} kapı). Sebep: {reason}"
                ),
                category='ORAPS',
            )
        except Exception:
            pass

        self.refresh_active_batch()
        self._notify_batch_changed()
        QMessageBox.information(
            self, "Kilit Açıldı",
            f"'{group_combo.currentText()}' grubunun kilidi açıldı "
            f"({len(member_indices)} kapı)."
        )

    def _on_quick_lock(self):
        """Batch duraklatılmışken seçilen kapı grubunu tekrar kilitle.
        Açıklama zorunlu (audit trail'e kaydedilir)."""
        ab = self.bm.get_active_batch()
        if not ab or ab.get('status') != 'paused':
            QMessageBox.warning(self, "Kilitle",
                                "Kilitleme yalnızca batch duraklatılmışken yapılabilir.")
            return

        # Kapı gruplarını al
        try:
            groups = self.bm.list_door_groups() or []
        except Exception:
            groups = []
        if not groups:
            QMessageBox.warning(self, "Kilitle", "Tanımlı kapı grubu bulunamadı.")
            return

        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QComboBox, QTextEdit, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("🔒 Kapı Grubu Kilitle")
        dlg.setMinimumSize(780, 520)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 20)

        info = QLabel(
            "Batch duraklatılmışken seçtiğiniz grubun kilidini tekrar "
            "aktif edebilirsiniz. Bu işlem audit trail'e kaydedilir."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#374151; font-size:16px;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(14)
        _lbl_qss = "font-size:17px; font-weight:600; color:#1f2937;"

        group_combo = QComboBox()
        group_combo.setCursor(Qt.PointingHandCursor)
        group_combo.setMinimumHeight(52)
        group_combo.setStyleSheet(
            "QComboBox { border:1px solid #d1d5db; border-radius:8px;"
            " padding:12px 14px; background:#ffffff; font-size:17px;"
            " color:#1f2937; }"
            " QComboBox::drop-down { width:44px; }"
            " QComboBox QAbstractItemView { background:#ffffff;"
            " color:#1f2937; font-size:17px;"
            " selection-background-color:#2563eb;"
            " selection-color:#ffffff; outline:0; }"
        )
        for g in groups:
            gid = g.get('id')
            name = g.get('name') or f"Grup #{gid}"
            group_combo.addItem(name, gid)
        _lbl_grp = QLabel("Kapı Grubu:")
        _lbl_grp.setStyleSheet(_lbl_qss)
        form.addRow(_lbl_grp, group_combo)

        reason_edit = QTextEdit()
        reason_edit.setPlaceholderText("Kilitleme sebebi (zorunlu)")
        reason_edit.setMinimumHeight(140)
        reason_edit.setStyleSheet(
            "QTextEdit { border:1px solid #d1d5db; border-radius:8px;"
            " padding:10px; background:#ffffff; font-size:16px; }"
        )
        _lbl_rsn = QLabel("Açıklama:")
        _lbl_rsn.setStyleSheet(_lbl_qss)
        form.addRow(_lbl_rsn, reason_edit)
        layout.addLayout(form)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Kilitle")
        buttons.button(QDialogButtonBox.Cancel).setText("İptal")
        for _b in (buttons.button(QDialogButtonBox.Ok),
                   buttons.button(QDialogButtonBox.Cancel)):
            _b.setCursor(Qt.PointingHandCursor)
            _b.setMinimumSize(160, 52)
            _b.setStyleSheet("font-size:17px; font-weight:600;")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec_() != QDialog.Accepted:
            return

        reason = reason_edit.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Kilitle", "Açıklama zorunludur.")
            return

        selected_gid = group_combo.currentData()
        if selected_gid is None:
            return

        # Gruptaki kapıları bul
        try:
            all_labels = self.bm.get_door_labels() or []
            member_indices = [
                int(row['door_index']) for row in all_labels
                if row.get('group_id') is not None and int(row['group_id']) == int(selected_gid)
            ]
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Grup üyeleri okunamadı:\n{e}")
            return

        if not member_indices:
            QMessageBox.warning(self, "Kilitle", "Seçilen grupta kapı bulunamadı.")
            return

        # Mevcut state kontrolü — zaten kilitliyse uyar, boşa işlem yapma.
        door_states = dict(ab.get('door_states', {}) or {})
        already_locked = all(
            door_states.get(str(idx), 'open') == 'locked' for idx in member_indices
        )
        if already_locked:
            QMessageBox.information(
                self, "Kilitle",
                f"'{group_combo.currentText()}' grubu zaten kilitli durumda."
            )
            return

        # Aktif batch'in door_states'ini güncelle (üyeleri 'locked' yap)
        try:
            for idx in member_indices:
                door_states[str(idx)] = 'locked'
            self.bm.update_batch_door_states(door_states)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Batch state güncellenemedi:\n{e}")
            return

        # IO bridge'e bildir — DO kanallarını güncelle
        try:
            bridge = getattr(self, '_io_bridge', None)
            if bridge is not None:
                bridge.apply_door_locks(door_states)
        except Exception:
            pass

        # Audit log
        try:
            group_name = group_combo.currentText()
            self.audit.log_action(
                'BATCH_DOOR_LOCK',
                description=(
                    f"Kapı grubu kilitlendi: '{group_name}' "
                    f"({len(member_indices)} kapı). Sebep: {reason}"
                ),
                category='ORAPS',
            )
        except Exception:
            pass

        self.refresh_active_batch()
        self._notify_batch_changed()
        QMessageBox.information(
            self, "Kilitlendi",
            f"'{group_combo.currentText()}' grubu kilitlendi "
            f"({len(member_indices)} kapı)."
        )

    def _on_quick_resume(self):
        try:
            self.bm.resume_batch()
        except (PermissionDenied, BatchInProgress) as e:
            QMessageBox.warning(self, "Hata", str(e))
            return
        # Resume: runtime door_states override'ını temizle → config
        # state'ine dön. Böylece kilit açıp batch devam ettirince
        # orijinal kilit/açık durumu otomatik geri yüklenir.
        try:
            self.bm.clear_batch_door_states_override()
        except Exception:
            pass
        # DO kilit komutlarını config state'ine göre tekrar yaz
        try:
            bridge = getattr(self, '_io_bridge', None)
            if bridge is not None:
                bridge.on_batch_changed()
        except Exception:
            pass
        self.refresh_active_batch()
        self._notify_batch_changed()

    def _on_quick_finish(self):
        if QMessageBox.question(
            self, "Batch Bitir",
            "Aktif batch'i bitirmek istediğinizden emin misiniz?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        try:
            self.bm.finish_batch()
        except (PermissionDenied, BatchInProgress) as e:
            QMessageBox.warning(self, "Hata", str(e))
            return

        # Faz-8: Bağlı GLT batch'i BatchPanel.finish_glt_batch_interactive
        # üzerinden tamamla → GLT'nin FAIL/PENDING açıklama diyalogları,
        # complete_batch + audit + kendi özet PDF'i tek noktadan işlenir.
        # Kaydedilmiş linked GLT id'yi ORABS PDF üretimi için kullanabilmek
        # üzere bir kenara alıyoruz (get_active_batch bittiği için).
        self._last_finished_glt_id = None
        try:
            linked = self.db.find_active_linked_glt_batch(linked_oraps_batch_id=1)
        except Exception:
            linked = None
        if linked and linked.get('id'):
            try:
                linked_full = self.db.get_batch_details(int(linked['id'])) or linked
            except Exception:
                linked_full = linked
            self._last_finished_glt_id = int(linked['id'])
            batch_panel = getattr(self.window(), 'batch_panel', None)
            if batch_panel is not None and hasattr(batch_panel, 'finish_glt_batch_interactive'):
                try:
                    batch_panel.finish_glt_batch_interactive(
                        linked_full,
                        parent=self,
                        verify_password=False,
                        auto_show_pdf=False,   # ORABS özet PDF'i açacak
                    )
                except Exception as e:
                    QMessageBox.warning(
                        self, "GLT Batch",
                        f"ORABS batch bitti ama bağlı GLT batch akışı çalıştırılamadı:\n{e}"
                    )
            else:
                # Fallback (batch_panel yoksa): sessizce complete_batch + audit.
                try:
                    self.db.complete_batch(int(linked['id']))
                    try:
                        self.audit.log_action(
                            action_type='BATCH_FINISHED',
                            category='GLT',
                            table_name='test_batches',
                            record_id=int(linked['id']),
                            description=(
                                f"GLT batch bitti (ORABS ile birleşik): "
                                f"'{linked.get('batch_name')}' #{linked['id']}"
                            ),
                        )
                    except Exception:
                        pass
                except Exception as e:
                    QMessageBox.warning(
                        self, "GLT Batch",
                        f"ORABS batch bitti ama bağlı GLT batch kapatılamadı:\n{e}"
                    )

        self.refresh_active_batch()
        # Faz-9: bridge'e bildir → aktif batch bittiği için DO kilit
        # yazımı uygun state'e (tüm kapılar 'open' veya son state) geçer.
        self._notify_batch_changed()

        # Faz-8: ORABS özet PDF (denetim izi + alarm + hareket + port).
        try:
            pdf_path = self._generate_batch_summary_pdf(silent=True)
            # Kompakt özet rapor (alarm + port) da otomatik üretilir —
            # Rapor Ayarları'ndaki 'report_auto_summary' ile kapatılabilir.
            try:
                if str(self.db.get_setting(
                        'report_auto_summary', '1')).strip() != '0':
                    self._generate_batch_summary_pdf(silent=True, compact=True)
            except Exception:
                pass
            if pdf_path:
                try:
                    QMessageBox.information(
                        self, "Rapor",
                        f"Batch tamamlandı. Rapor otomatik oluşturuldu:\n{pdf_path}"
                    )
                    # PDF'i uygulama içinde aç (tam ekran viewer).
                    try:
                        from gui.pdf_viewer_dialog import PdfViewerDialog
                        PdfViewerDialog(pdf_path, parent=self).exec_()
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            import traceback; traceback.print_exc()

    # ── Batch özet raporu (Faz-8) ────────────────────────────────
    # Batch aralığındaki audit satırlarından PORT_MOTION + DOOR_OPENED/CLOSED
    # çiftlerini "başlangıç/bitiş" satırlarına dönüştür. PDF Sayfa 2'deki
    # "Eldiven Port ve Kapak Hareketleri" tablosunun kaynağı.
    def _build_movement_records(self, records):
        """Batch özet raporundaki 'Eldiven Port Hareketleri' tablosu —
        YALNIZCA port hareket sensörü (PORT_MOTION/_END) çiftleri.
        Kapak aç/kapa olayları bu tabloya GİRMEZ (denetim izi
        tablosunda zaten listelenir; kullanıcı isteği 2026-08-05)."""
        open_ports: dict[int, str] = {}
        out: list[dict] = []
        # Kronolojik sıra (audit_trail default DESC → sort ASC).
        for r in sorted(records, key=lambda x: x.get('timestamp') or ''):
            at = (r.get('action_type') or '').upper()
            rid = r.get('record_id')
            ts = r.get('timestamp') or ''
            try:
                rid_int = int(rid) if rid is not None else None
            except (TypeError, ValueError):
                rid_int = None
            if rid_int is None:
                continue
            if at == 'PORT_MOTION':
                open_ports[rid_int] = ts
            elif at == 'PORT_MOTION_END':
                start = open_ports.pop(rid_int, None)
                out.append({
                    'code': f"Z{rid_int:02d}",
                    'description': (
                        f"Port {rid_int} Hareket Algılandı / "
                        f"Port {rid_int} Movement Detected"
                    ),
                    'start': start or '',
                    'end': ts,
                })
        # Kapanmamış olayları da göster (bitiş boş)
        for pidx, sts in open_ports.items():
            out.append({
                'code': f"Z{pidx:02d}",
                'description': (
                    f"Port {pidx} Hareket Algılandı / "
                    f"Port {pidx} Movement Detected"
                ),
                'start': sts, 'end': '',
            })
        return out

    def _load_batch_alarm_records(self, start_iso: str, end_iso: str) -> list[dict]:
        """Batch aralığındaki LAF alarm event'lerini oku."""
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            cur.execute(
                'SELECT id, timestamp, flag_code, message, cleared_at '
                'FROM laf_alarm_events '
                'WHERE timestamp BETWEEN ? AND ? '
                'ORDER BY timestamp',
                (start_iso, end_iso),
            )
            rows = [dict(r) for r in cur.fetchall()]
            self.db.close()
            return rows
        except Exception:
            try:
                self.db.close()
            except Exception:
                pass
            return []

    # Alarm tablosu için başlangıç→bitiş eşleşmeleri (denetim izinden).
    _ALARM_END_TO_STARTS = {
        'MACHINE_STOP_CLEARED': ('MACHINE_STOP_TRIGGERED',),
        'ESTOP_RELEASED': ('ESTOP_TRIGGERED',),
        'DOOR_FORCED_CLOSED': ('DOOR_FORCED',),
        'AI_ALARM_OK': ('AI_ALARM_HIGH', 'AI_ALARM_LOW'),
    }
    _ALARM_START_ACTIONS = ('MACHINE_STOP_TRIGGERED', 'ESTOP_TRIGGERED',
                            'DOOR_FORCED', 'AI_ALARM_HIGH', 'AI_ALARM_LOW')

    def _build_alarm_rows(self, records) -> list[dict]:
        """Denetim izi kayıtlarından Alarm tablosu satırları üret
        (2026-08-06). Önceden tablo yalnız LAF alarmlarını gösteriyor,
        bariyer/makine durdurma/acil stop alarmları varken 'alarm yok'
        yazıyordu. Başlangıç/bitiş çiftleri record_id üzerinden eşleşir.
        Satır: {'code','description','start','end'}"""
        rows: list[dict] = []
        open_by_key: dict = {}

        def _code_of(desc_raw: str) -> str:
            m = re.match(r'^\s*\[([A-Za-z]{1,4}-?\d{0,3})\]', desc_raw or '')
            return m.group(1) if m else ''

        for r in sorted(records, key=lambda x: str(x.get('timestamp') or '')):
            at = (r.get('action_type') or '').upper()
            ts = r.get('timestamp') or ''
            rid = r.get('record_id')
            desc_raw = str(r.get('description') or '').strip()
            desc = _strip_code_prefix(desc_raw)
            code = _code_of(desc_raw)
            if at == 'BARRIER_TRIGGERED':
                key = ('bar', rid)
                if 'BLOKE' in desc_raw.upper():
                    row = {'code': code or 'IB-01', 'description': desc,
                           'start': ts, 'end': ''}
                    open_by_key[key] = row
                    rows.append(row)
                else:   # serbest → açık satırı kapat
                    row = open_by_key.pop(key, None)
                    if row is not None:
                        row['end'] = ts
                continue
            if at in self._ALARM_START_ACTIONS:
                row = {'code': code or '', 'description': desc,
                       'start': ts, 'end': ''}
                open_by_key[(at, rid)] = row
                rows.append(row)
                continue
            starts = self._ALARM_END_TO_STARTS.get(at)
            if starts:
                for st in starts:
                    row = open_by_key.pop((st, rid), None)
                    if row is not None:
                        row['end'] = ts
                        break
                continue
            if at == 'BATCH_INTERLOCK_TRIPPED':
                rows.append({'code': code or 'IB-02', 'description': desc,
                             'start': ts, 'end': ''})
        return rows

    def _load_batch_ports(self, linked_glt_id: Optional[int]) -> tuple[list[dict], dict]:
        """GLT batch id (aktif veya biten) varsa port detaylarını çek.
        `Database`'de "biten batch details" metodu olmadığı için doğrudan
        `test_batches` + `batch_ports` sorgusuyla çekiyoruz.
        """
        if not linked_glt_id:
            return [], {}
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            cur.execute(
                'SELECT bp.* FROM batch_ports bp '
                'LEFT JOIN test_records tr ON bp.test_record_id = tr.id '
                'WHERE bp.batch_id = ? '
                'ORDER BY CASE WHEN tr.test_start_time IS NULL THEN 1 ELSE 0 END, '
                '         tr.test_start_time ASC',
                (int(linked_glt_id),)
            )
            ports = [dict(r) for r in cur.fetchall()]
            self.db.close()
        except Exception:
            try:
                self.db.close()
            except Exception:
                pass
            return [], {}
        all_ports_dict = {}
        try:
            for p in self.db.get_all_ports() or []:
                all_ports_dict[int(p.get('id'))] = dict(p)
        except Exception:
            pass
        return ports, all_ports_dict

    def _resolve_linked_glt_id(self, orabs_batch_name: str) -> Optional[int]:
        """Batch summary PDF için linked GLT batch id'sini üç kaynaktan çöz:
          1. `find_active_linked_glt_batch` — hâlâ aktifse.
          2. `_last_finished_glt_id` — bu turda `_on_quick_finish` tarafından set.
          3. DB'den ORAPS batch adına göre en son test_batches satırı (COMPLETED
             dahil) — kullanıcı 'Rapor' butonuna sonradan bassa da bulsun.
        """
        try:
            linked = self.db.find_active_linked_glt_batch(linked_oraps_batch_id=1)
            if linked and linked.get('id'):
                return int(linked['id'])
        except Exception:
            pass
        cached = getattr(self, '_last_finished_glt_id', None)
        if cached:
            try:
                return int(cached)
            except (TypeError, ValueError):
                pass
        if not orabs_batch_name:
            return None
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            cur.execute(
                'SELECT id FROM test_batches '
                'WHERE linked_oraps_batch_id=1 AND batch_name=? '
                'ORDER BY id DESC LIMIT 1',
                (orabs_batch_name,),
            )
            row = cur.fetchone()
            self.db.close()
            if row:
                try:
                    return int(row['id'])
                except (TypeError, KeyError, IndexError):
                    try:
                        return int(row[0])
                    except (TypeError, ValueError, IndexError):
                        return None
        except Exception:
            try:
                self.db.close()
            except Exception:
                pass
        return None

    def _generate_batch_summary_pdf(self, silent: bool = False,
                                    compact: bool = False) -> Optional[str]:
        """Aktif/son biten ORAPS batch için özet PDF üret.
        silent=True → popup yok (batch bittiğinde otomatik çağrı için).
        compact=True → yalnızca alarmlar + port sonuçları (hareket tablosu
        ve genel denetim izi yok; dosya adına '_ozet' eklenir).
        Return: PDF path veya None.
        """
        if self.pdf_gen is None:
            if not silent:
                QMessageBox.warning(self, "Rapor", "PDF üretici hazır değil.")
            return None
        ab = self.bm.get_active_batch()
        if not ab or not ab.get('started_at'):
            if not silent:
                QMessageBox.information(
                    self, "Rapor",
                    "Raporlanacak aktif veya yakın bir batch yok."
                )
            return None
        from datetime import datetime
        start_iso = ab.get('started_at')
        status_lower = (ab.get('status') or '').lower()
        # Batch bittiyse: BATCH_FINISHED audit timestamp'ini bitiş olarak al.
        end_iso = datetime.now().isoformat()
        if status_lower == 'finished':
            try:
                fin = self.audit.get_audit_trail({
                    'action_type': 'BATCH_FINISHED',
                    'date_from': start_iso,
                }) or []
                if fin:
                    end_iso = fin[0].get('timestamp') or end_iso
            except Exception:
                pass
        linked_glt_id = self._resolve_linked_glt_id(ab.get('batch_name') or '')
        return self._build_batch_report_pdf(
            batch_name=ab.get('batch_name') or 'ORAPS Batch',
            start_iso=start_iso,
            end_iso=end_iso,
            status=('COMPLETED' if status_lower == 'finished'
                    else 'IN_PROGRESS'),
            linked_glt_id=linked_glt_id,
            compact=compact,
            silent=silent,
        )

    def regenerate_report_from_registry(self, entry: dict) -> Optional[str]:
        """Rapor Arşivi: `oraps_report_registry` satırından raporu yeniden
        üret (PDF diskten silinmiş olsa bile). Denetim izi/alarm/hareket
        verileri tarih aralığından, port sonuçları bağlı GLT batch'inden
        yeniden sorgulanır — tarihsel batch'ler de desteklenir."""
        from datetime import datetime
        return self._build_batch_report_pdf(
            batch_name=entry.get('batch_name') or 'ORAPS Batch',
            start_iso=entry.get('start_iso') or '',
            end_iso=entry.get('end_iso') or datetime.now().isoformat(),
            status=entry.get('status') or 'COMPLETED',
            linked_glt_id=entry.get('linked_glt_id'),
            compact=(str(entry.get('report_kind') or '') == 'ozet'),
            silent=True,
        )

    def _build_batch_report_pdf(self, *, batch_name: str, start_iso: str,
                                end_iso: str, status: str,
                                linked_glt_id, compact: bool,
                                silent: bool) -> Optional[str]:
        """Parametrik batch/özet raporu üretim çekirdeği (2026-08-06).
        Hem aktif/son batch'ten (`_generate_batch_summary_pdf`) hem rapor
        kayıt defterinden (`regenerate_report_from_registry`) çağrılır.
        Üretim sonrası `oraps_report_registry`'ye upsert yapılır."""
        if self.pdf_gen is None:
            if not silent:
                QMessageBox.warning(self, "Rapor", "PDF üretici hazır değil.")
            return None
        # 1) Audit — batch aralığındaki tüm satırlar
        try:
            audit_all = self.audit.get_audit_trail({
                'date_from': start_iso,
                'date_to': end_iso,
            }) or []
        except Exception:
            audit_all = []
        # ORABS batch raporu: kategori filtresi YOK — batch aralığındaki
        # TÜM audit kayıtları denetim izine girer (kullanıcı isteği
        # 2026-08-05; önceden ORAPS + seçili batch olaylarıyla sınırlıydı).
        audit_pdf = list(audit_all)
        # Kompakt rapor: denetim izi ALARM + kapı/interlock + batch yaşam
        # döngüsü olaylarına indirgenir (müşteri listesi 2026-08-06:
        # madde 1-4; rutin işletim kayıtları — login, ayar, RFID vs. —
        # yalnız tam batch raporunda kalır).
        _ALARM_ACTIONS = {
            'DOOR_FORCED', 'DOOR_FORCED_CLOSED', 'BARRIER_TRIGGERED',
            'BATCH_INTERLOCK_TRIPPED', 'MACHINE_STOP_TRIGGERED',
            'MACHINE_STOP_CLEARED', 'ESTOP_TRIGGERED', 'ESTOP_RELEASED',
            'LAF_ALARM', 'LAF_ALARM_CLEAR', 'LAF_ALARM_RAISED',
            'LAF_ALARM_CLEARED', 'AI_ALARM_HIGH', 'AI_ALARM_LOW',
            'AI_ALARM_OK', 'BARRIER_LOW_BATTERY',
            'DOOR_OPENED', 'DOOR_CLOSED',
            # Batch yaşam döngüsü + kilit aç/kapa işlemleri
            'BATCH_STARTED', 'BATCH_PAUSED', 'BATCH_RESUMED',
            'BATCH_FINISHED', 'BATCH_COMPLETED', 'BATCH_PHASE_ORABS',
            'BATCH_DOOR_UNLOCK', 'BATCH_DOOR_LOCK',
        }
        if compact:
            audit_pdf = [
                r for r in audit_pdf
                if (r.get('action_type') or '') in _ALARM_ACTIONS
            ]
        # 2) Alarm tablosu — LAF alarmları + denetim izinden türetilen
        #    başlangıç/bitiş çiftli alarm olayları (bariyer, makine durdurma,
        #    acil stop, zorla açma, AI). 2026-08-06: tablo önceden yalnız
        #    LAF gösterip diğer alarmlar varken 'alarm yok' yazıyordu.
        #    `report_include_laf` yalnız LAF satırlarını kontrol eder.
        _inc_laf = str(self.db.get_setting(
            'report_include_laf', '1')).strip() != '0'
        laf_rows = (self._load_batch_alarm_records(start_iso, end_iso)
                    if (_inc_laf or compact) else [])
        alarm_records = list(laf_rows) + self._build_alarm_rows(audit_all)
        alarm_records.sort(
            key=lambda a: str(a.get('timestamp') or a.get('start') or ''))
        # 3) Movement (start/end çiftleri) — tablo YALNIZ port hareketi
        #    içerir (kapak olayları denetim izinde). 'Port hareket sensörü
        #    dahil et' ayarı KAPALIYSA bölüm PDF'e HİÇ konmaz (None) ve
        #    denetim izinden PORT_MOTION kayıtları çıkarılır.
        _inc_pm = str(self.db.get_setting(
            'report_include_port_motion', '1')).strip() != '0'
        if compact:
            movement_records = None   # kompakt raporda hareket tablosu yok
        elif _inc_pm:
            movement_records = self._build_movement_records(audit_all)
        else:
            movement_records = None   # bölümü tamamen atla
            audit_pdf = [
                r for r in audit_pdf
                if (r.get('action_type') or '') not in
                   ('PORT_MOTION', 'PORT_MOTION_END')
            ]
        # 4) Bağlı GLT batch'ten port detayları (tarihsel batch destekli)
        ports_list, all_ports_dict = self._load_batch_ports(linked_glt_id)

        batch_data = {
            'batch_name': batch_name,
            'start_time': start_iso,
            'end_time': end_iso if status == 'COMPLETED' else None,
            'status': status,
            'ports': ports_list,
        }
        # Şirket adı — Rapor Ayarları anahtarı (report_company_name) esas;
        # eski kurulumlarla uyum için legacy 'company_name' fallback'i.
        # (Bug 2026-08-01: burada yalnız 'company_name' okunuyordu → Rapor
        # Ayarları'ndaki değişiklik ORABS raporuna yansımıyordu.)
        try:
            company = (self.db.get_setting('report_company_name', '')
                       or self.db.get_setting('company_name', '')
                       or 'Farve İlaç Sanayi ve Ticaret A.Ş.')
        except Exception:
            company = 'Farve İlaç Sanayi ve Ticaret A.Ş.'
        # Kompakt raporun başlığı Rapor Ayarları'ndan (report_summary_title).
        _summary_title = None
        if compact:
            try:
                _summary_title = (self.db.get_setting(
                    'report_summary_title',
                    'Batch Alarm ve Sonuç Özet Raporu')
                    or 'Batch Alarm ve Sonuç Özet Raporu')
            except Exception:
                _summary_title = 'Batch Alarm ve Sonuç Özet Raporu'
        try:
            pdf_path = self.pdf_gen.generate_batch_summary_report(
                batch_data,
                all_ports_dict=all_ports_dict,
                company_name=company,
                lang='tr',
                audit_records=audit_pdf,
                alarm_records=alarm_records,
                movement_records=movement_records,
                filename_suffix='_ozet' if compact else '',
                report_title=_summary_title,
            )
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Rapor",
                                     f"PDF üretilemedi:\n{e}")
            return None
        # Rapor kayıt defterine upsert — dosya silinse bile arşivde kalır
        # ve bu parametrelerle yeniden üretilebilir.
        self._register_report(
            'ozet' if compact else 'batch', batch_name, pdf_path,
            start_iso, end_iso, status, linked_glt_id)
        if not silent:
            QMessageBox.information(
                self, "Rapor",
                f"Rapor oluşturuldu:\n{pdf_path}"
            )
        return pdf_path

    def _register_report(self, kind: str, batch_name: str, file_path: str,
                         start_iso: str, end_iso: str, status: str,
                         linked_glt_id) -> None:
        """`oraps_report_registry` upsert (UNIQUE(report_kind, file_path))."""
        from datetime import datetime
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO oraps_report_registry '
                '(report_kind, batch_name, file_path, start_iso, end_iso, '
                ' status, linked_glt_id, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?) '
                'ON CONFLICT(report_kind, file_path) DO UPDATE SET '
                ' batch_name=excluded.batch_name, '
                ' start_iso=excluded.start_iso, end_iso=excluded.end_iso, '
                ' status=excluded.status, '
                ' linked_glt_id=excluded.linked_glt_id, '
                ' created_at=excluded.created_at',
                (kind, batch_name, str(file_path),
                 start_iso or '', end_iso or '', status or '',
                 (int(linked_glt_id) if linked_glt_id is not None else None),
                 datetime.now().isoformat(timespec='seconds')),
            )
            conn.commit()
            self.db.close()
        except Exception:
            try:
                self.db.close()
            except Exception:
                pass

    def _on_quick_report(self):
        """Ana ekran 'Rapor' butonu — tam formatlı batch özet PDF üretir."""
        self._generate_batch_summary_pdf(silent=False)

    def _on_quick_report_compact(self):
        """Ana ekran 'Özet Rapor' butonu — yalnızca alarmlar + port
        sonuçlarını içeren kompakt batch PDF üretir."""
        self._generate_batch_summary_pdf(silent=False, compact=True)

    def _on_open_reports_browser(self):
        """Ana ekran '📚 Raporları Görüntüle' butonu — GLT + Batch PDF
        raporlarını uygulama içinde tarayıcı dialog ile listeler."""
        if self.pdf_gen is None:
            QMessageBox.warning(
                self, "Raporlar",
                "PDF üretici (pdf_gen) mevcut değil — raporlar listelenemedi."
            )
            return
        try:
            from gui.reports_browser_dialog import ReportsBrowserDialog
            ReportsBrowserDialog(self.pdf_gen, parent=self,
                                 db=self.db).exec_()
        except Exception as e:
            QMessageBox.critical(
                self, "Raporlar",
                f"Rapor tarayıcısı açılamadı:\n{e}"
            )

    def refresh_laf_info(self):
        """LAF sensör düzenleme dialogunda 'Ana Ekran' işaretli sensörlerin
        son değerlerini ve aktif alarmları (kod + mesaj) listele.

        5 saniye periyodik info_timer'ın eski hali her tetikte tüm chip
        widget'larını silip yeniden inşa ediyordu → LAF kartı yüksekliği
        anlık değişiyor → cascade resize → 3D viewer titremesi.
        Şimdi sensör listesi (id+label+unit) aynı olduğu sürece chip
        widget'ları yerlerinde kalıyor; sadece değer label'ı güncelleniyor.
        """
        # Sensors (overview-flagged only)
        try:
            sensors = self.laf.list_sensors(only_overview=True)
        except Exception:
            sensors = []
        try:
            latest = self.laf.latest_reading_per_sensor()
        except Exception:
            latest = {}
        try:
            alarms = self.laf.list_active_alarms()
        except Exception:
            alarms = []

        # ── Status / counts (diff'li — setText ancak metin değişince) ──
        n_sens = len(sensors)
        if n_sens == 0:
            new_status = (
                "<span style='color:#9ca3af;'>"
                "Ana ekranda gösterilecek LAF sensörü yok — "
                "<b>LAF sekmesinden</b> sağ üstteki "
                "<b>“🏠 Ana Ekran Sensörleri…”</b> butonuna tıklayıp "
                "göstermek istediklerinizi işaretleyin.</span>"
            )
        else:
            new_status = (
                f"<span style='color:#374151;'>"
                f"<b>{n_sens}</b> sensör · son okumalar:</span>"
            )
        if new_status != self._laf_status_html:
            self._laf_status_html = new_status
            self.laf_status_lbl.setText(new_status)

        # ── Sensör grid — sadece liste değiştiğinde rebuild ──
        chips_key = tuple(
            (s['id'], s.get('label') or s.get('name') or '',
             s.get('unit') or '')
            for s in sensors
        )
        if chips_key != self._laf_chips_key:
            # Tam rebuild gerekli (sensör eklendi/silindi/etiket değişti).
            self._laf_chips_key = chips_key
            while self.laf_values_layout.count():
                it = self.laf_values_layout.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
            self._laf_chips = {}
            cols = 2
            for i, s in enumerate(sensors):
                r, c = divmod(i, cols)
                chip = self._build_laf_value_chip(s, latest.get(s['id']))
                self.laf_values_layout.addWidget(chip, r, c)
                self._laf_chips[s['id']] = chip
        else:
            # Sadece değer label'larını güncelle (layout sabit kalır).
            for s in sensors:
                chip = self._laf_chips.get(s['id'])
                if chip is not None:
                    self._update_laf_chip_value(chip, latest.get(s['id']),
                                                s.get('unit') or '')

        # ── GLB viewer overlay (Faz-5) ──
        # Aynı sensör listesi (kart cache'i ile aynı set) viewer üzerinde
        # DOM chip olarak gösterilir. Three.js sahnesine dokunulmaz.
        self._push_laf_overlay(sensors, latest, chips_changed=(chips_key != getattr(self, '_last_overlay_key', None)))

        # ── Active alarms — diff'li setText (HTML aynıysa dokunma) ──
        if not alarms:
            new_alarms_html = (
                "<span style='color:#059669;font-weight:600;'>🟢 Alarm yok</span>"
            )
        else:
            lines = [
                "<span style='color:#dc2626;font-weight:600;'>"
                f"🔴 {len(alarms)} aktif alarm</span>"
            ]
            for a in alarms:
                code = str(a.get('flag_code') or '?')
                msg = str(a.get('message') or '').strip()
                ts = str(a.get('timestamp') or '')[11:19]  # HH:MM:SS
                msg_html = (
                    f" — <span style='color:#374151;'>{_escape_html(msg)}</span>"
                    if msg else ''
                )
                ts_html = (
                    f" <span style='color:#9ca3af;font-size:11px;'>[{ts}]</span>"
                    if ts else ''
                )
                lines.append(
                    "<div style='margin-top:3px;'>"
                    f"<span style='color:#b91c1c;font-weight:600;'>• {_escape_html(code)}</span>"
                    f"{msg_html}{ts_html}</div>"
                )
            new_alarms_html = "".join(lines)
        if new_alarms_html != self._laf_alarms_html:
            self._laf_alarms_html = new_alarms_html
            self.laf_alarms_lbl.setText(new_alarms_html)

    def _build_laf_value_chip(self, sensor: dict, reading: dict | None) -> QFrame:
        """Tek bir LAF sensörü için küçük değer kutusu (label + value).
        chip._val_lbl ve chip._unit cache için attribute olarak saklanır;
        sonraki refresh'lerde _update_laf_chip_value bunları kullanarak
        chip'i widget yeniden inşa etmeden günceller.
        """
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background:#f9fafb; border:1px solid #e5e7eb;"
            " border-radius:8px; padding:6px 8px; }"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(0)

        name = str(sensor.get('label') or sensor.get('name') or '?')
        unit = str(sensor.get('unit') or '').strip()

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            "color:#6b7280;font-size:11px;font-weight:500;"
        )
        lay.addWidget(name_lbl)

        val_lbl = QLabel()
        val_lbl.setTextFormat(Qt.RichText)
        lay.addWidget(val_lbl)

        # Cache attribute'ları (diff-update için)
        frame._val_lbl = val_lbl
        frame._unit = unit
        frame._last_value_html = None

        self._update_laf_chip_value(frame, reading, unit)
        return frame

    def _push_laf_overlay(self, sensors: list, latest: dict, chips_changed: bool):
        """GLB viewer üzerine LAF sensör chip'lerini DOM olarak push eder.

        chips_changed=True ise tüm liste yeniden oluşturulur (setLafSensors);
        aksi halde sadece değişen değerler updateLafValue ile güncellenir.
        Three.js sahnesine hiç dokunulmaz → GLB titremesi/yeniden yükleme yok.
        """
        if not hasattr(self, 'viewer') or self.viewer is None:
            return
        try:
            if chips_changed:
                payload = []
                for s in sensors:
                    sid = s['id']
                    val_str, unit_str = self._format_laf_overlay_value(
                        latest.get(sid), s.get('unit')
                    )
                    payload.append({
                        'id': sid,
                        'label': s.get('label') or s.get('name') or f'Sensör {sid}',
                        'unit': unit_str,
                        'value': val_str,
                        # Pozisyon: DB'de yoksa None → JS default (sağ üst köşe sıralı)
                        'xPct': s.get('overview_x'),
                        'yPct': s.get('overview_y'),
                    })
                self.viewer.set_laf_overlay(payload)
                self._last_overlay_key = tuple(
                    (s['id'], s.get('label') or '', s.get('unit') or '')
                    for s in sensors
                )
                # İlk push sonrası value cache'i de doldur (gereksiz tekrar push olmasın).
                self._last_overlay_values = {
                    s['id']: self._format_laf_overlay_value(
                        latest.get(s['id']), s.get('unit')
                    )[0]
                    for s in sensors
                }
                return
            # Diff: sadece değişen değerler
            for s in sensors:
                sid = s['id']
                val_str, unit_str = self._format_laf_overlay_value(
                    latest.get(sid), s.get('unit')
                )
                if self._last_overlay_values.get(sid) == val_str:
                    continue
                self._last_overlay_values[sid] = val_str
                self.viewer.update_laf_value(sid, val_str, unit_str)
        except Exception:
            import traceback; traceback.print_exc()

    @staticmethod
    def _format_laf_overlay_value(reading: dict | None, unit: str | None):
        """— / 0.00 vb. uniform string çıktı + temizlenmiş unit."""
        u = (unit or '').strip()
        if reading is None or reading.get('value') is None:
            return '—', u
        try:
            v = float(reading['value'])
            return f"{v:.2f}", u
        except (TypeError, ValueError):
            return str(reading.get('value')), u

    @staticmethod
    def _update_laf_chip_value(chip: QFrame, reading: dict | None, unit: str | None = None):
        """Var olan chip'in değer label'ını yerinde günceller — widget yeniden
        oluşturulmaz, layout invalidation tetiklenmez."""
        if not hasattr(chip, '_val_lbl'):
            return
        u = unit if unit is not None else getattr(chip, '_unit', '') or ''
        if reading is None or reading.get('value') is None:
            val_text = "—"
            val_color = "#9ca3af"
        else:
            try:
                v = float(reading['value'])
                val_text = f"{v:.2f}"
            except (TypeError, ValueError):
                val_text = str(reading.get('value'))
            val_color = "#111827"
        suffix = f" <span style='color:#6b7280;font-size:11px;'>{u}</span>" if u else ''
        html = (
            f"<span style='color:{val_color};font-weight:700;font-size:15px;'>"
            f"{val_text}</span>{suffix}"
        )
        # Diff: aynı HTML ise setText çağırma (re-layout önlenir).
        if getattr(chip, '_last_value_html', None) == html:
            return
        chip._last_value_html = html
        chip._val_lbl.setText(html)

    def refresh_glt_devices(self):
        """GLT ana ekranındaki cihaz kartlarını (DeviceCard) burada da göster.
        Karta tıklandığında `glt_card_clicked` sinyali fırlatılır → MainWindow
        outer_tabs'i GLT'ye + glt_tabs'i ESP-NOW ana sekmesine geçirir.

        Cihaz filtresi GLT ana ekranıyla aynı: esp_now_control.device_cards
        (HELLO/STREAM ile onaylanmış cihazlar) — ham slave_devices listesinden
        bu set'le filtreleniyor. Aksi halde etraftaki başka ESP cihazları
        burada görünür ama GLT ana ekranda görünmez (tutarsızlık).
        """
        devices = []
        if self.esp32 is not None:
            try:
                devices = list(getattr(self.esp32, 'slave_devices', []) or [])
            except Exception:
                devices = []

        # GLT ana ekran ile aynı filtre: yalnız onaylanmış cihazlar.
        if self.esp_now_control is not None:
            try:
                allowed = set(self.esp_now_control.device_cards.keys())
                devices = [d for d in devices if d.get('name') in allowed]
            except Exception:
                pass

        # Header summary
        if not devices:
            self.glt_summary.setText(
                "<span style='color:#6b7280;'>Şu an bağlı GLT cihazı yok.</span>"
            )
        else:
            connected = sum(
                1 for d in devices
                if str(d.get('status', '')).upper() in ('BAGLI', 'CONNECTED', 'OK')
            )
            self.glt_summary.setText(
                f"<b>{connected}</b> / {len(devices)} cihaz bağlı"
            )

        # Build/update cards
        live_names = set()
        # Faz-9: sağ kolon dar (260px), kart 220px → tek sütun.
        cols = 1
        for idx, d in enumerate(devices):
            name = str(d.get('name') or '').strip()
            mac = str(d.get('mac') or '').strip()
            if not name:
                continue
            live_names.add(name)
            status = str(d.get('status', '')).upper()
            connected = status in ('BAGLI', 'CONNECTED', 'OK')

            card = self._glt_cards.get(name)
            if card is None:
                card = DeviceCard(name, mac, self.auth, self.glt_grid_wrap)
                self._wire_glt_card_signals(card)
                r, c = divmod(idx, cols)
                self.glt_grid_layout.addWidget(card, r, c)
                self._glt_cards[name] = card
            else:
                # Yer değiştirebilir; mevcut layout'ta zaten ekli, sadece güncelle
                pass

            try:
                card.update_status(connected)
            except Exception:
                pass

        # Remove cards for devices that disappeared from the master list
        for stale in [n for n in self._glt_cards if n not in live_names]:
            w = self._glt_cards.pop(stale)
            w.setParent(None)
            w.deleteLater()

    # ── Slots ───────────────────────────────────────────────────
    def _on_viewer_ready(self):
        self.refresh_from_settings()

    def _on_model_loaded(self, door_count: int, port_count: int = 0,
                         meta_json: str = ''):
        # GLB değişmişse DB'deki kapı/port sayısını yeni model ile senkronize et
        # (BUG: yeni GLB yüklendiğinde oraps_door_labels/oraps_port_labels eski
        # satırlarla kalıyordu; port 15/16 'tıklanınca "bulunamadı" hatası).
        # meta_json: viewer'ın dış-yüzey bayrakları {"outer": {"1": true, ...}}
        # → yeni kapı satırlarının default görünürlüğü.
        outer_flags = None
        try:
            if meta_json:
                meta = json.loads(meta_json)
                raw = meta.get('outer') or {}
                outer_flags = {int(k): bool(v) for k, v in raw.items()}
        except Exception:
            outer_flags = None
        try:
            if door_count and door_count > 0:
                self.bm.reinit_doors_for_glb(int(door_count), outer_flags=outer_flags)
        except Exception as e:
            print(f"reinit_doors_for_glb failed: {e}")
        try:
            if port_count and port_count > 0:
                self.bm.reinit_ports_for_glb(int(port_count))
        except Exception as e:
            print(f"reinit_ports_for_glb failed: {e}")
        # Once meshes exist we can colour them according to active batch
        self.refresh_active_batch()
        # Kapı/port bilgi container'larını (chip) viewer'a bas.
        self._push_door_chips()
        self._push_port_chips()

    def _refresh_info_cards(self):
        self.refresh_laf_info()
        self.refresh_glt_devices()
        self.refresh_events()
        # Kapı/port ad etiketlerini (sprite) periyodik güncelle.
        self._push_door_chips()
        self._push_port_chips()
        # Faz-12/13 (bug 2026-08-03): GLT test sonuçları overview'a sinyal
        # OLMADAN farklı panelden (esp_now → batch_panel) DB'ye yazılıyor.
        # 3D renkler periyodik güncellenirken batch kartı sayacı ("X geçti")
        # ve "ORABS'a Geç" butonu yalnız batch olaylarında tazeleniyordu →
        # bayat kalıyordu. Port durumu DEĞİŞTİYSE kartı tazele; değişmediyse
        # dokunma (viewer'a gereksiz apply_door_states çağrısı olmasın).
        try:
            _snap = self._batch_member_port_status()
        except Exception:
            _snap = {}
        if _snap != getattr(self, '_last_port_status_snap', None):
            self._last_port_status_snap = _snap
            try:
                self.refresh_active_batch()
            except Exception:
                pass

    # ── Kapı / Port 3D ad etiketleri (sprite, Faz-5) ─────────────
    @staticmethod
    def _label_offset(row) -> dict | None:
        """DB satırındaki overview_x/y/z → sprite dünya-ofseti (yoksa None)."""
        ox, oy, oz = row.get('overview_x'), row.get('overview_y'), row.get('overview_z')
        if ox is None or oy is None or oz is None:
            return None
        return {'x': float(ox), 'y': float(oy), 'z': float(oz)}

    def _active_barrier_door_set(self) -> set[int]:
        """Şu an BLOKE (state=1) olan bariyerlerin bağlı kapı indekslerinin
        birleşimi. Kaynak: canlı `_barrier_states` cache (bridge sinyalinden
        gelir). Audit tablosundan değil — çünkü audit'te eski state=1 event
        kalırsa gerçek DI 0'a düşse bile turuncu görünürdü. Cache boş →
        hiçbir bariyer aktif değil (kullanıcı istediği davranış)."""
        active_bids = [bid for bid, st in self._barrier_states.items()
                       if int(st) == 1]
        if not active_bids:
            return set()
        try:
            barriers = {int(b['id']): b for b in self.bm.list_barriers()}
        except Exception:
            barriers = {}
        result: set[int] = set()
        for bid in active_bids:
            b = barriers.get(bid)
            if not b:
                continue
            for d in (b.get('door_indices') or []):
                try:
                    result.add(int(d))
                except (TypeError, ValueError):
                    pass
        return result

    def _push_door_chips(self):
        """Kapı 3D ad etiketlerini viewer'a bas. YALNIZCA adı olan (kullanıcı
        isimlendirmiş) kapılar gösterilir; renk aktif batch/DI/bariyer
        durumuna göre."""
        if not hasattr(self, 'viewer') or self.viewer is None:
            return
        try:
            labels = self.bm.get_door_labels()
        except Exception:
            return
        ab = self.bm.get_active_batch()
        states: dict[str, str] = {}
        if ab and ab.get('status') in ('running', 'paused'):
            states.update(ab.get('door_states', {}) or {})
        for door_idx, val in self._door_sensor_states.items():
            if int(val) == 1:
                states[str(door_idx)] = 'sensor_open'
        # Aktif bariyer bağlı kapılar → 'barrier' (üzerine yazar)
        _bset = self._active_barrier_door_set()
        for d in _bset:
            states[str(d)] = 'barrier'
        items = []
        for d in labels:
            idx = int(d['door_index'])
            label = (d.get('label') or '').strip()
            if not label:
                continue   # isimsiz kapı → sprite yok
            # Kullanıcı bu kapı için etiketi gizlemiş → toptan toggle
            # açık olsa bile gösterme.
            if int(d.get('show_label', 1) or 0) == 0:
                continue
            st = states.get(str(idx))
            if st == 'barrier':
                state, sub = 'barrier', 'Bariyer aktif'
            elif st == 'sensor_open':
                state, sub = 'sensor', 'Sensör açık'
            elif st == 'open':
                state, sub = 'open', 'Açık'
            elif st == 'locked':
                state, sub = 'locked', 'Kilitli'
            else:
                state, sub = 'neutral', ''
            items.append({
                'index': idx,
                'label': label,
                'state': state,
                'sub': sub,
                'offset': self._label_offset(d),
            })
        try:
            self.viewer.set_door_name_labels(items)
            if hasattr(self, 'door_labels_btn'):
                self.viewer.set_labels_visible(self.door_labels_btn.isChecked())
        except Exception:
            import traceback; traceback.print_exc()

    def _batch_member_port_status(self) -> dict:
        """Aktif ORABS batch'e bağlı GLT batch'inin portlarını ORABS
        port_index → batch_ports.status ('PENDING'|'PASS'|'FAIL') dict'ine
        çevirir. Bağlı GLT batch yoksa boş döner.

        Köprü: `batch_ports.port_id` → `glove_ports.rfid_tag` → ORABS
        `oraps_port_labels.rfid_tag` → `port_index`.
        `batch_ports.rfid_tag` başlangıçta NULL olduğu için ORİJİNAL şablon
        RFID'sini `glove_ports.rfid_tag`'ten alıyoruz.
        """
        try:
            ab = self.bm.get_active_batch()
        except Exception:
            ab = None
        if not ab or ab.get('status') not in ('running', 'paused'):
            return {}
        try:
            glt_active = self.db.find_active_linked_glt_batch(1)
        except Exception:
            glt_active = None
        if not glt_active:
            return {}
        # RFID → status eşlemesi (tek SQL, batch_ports + glove_ports JOIN).
        tag_to_status: dict = {}
        try:
            from core.database import normalize_rfid as _nrfid
        except Exception:
            _nrfid = lambda t: str(t or '').strip().upper()
        try:
            conn = self.db.connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    'SELECT gp.rfid_tag, bp.status '
                    'FROM batch_ports bp '
                    'JOIN glove_ports gp ON gp.id = bp.port_id '
                    'WHERE bp.batch_id = ?',
                    (int(glt_active['id']),)
                )
                for row in cur.fetchall():
                    tag = _nrfid(row[0]) if row[0] else ''
                    st = (row[1] or 'PENDING').strip().upper()
                    if tag:
                        # Aynı RFID birden fazla satırda ise en son status'u
                        # koru (PASS/FAIL, PENDING'e tercih edilir).
                        prev = tag_to_status.get(tag)
                        if prev is None or (prev == 'PENDING' and st != 'PENDING'):
                            tag_to_status[tag] = st
            finally:
                self.db.close()
        except Exception:
            import traceback; traceback.print_exc()
            return {}
        if not tag_to_status:
            return {}
        # RFID → ORABS port_index (cache).
        if self._rfid_to_port is None:
            self._rfid_to_port = self._build_rfid_cache()
        result: dict = {}
        for pidx_tag, st in tag_to_status.items():
            pidx = None
            for cache_tag, cache_idx in self._rfid_to_port.items():
                if _nrfid(cache_tag) == pidx_tag:
                    pidx = cache_idx
                    break
            if pidx:
                result[int(pidx)] = st
        return result

    def _batch_member_port_indices(self) -> set:
        """Geriye dönük uyum: sadece port_index setini döner (status'suz)."""
        return set(self._batch_member_port_status().keys())

    def _push_port_chips(self):
        """Port 3D ad etiketlerini viewer'a bas. YALNIZCA adı olan portlar
        gösterilir; doluluk + batch üyeliği bilgisiyle. Aktif ORABS batch'e
        bağlı GLT batch'inde tanımlı portlar 'batch' state ile mor renkte."""
        if not hasattr(self, 'viewer') or self.viewer is None:
            return
        try:
            labels = self.bm.get_port_labels()
        except Exception:
            return
        try:
            occ = self.bm.get_port_occupancy()
        except Exception:
            occ = {}
        batch_status = self._batch_member_port_status()   # {port_index: 'PENDING'|'PASS'|'FAIL'}
        items = []
        mesh_states: dict[str, str] = {}
        for p in labels:
            idx = int(p['port_index'])
            label = (p.get('label') or '').strip()
            if not label:
                continue   # isimsiz port → sprite yok
            # Kullanıcı bu port için etiketi gizlemiş → toptan toggle
            # açık olsa bile gösterme.
            if int(p.get('show_label', 1) or 0) == 0:
                continue
            o = occ.get(idx, {})
            is_occ = int(o.get('is_occupied', p.get('is_occupied', 0)) or 0) == 1
            bst = batch_status.get(idx)   # None ise batch üyesi değil
            is_motion = idx in self._barrier_motion_ports
            # Sprite state öncelik:
            #   motion (kısa hold) > PASS/FAIL > PENDING (batch+eldiven) >
            #   occupied > empty
            if is_motion:
                state = 'motion'
                sub = '🚶 Hareket'
            elif bst == 'PASS':
                state = 'pass'
                sub = '✓ Test geçti'
            elif bst == 'FAIL':
                state = 'fail'
                sub = '✗ Test başarısız'
            elif bst == 'PENDING' and is_occ:
                state = 'batch'
                sub = '🧤 Eldiven takılı'
            elif is_occ:
                state = 'occupied'
                sub = ''
            else:
                # PENDING+boş dahil: default gri, batch üyeliği vurgulanmaz.
                state = 'empty'
                sub = ''
            items.append({
                'index': idx,
                'label': label,
                'state': state,
                'sub': sub,
                'offset': self._label_offset(p),
            })
            # 3D mesh boyaması: tüm state'ler mesh'e yansıtılsın.
            mesh_states[str(idx)] = state
        try:
            self.viewer.set_port_name_labels(items)
            if hasattr(self, 'door_labels_btn'):
                self.viewer.set_labels_visible(self.door_labels_btn.isChecked())
        except Exception:
            import traceback; traceback.print_exc()
        # Batch üyesi portlar için 3D mesh rengini de mor'a çevir.
        if mesh_states:
            try:
                self.viewer.apply_port_states(mesh_states)
            except Exception:
                pass

    def _on_door_labels_toggled(self, checked: bool):
        """🏷 Ad Etiketleri butonu → 3D kapı+port ad etiketlerini göster/gizle."""
        try:
            self.viewer.set_labels_visible(bool(checked))
        except Exception:
            pass

    def _on_door_position_changed(self, door_index: int, dx: float, dy: float, dz: float):
        """Kapı ad etiketi sürüklenince DB'ye 3D ofseti kaydet."""
        try:
            self.db.update_door_position(int(door_index), float(dx), float(dy), float(dz))
        except Exception:
            import traceback; traceback.print_exc()

    def _on_port_position_changed(self, port_index: int, dx: float, dy: float, dz: float):
        """Port ad etiketi sürüklenince DB'ye 3D ofseti kaydet."""
        try:
            self.db.update_port_position(int(port_index), float(dx), float(dy), float(dz))
        except Exception:
            import traceback; traceback.print_exc()

    # ── Son Olaylar (Faz 7) ─────────────────────────────────────
    # Aksiyon tipi → (severity, ikon, kısa Türkçe etiket).
    # Faz-8: liste sadece kritik olaylar değil, ORAPS kategorisindeki TÜM
    # audit satırlarını gösterir (port motion, batch, bariyer keşfi vs.).
    # Bilinmeyen action_type için fallback (icon '•', label=action_type).
    _EVENT_WHITELIST = {
        # Kritik (kırmızı) — Faz-13: alarm kodları etikete eklendi.
        'DOOR_FORCED':              ('crit', '🚨', 'KP-03 Kilitli kapı açıldı'),
        'DOOR_FORCED_CLOSED':       ('warn', '🔒', 'KP-04 Kilitli kapı kapatıldı'),
        'DOOR_OPENED':              ('info', '🚪', 'KP-01 Kapı açıldı'),
        'DOOR_CLOSED':              ('info', '🚪', 'KP-02 Kapı kapatıldı'),
        'BARRIER_TRIGGERED':        ('crit', '⚡', 'IB-01 Işık bariyeri'),
        'BATCH_INTERLOCK_TRIPPED':  ('crit', '🛑', 'IB-02 Otomatik durdurma'),
        'MACHINE_STOP_TRIGGERED':   ('crit', '🛑', 'MS Makine durdurma'),
        'MACHINE_STOP_CLEARED':     ('info', '✅', 'MS-02 Durdurma temizlendi'),
        'LAF_ALARM':                ('crit', '🔴', 'LF-01 LAF alarm'),
        'LAF_ALARM_CLEAR':          ('info', '🟢', 'LF-02 LAF alarm temizlendi'),
        'LAF_ALARM_RAISED':         ('crit', '🔴', 'LF-01 LAF alarm'),
        'LAF_ALARM_CLEARED':        ('info', '🟢', 'LF-02 LAF alarm sona erdi'),
        'ESTOP_TRIGGERED':          ('crit', '🛑', 'AS-01 ACİL STOP BASILDI'),
        'ESTOP_RELEASED':           ('info', '✅', 'AS-02 Acil stop serbest'),
        'AI_ALARM_HIGH':            ('crit', '📈', 'AI-01 Yüksek eşik'),
        'AI_ALARM_LOW':             ('crit', '📉', 'AI-02 Düşük eşik'),
        'AI_ALARM_OK':              ('info', '✅', 'AI-03 Normale döndü'),
        # Uyarı (sarı)
        'BATCH_PAUSED':             ('warn', '⏸', 'BT-01 Batch durdu'),
        'BARRIER_LOW_BATTERY':      ('warn', '🔋', 'PT-03 Bariyer pili düşük'),
        # Info (mavi)
        'BATCH_STARTED':            ('info', '▶', 'Batch başladı'),
        'BATCH_RESUMED':            ('info', '▶', 'BT-02 Batch devam'),
        'BATCH_FINISHED':           ('info', '✓', 'Batch bitti'),
        'PORT_MOTION':              ('info', '🟦', 'PT-01 Port hareketi'),
        'PORT_MOTION_END':          ('info', '⬜', 'PT-02 Port hareketi sona erdi'),
        'BARRIER_DISCOVERED':       ('info', '📡', 'PT-04 Yeni bariyer'),
    }
    _SEV_COLOR = {
        'crit': '#b91c1c',
        'warn': '#92400e',
        'info': '#1d4ed8',
    }

    def refresh_events(self):
        """Son 24 saatin audit kayıtlarından kritik olayları kompakt listeler.
        Diff'li: HTML aynıysa setText çağrılmaz (LAF chip mantığıyla aynı)."""
        from datetime import datetime, timedelta
        try:
            now = datetime.now()
            since = (now - timedelta(hours=24)).isoformat()
            records = self.audit.get_audit_trail({
                'date_from': since,
                'date_to': now.isoformat(),
            }) or []
        except Exception:
            records = []

        # ORAPS kategorisindeki tüm audit satırları — en son 8 tanesi.
        # Bilinmeyen action_type'lar için fallback ikon (below) devrededir,
        # yani gelecekte eklenen yeni ORAPS event'leri otomatik listelenir.
        filtered = []
        for r in records:
            cat = (r.get('category') or '').upper()
            at = r.get('action_type') or ''
            if cat == 'ORAPS' or at in self._EVENT_WHITELIST:
                filtered.append(r)
            if len(filtered) >= 8:
                break

        if not filtered:
            new_html = (
                "<span style='color:#9ca3af;font-size:16px;'>"
                "Son 24 saatte olay yok.</span>"
            )
        else:
            lines = []
            for r in filtered:
                at = r.get('action_type') or ''
                sev, icon, label = self._EVENT_WHITELIST.get(
                    at, ('info', '•', at)
                )
                color = self._SEV_COLOR.get(sev, '#374151')
                ts = str(r.get('timestamp') or '')[11:19]  # HH:MM:SS
                desc = _strip_code_prefix(
                    str(r.get('description') or '').strip())
                desc_html = (
                    f" <span style='color:#6b7280;'>{_escape_html(desc[:60])}</span>"
                    if desc else ''
                )
                ts_html = (
                    f" <span style='color:#9ca3af;font-size:14px;'>[{ts}]</span>"
                    if ts else ''
                )
                lines.append(
                    "<div style='margin:1px 0;'>"
                    f"<span style='color:{color};font-weight:600;'>"
                    f"{icon} {label}</span>{desc_html}{ts_html}</div>"
                )
            new_html = "".join(lines)

        # Diff check — aynı HTML ise dokunma (re-layout önlenir).
        if new_html != self._events_html:
            self._events_html = new_html
            self.events_lbl.setText(new_html)

        # Aktif alarm banner'ı da güncelle (refresh_events sonrası).
        self.refresh_active_alarms()

    # ── Aktif alarm banner (Faz-7 uzantısı) ─────────────────────
    _CRITICAL_ACTIONS = ('DOOR_FORCED', 'BARRIER_TRIGGERED', 'ESTOP_TRIGGERED')
    _CRITICAL_WINDOW_SEC = 300   # tek atımlık olay son 5 dakika içindeyse aktif

    def _collect_active_alarms(self) -> list[dict]:
        """Şu an aktif sayılan alarmları döner. Her item: {'id','icon',
        'label','severity','key'}. 'key' dismiss için stabil (audit_id ya da
        laf:sensor_id:code)."""
        from datetime import datetime, timedelta
        items: list[dict] = []
        # 1) LAF aktif alarmlar — cleared gelene kadar aktif.
        try:
            for a in self.laf.list_active_alarms() or []:
                code = str(a.get('code') or a.get('alarm_code') or '')
                sid = a.get('sensor_id') or a.get('id') or 0
                key = f"laf:{sid}:{code}"
                if key in self._ack_laf_codes:
                    continue
                name = a.get('sensor_label') or a.get('sensor_name') or f"Sensör {sid}"
                msg = (a.get('message') or code or 'LAF alarm').strip()
                items.append({
                    'key': key,
                    'icon': '🔴',
                    'label': f"LAF · {name}: {msg}",
                })
        except Exception:
            pass
        # 2) Son 5 dakikadaki kritik audit olayları (DOOR_FORCED, BARRIER_TRIGGERED).
        try:
            now = datetime.now()
            since = (now - timedelta(seconds=self._CRITICAL_WINDOW_SEC)).isoformat()
            records = self.audit.get_audit_trail({
                'date_from': since,
                'date_to': now.isoformat(),
            }) or []
        except Exception:
            records = []
        # Makine durdurma (durdurma kapağı açık) — yalnız EN SON MS olayı
        # belirleyicidir: kayıtlar yeni→eski geldiği için ilk görülen MS
        # kaydı son durumdur. TRIGGERED ise ışık bariyeri gibi banner'da
        # yanar; kapaklar kapanıp CLEARED gelince otomatik söner.
        _ms_handled = False
        for r in records:
            at = str(r.get('action_type') or '')
            if at in ('MACHINE_STOP_TRIGGERED', 'MACHINE_STOP_CLEARED'):
                if _ms_handled:
                    continue          # daha yeni bir MS kaydı zaten işlendi
                _ms_handled = True
                if at == 'MACHINE_STOP_CLEARED':
                    continue          # kapaklar kapalı → alarm yok
                # TRIGGERED → ortak kritik-alarm akışına düş
            elif at not in self._CRITICAL_ACTIONS:
                continue
            rid = r.get('id')
            if rid in self._ack_audit_ids:
                continue
            info = self._EVENT_WHITELIST.get(at, ('crit', '🚨', at))
            _, icon, label = info
            desc = _strip_code_prefix(
                str(r.get('description') or '').strip())
            items.append({
                'key': f"audit:{rid}",
                'icon': icon,
                'label': f"{label}" + (f" · {desc[:80]}" if desc else ''),
                'audit_id': rid,
            })
        # 3) Acil stop canlı durumu (bridge cache — dismiss edilemez,
        # fiziksel buton serbest bırakılınca otomatik temizlenir).
        if getattr(self, '_estop_active', False):
            items.append({
                'key': 'estop:active',
                'icon': '🛑',
                'label': 'ACİL STOP BASILDI — Butonu serbest bırakın!',
            })
        return items

    def refresh_active_alarms(self):
        """Aktif alarmları derle → üst şeriti göster/gizle. Diff'li."""
        try:
            items = self._collect_active_alarms()
        except Exception:
            items = []
        # Buzzer DO: banner yanıkken 1, sönük/onaylanmışken 0. Bridge
        # değeri cache'ler — değişmedikçe Modbus'a yazmaz; diff-return'den
        # ÖNCE çağrılır ki reconnect sonrası durum da tazelensin.
        try:
            bridge = getattr(self, '_io_bridge', None)
            if bridge is not None and hasattr(bridge, 'set_alarm_buzzer'):
                bridge.set_alarm_buzzer(bool(items))
        except Exception:
            pass
        # Anahtar (dismiss/geldi-gitti) diff için.
        key = tuple(sorted(i['key'] for i in items))
        if key == self._banner_key:
            return
        self._banner_key = key
        if not items:
            self.alarm_banner.setVisible(False)
            if self._alarm_blink_timer.isActive():
                self._alarm_blink_timer.stop()
            self._banner_active_keys = []
            return
        # Aktif key'leri Ack butonu için sakla.
        self._banner_active_keys = [i['key'] for i in items]
        parts = [f"{i['icon']} {_escape_html(i['label'])}" for i in items[:3]]
        more = len(items) - 3
        html = " &nbsp;·&nbsp; ".join(parts)
        if more > 0:
            html += f" &nbsp;<span style='opacity:0.85;'>(+{more} daha)</span>"
        self.alarm_banner_lbl.setText(html)
        self.alarm_banner.setVisible(True)
        if not self._alarm_blink_timer.isActive():
            self._alarm_blink_timer.start()

    def _toggle_alarm_blink(self):
        """Banner arka planını 600ms'de bir toggle et (yanıp sönme)."""
        self._banner_blink_state = not self._banner_blink_state
        bg = '#7f1d1d' if self._banner_blink_state else '#dc2626'
        self.alarm_banner.setStyleSheet(
            f"QFrame {{ background:{bg}; border:2px solid #7f1d1d;"
            " border-radius:6px; }"
        )

    def _on_alarm_ack(self):
        """Operatör 'Tamam' → şu anda aktif tüm alarmları session-lokal onayla.
        Audit'e ALARM_ACKED düşer; tekrar tetiklenirse yeniden görünür."""
        keys = list(getattr(self, '_banner_active_keys', []) or [])
        if not keys:
            return
        acked_count = 0
        for k in keys:
            if k.startswith('audit:'):
                try:
                    rid = int(k.split(':', 1)[1])
                    self._ack_audit_ids.add(rid)
                    acked_count += 1
                except Exception:
                    pass
            elif k.startswith('laf:'):
                self._ack_laf_codes.add(k)
                acked_count += 1
        if acked_count and self.audit is not None:
            try:
                self.audit.log_action(
                    action_type='ALARM_ACKED',
                    table_name='audit_trail',
                    description=f"Operatör aktif alarm(lar)ı onayladı ({acked_count} adet).",
                    new_value=','.join(keys),
                    category='ORAPS',
                )
            except Exception:
                pass
        # Cache invalidate → refresh_active_alarms yeniden hesaplayıp gizler.
        self._banner_key = None
        self.refresh_active_alarms()

    def apply_role_visibility(self):
        """Operator için header'daki admin-only mod butonlarını gizle:
        RFID Eşleme, Kapı Eşleme, Yerleşim Modu. Ad Etiketleri Operator'da
        da görünür kalır. Login sonrasında oraps_main.on_login_complete
        tarafından çağrılır."""
        try:
            can_manage = self._can_pick_modes()   # Admin/Supervisor
        except Exception:
            can_manage = False
        for btn_name in ('pick_mode_btn', 'door_pick_btn', 'layout_mode_btn',
                         'barrier_pair_btn', 'rotate_btn'):
            btn = getattr(self, btn_name, None)
            if btn is None:
                continue
            # Operator (can_manage=False) → gizle, aktif ise kapat.
            btn.setVisible(can_manage)
            if not can_manage and hasattr(btn, 'isChecked') and btn.isChecked():
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)
                # Viewer tarafında da modu kapat (varsa).
                try:
                    if btn_name in ('pick_mode_btn', 'door_pick_btn',
                                    'barrier_pair_btn'):
                        self.viewer.set_pick_mode('')
                    elif btn_name == 'rotate_btn':
                        self.viewer.set_rotate_enabled(False)
                    else:
                        self.viewer.set_layout_edit_mode(False)
                except Exception:
                    pass
        # Rotate butonu her zaman "sadece pick modu açıkken" görünsün —
        # yetki verilse bile pick modu yoksa gizle.
        if hasattr(self, 'rotate_btn'):
            self._update_rotate_btn_visibility()

    def _on_glt_card_clicked(self, device_name: str):
        """Fallback (esp_now_control yoksa): MainWindow GLT ana sekmesine geçer."""
        self.glt_card_clicked.emit(device_name)

    def _wire_glt_card_signals(self, card):
        """Faz 4a — ORABS Overview'daki GLT kartının tüm sinyallerini doğrudan
        esp_now_control'ün handler'larına bağla. Operator hiç sekme
        değiştirmeden tüm cihaz işlemlerini (detay dialog, settings, RFID,
        port, test komutları, sync) ORABS Overview'dan yapabilir.

        esp_now_control referansı yoksa fallback: clicked → GLT sekmesine geç.
        """
        if self.esp_now_control is None:
            try:
                card.clicked.connect(self._on_glt_card_clicked)
            except Exception:
                pass
            return
        ec = self.esp_now_control
        # (sinyal_adı, handler) — eksik olanlar sessizce geçilir.
        wiring = (
            ('device_selected',       getattr(ec, 'on_device_selected', None)),
            ('settings_clicked',      getattr(ec, 'on_device_settings_clicked', None)),
            ('rfid_clicked',          getattr(ec, 'on_rfid_clicked', None)),
            ('register_port_clicked', getattr(ec, 'on_register_port_clicked', None)),
            ('test_start_clicked',    getattr(ec, 'on_device_test_start', None)),
            ('test_dismount_clicked', getattr(ec, 'on_device_dismount', None)),
            ('test_abort_clicked',    getattr(ec, 'on_device_test_abort', None)),
            ('test_mount_clicked',    getattr(ec, 'on_device_mount', None)),
            ('sync_clicked',          getattr(ec, '_on_manual_sync_clicked', None)),
        )
        for sig_name, handler in wiring:
            if handler is None:
                continue
            sig = getattr(card, sig_name, None)
            if sig is None:
                continue
            try:
                sig.connect(handler)
            except Exception:
                pass

    # ── RFID eşleme modu ───────────────────────────────
    def _is_admin(self) -> bool:
        try:
            return self.auth.get_current_user_role() == 'Admin'
        except Exception:
            return False

    def _can_pick_modes(self) -> bool:
        """RFID ve Kapı eşleme modlarını admin veya supervisor açabilir."""
        try:
            return self.auth.get_current_user_role() in ('Admin', 'Supervisor')
        except Exception:
            return False

    def _on_pick_mode_toggled(self, checked: bool):
        if checked and not self._can_pick_modes():
            QMessageBox.warning(
                self, "Yetki Gerekli",
                "RFID eşleme modunu yalnızca admin veya supervisor açabilir."
            )
            self.pick_mode_btn.blockSignals(True)
            self.pick_mode_btn.setChecked(False)
            self.pick_mode_btn.blockSignals(False)
            return
        # Mutex: kapı modu, yerleşim modu veya bariyer eşleme modu açıksa kapat
        if checked and self.door_pick_btn.isChecked():
            self.door_pick_btn.blockSignals(True)
            self.door_pick_btn.setChecked(False)
            self.door_pick_btn.blockSignals(False)
        if checked and hasattr(self, 'layout_mode_btn') and self.layout_mode_btn.isChecked():
            self.layout_mode_btn.blockSignals(True)
            self.layout_mode_btn.setChecked(False)
            self.layout_mode_btn.blockSignals(False)
            try:
                self.viewer.set_layout_edit_mode(False)
            except Exception:
                pass
        if checked and getattr(self, 'barrier_pair_btn', None) is not None \
                and self.barrier_pair_btn.isChecked():
            self._cleanup_pairing(cancelled=True)
        try:
            self.viewer.set_pick_mode('port' if checked else '')
        except Exception:
            pass
        self._update_rotate_btn_visibility()

    def _on_door_pick_mode_toggled(self, checked: bool):
        if checked and not self._can_pick_modes():
            QMessageBox.warning(
                self, "Yetki Gerekli",
                "Kapı eşleme modunu yalnızca admin veya supervisor açabilir."
            )
            self.door_pick_btn.blockSignals(True)
            self.door_pick_btn.setChecked(False)
            self.door_pick_btn.blockSignals(False)
            return
        # Mutex: port modu, yerleşim modu veya bariyer eşleme modu açıksa kapat
        if checked and self.pick_mode_btn.isChecked():
            self.pick_mode_btn.blockSignals(True)
            self.pick_mode_btn.setChecked(False)
            self.pick_mode_btn.blockSignals(False)
        if checked and hasattr(self, 'layout_mode_btn') and self.layout_mode_btn.isChecked():
            self.layout_mode_btn.blockSignals(True)
            self.layout_mode_btn.setChecked(False)
            self.layout_mode_btn.blockSignals(False)
            try:
                self.viewer.set_layout_edit_mode(False)
            except Exception:
                pass
        if checked and getattr(self, 'barrier_pair_btn', None) is not None \
                and self.barrier_pair_btn.isChecked():
            self._cleanup_pairing(cancelled=True)
        try:
            self.viewer.set_pick_mode('door' if checked else '')
        except Exception:
            pass
        self._update_rotate_btn_visibility()

    def _on_layout_mode_toggled(self, checked: bool):
        """LAF chip drag-place modu aç/kapa. Admin/Supervisor yetkili."""
        if checked and not self._can_pick_modes():
            QMessageBox.warning(
                self, "Yetki Gerekli",
                "Yerleşim modunu yalnızca admin veya supervisor açabilir."
            )
            self.layout_mode_btn.blockSignals(True)
            self.layout_mode_btn.setChecked(False)
            self.layout_mode_btn.blockSignals(False)
            return
        # Mutex: pick mode'lar açıksa kapat
        if checked and self.pick_mode_btn.isChecked():
            self.pick_mode_btn.blockSignals(True)
            self.pick_mode_btn.setChecked(False)
            self.pick_mode_btn.blockSignals(False)
            try:
                self.viewer.set_pick_mode('')
            except Exception:
                pass
        if checked and self.door_pick_btn.isChecked():
            self.door_pick_btn.blockSignals(True)
            self.door_pick_btn.setChecked(False)
            self.door_pick_btn.blockSignals(False)
            try:
                self.viewer.set_pick_mode('')
            except Exception:
                pass
        if checked and getattr(self, 'barrier_pair_btn', None) is not None \
                and self.barrier_pair_btn.isChecked():
            # Bariyer eşleme akışını iptal ederek kapat.
            self._cleanup_pairing(cancelled=True)
        try:
            self.viewer.set_layout_edit_mode(checked)
        except Exception:
            pass

    def _on_rotate_toggled(self, checked: bool):
        """🔄 Döndür toggle → viewer'a rotate on/off gönder."""
        try:
            self.viewer.set_rotate_enabled(bool(checked))
        except Exception:
            pass

    def _update_rotate_btn_visibility(self):
        """RFID veya Kapı eşleme modu açıkken 🔄 Döndür butonu görünür,
        aksi halde gizli + toggle kapalı + rotate off."""
        try:
            visible = bool(
                self.pick_mode_btn.isChecked() or
                self.door_pick_btn.isChecked()
            )
        except Exception:
            visible = False
        self.rotate_btn.setVisible(visible)
        if not visible and self.rotate_btn.isChecked():
            self.rotate_btn.blockSignals(True)
            self.rotate_btn.setChecked(False)
            self.rotate_btn.blockSignals(False)
            try:
                self.viewer.set_rotate_enabled(False)
            except Exception:
                pass

    def _on_barrier_pair_mode_toggled(self, checked: bool):
        """Bariyer eşleme modu (Faz-7). Port'a tıkla → sensöre elini geçir."""
        if checked and not self._can_pick_modes():
            QMessageBox.warning(
                self, "Yetki Gerekli",
                "Bariyer eşleme modunu yalnızca admin veya supervisor açabilir."
            )
            self.barrier_pair_btn.blockSignals(True)
            self.barrier_pair_btn.setChecked(False)
            self.barrier_pair_btn.blockSignals(False)
            return
        if checked:
            # Mutex: diğer modları kapat
            for btn_name in ('pick_mode_btn', 'door_pick_btn', 'layout_mode_btn'):
                btn = getattr(self, btn_name, None)
                if btn is not None and btn.isChecked():
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)
                    if btn_name == 'layout_mode_btn':
                        try:
                            self.viewer.set_layout_edit_mode(False)
                        except Exception:
                            pass
            # 3D'de port pick etkin
            try:
                self.viewer.set_pick_mode('port')
            except Exception:
                pass
        else:
            # Kapatılıyor — devam eden bir pairing varsa iptal et.
            if getattr(self, '_pairing_wait_port', None) is not None:
                self._cleanup_pairing(cancelled=True)
            else:
                try:
                    self.viewer.set_pick_mode('')
                except Exception:
                    pass

    def _on_laf_position_changed(self, sensor_id: int, x_pct: float, y_pct: float):
        """Drag bitince JS çağırır → DB'ye yeni pozisyonu kaydet."""
        try:
            self.db.update_laf_sensor_position(int(sensor_id),
                                                float(x_pct), float(y_pct))
        except Exception:
            import traceback; traceback.print_exc()
        # Cache invalidate — sonraki refresh'te yeni pozisyonla setLafSensors çağrılır.
        self._last_overlay_key = None

    def _on_port_picked(self, port_index: int):
        """3D viewer'da bir glove port mesh'i tıklandı.

        Bariyer Eşleme Modu aktifse → bu port bir bariyer sensörüyle
        eşlenmek üzere bekleme moduna alınır (5 sn içinde bir sensör E1
        gönderirse otomatik bağlanır; timeout olursa manuel dialog).

        Aksi halde (varsayılan) → RFID picker açılır.
        """
        if not self._can_pick_modes():
            return
        # 1) Bariyer eşleme modu aktifse → pairing akışına gir.
        if getattr(self, 'barrier_pair_btn', None) is not None \
                and self.barrier_pair_btn.isChecked():
            self._start_barrier_pairing_for_port(port_index)
            return

        # 2) Varsayılan: RFID picker
        try:
            ports = {p['port_index']: p for p in self.bm.get_port_labels()}
        except Exception as e:
            QMessageBox.warning(self, "Port", f"Port bilgisi okunamadı:\n{e}")
            return
        port = ports.get(port_index)
        if not port:
            QMessageBox.warning(
                self, "Port", f"Port #{port_index} bulunamadı."
            )
            return
        try:
            rfids = self.bm.list_registered_glt_rfids()
        except Exception as e:
            QMessageBox.warning(self, "RFID", f"RFID listesi okunamadı:\n{e}")
            return
        dlg = _RfidPickerDialog(
            port_index=port_index,
            port_label=port.get('label') or '',
            current_rfid=port.get('rfid_tag') or '',
            rfids=rfids,
            parent=self,
            current_show_label=bool(int(port.get('show_label', 1) or 0)),
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        new_rfid = dlg.selected_rfid()  # '' → eşlemeyi kaldır
        new_label = dlg.selected_label()
        new_show = dlg.selected_show_label()
        try:
            kwargs = {'rfid_tag': new_rfid, 'show_label': 1 if new_show else 0}
            # Ad değiştiyse yaz (boş '' → adı kaldır/gizle de dahil).
            if new_label != (port.get('label') or ''):
                kwargs['label'] = new_label
            self.bm.update_port_label(port_index, **kwargs)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Eslem kaydedilemedi:\n{e}")
            return
        # Cache'i sıfırla — yeni eşleme bir sonraki RFID event'inde aktif olsun.
        self._invalidate_rfid_cache()
        # Ad etiketini anında yenile.
        self._push_port_chips()
        QMessageBox.information(
            self, "Eşleme Kaydedildi",
            f"Port #{port_index} ({new_label or '(adsız)'}) → "
            f"RFID: {new_rfid or '(temizlendi)'}"
        )

    # ── Bariyer eşleme akışı (Faz-7) ─────────────────────
    _BARRIER_PAIR_TIMEOUT_MS = 5000

    def _start_barrier_pairing_for_port(self, port_index: int):
        """Port'a tıklandı, bariyer eşleme akışı başlıyor: 5 sn içinde
        BROKEN event geldiyse otomatik bağla; yoksa manuel liste."""
        mw = self.window()   # MainWindow
        bmgr = getattr(mw, 'barrier_manager', None)
        if bmgr is None:
            QMessageBox.warning(
                self, "Bariyer",
                "Bariyer sistemi başlatılmamış — Ayarlar → 📡 Kablosuz Bariyer "
                "Sensörleri'nden manuel eşleyebilirsiniz."
            )
            return
        # State: hangi port için bekliyoruz + connect edilmiş sinyal
        self._pairing_wait_port = int(port_index)
        try:
            bmgr.set_pairing_mode(True)
        except Exception:
            pass
        try:
            bmgr.pairing_candidate.connect(self._on_pairing_candidate,
                                           type=Qt.UniqueConnection)
        except Exception:
            pass
        # Timeout timer
        if not hasattr(self, '_pairing_timeout_timer') or self._pairing_timeout_timer is None:
            self._pairing_timeout_timer = QTimer(self)
            self._pairing_timeout_timer.setSingleShot(True)
            self._pairing_timeout_timer.timeout.connect(
                self._on_pairing_timeout
            )
        self._pairing_timeout_timer.stop()
        self._pairing_timeout_timer.start(self._BARRIER_PAIR_TIMEOUT_MS)
        # Kullanıcıya bilgi (modeless: bilgi ver, kullanıcı sensöre gitsin)
        self._pairing_hint = QMessageBox(self)
        self._pairing_hint.setIcon(QMessageBox.Information)
        self._pairing_hint.setWindowTitle("Bariyer Eşleme")
        try:
            port_label = next(
                (p.get('label') or f"#{port_index}"
                 for p in self.bm.get_port_labels()
                 if int(p['port_index']) == int(port_index)),
                f"#{port_index}"
            )
        except Exception:
            port_label = f"#{port_index}"
        self._pairing_hint.setText(
            f"<b>Port {port_label}</b> için eşleme başlatıldı.<br><br>"
            f"Şimdi ilgili IR bariyer sensörünün önünden elinizi geçirin "
            f"(<b>{self._BARRIER_PAIR_TIMEOUT_MS // 1000} sn</b> içinde).<br><br>"
            "Timeout olursa manuel seçim açılacak."
        )
        self._pairing_hint.setStandardButtons(QMessageBox.Cancel)
        # Cancel → temizle
        self._pairing_hint.buttonClicked.connect(
            lambda _b: self._cleanup_pairing(cancelled=True)
        )
        self._pairing_hint.show()

    def _on_pairing_candidate(self, mac: str, sensor_id):
        """BarrierManager'dan pairing candidate geldi → onay dialog'u."""
        if not hasattr(self, '_pairing_wait_port') or self._pairing_wait_port is None:
            return
        port_index = int(self._pairing_wait_port)
        # Timer + hint dialog kapat
        try:
            self._pairing_timeout_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, '_pairing_hint', None) is not None:
                self._pairing_hint.close()
                self._pairing_hint = None
        except Exception:
            pass
        try:
            sensor = self.db.get_barrier_sensor_by_mac(mac) or {}
        except Exception:
            sensor = {}
        sid = int(sensor.get('id') or sensor_id or 0)
        s_label = sensor.get('label') or f"#{sid}"
        try:
            port_label = next(
                (p.get('label') or f"#{port_index}"
                 for p in self.bm.get_port_labels()
                 if int(p['port_index']) == int(port_index)),
                f"#{port_index}"
            )
        except Exception:
            port_label = f"#{port_index}"
        ans = QMessageBox.question(
            self, "Bariyer Tespit Edildi",
            f"<b>{s_label}</b> algılandı.<br><br>"
            f"Port <b>{port_label}</b> ile eşlensin mi?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if ans == QMessageBox.Yes:
            try:
                self.db.update_barrier_sensor(sid, port_index=port_index)
                QMessageBox.information(
                    self, "Eşleme Kaydedildi",
                    f"{s_label} → Port {port_label} eşlemesi kaydedildi."
                )
            except Exception as e:
                QMessageBox.critical(self, "Hata", str(e))
        self._cleanup_pairing()

    def _on_pairing_timeout(self):
        """5 sn içinde BROKEN event gelmedi → manuel liste fallback."""
        if not hasattr(self, '_pairing_wait_port') or self._pairing_wait_port is None:
            return
        port_index = int(self._pairing_wait_port)
        # Hint dialog kapat
        try:
            if getattr(self, '_pairing_hint', None) is not None:
                self._pairing_hint.close()
                self._pairing_hint = None
        except Exception:
            pass
        # Manuel seçim dialog'u
        try:
            sensors = self.db.list_barrier_sensors() or []
        except Exception:
            sensors = []
        if not sensors:
            QMessageBox.information(
                self, "Bariyer Eşleme",
                "Sistemde tanımlı bariyer sensörü yok. Sensöre 5V+3V verip "
                "en az bir E1 mesajı geldiğinde otomatik listelenir."
            )
            self._cleanup_pairing()
            return
        # Basit input dialog: sensör listesi
        from PyQt5.QtWidgets import QInputDialog
        options = []
        opt_ids = []
        for s in sensors:
            sid = int(s['id'])
            lbl = (s.get('label') or f'#{sid}').strip() or f'#{sid}'
            cur_p = s.get('port_index')
            suf = (f" (mevcut: Port {cur_p})" if cur_p else '')
            options.append(f"#{sid} · {lbl}{suf}")
            opt_ids.append(sid)
        options.append("— Vazgeç —")
        opt_ids.append(None)
        choice, ok = QInputDialog.getItem(
            self, "Bariyer Eşleme (Manuel)",
            "Sensör algılanmadı — listeden seçin:",
            options, 0, False
        )
        if not ok or choice == "— Vazgeç —":
            self._cleanup_pairing()
            return
        try:
            sid = opt_ids[options.index(choice)]
        except (ValueError, IndexError):
            sid = None
        if sid is not None:
            try:
                self.db.update_barrier_sensor(int(sid), port_index=port_index)
                QMessageBox.information(
                    self, "Eşleme Kaydedildi",
                    f"Sensör #{sid} → Port #{port_index} eşlemesi kaydedildi."
                )
            except Exception as e:
                QMessageBox.critical(self, "Hata", str(e))
        self._cleanup_pairing()

    def _cleanup_pairing(self, cancelled: bool = False):
        """Pairing state'i temizle: timer durdur, sinyal çöz, mod kapat."""
        self._pairing_wait_port = None
        try:
            self._pairing_timeout_timer.stop()
        except Exception:
            pass
        mw = self.window()
        bmgr = getattr(mw, 'barrier_manager', None)
        if bmgr is not None:
            try:
                bmgr.set_pairing_mode(False)
            except Exception:
                pass
            try:
                bmgr.pairing_candidate.disconnect(self._on_pairing_candidate)
            except Exception:
                pass
        # Eşleme modu butonunu kapat
        try:
            if getattr(self, 'barrier_pair_btn', None) is not None:
                self.barrier_pair_btn.blockSignals(True)
                self.barrier_pair_btn.setChecked(False)
                self.barrier_pair_btn.blockSignals(False)
        except Exception:
            pass
        try:
            self.viewer.set_pick_mode('')
        except Exception:
            pass

    # ── Kapı eşleme modu ───────────────────────────────
    def _on_door_picked(self, door_index: int):
        """3D viewer'da bir kapı tıklandı — isim + grup düzenleme dialog'u."""
        if not self._can_pick_modes():
            return
        try:
            doors = {d['door_index']: d for d in self.bm.get_door_labels()}
        except Exception as e:
            QMessageBox.warning(self, "Kapı", f"Kapı bilgisi okunamadı:\n{e}")
            return
        door = doors.get(door_index)
        if not door:
            QMessageBox.warning(
                self, "Kapı", f"Kapı #{door_index} bulunamadı."
            )
            return
        try:
            groups = self.bm.list_door_groups()
        except Exception as e:
            QMessageBox.warning(self, "Grup", f"Grup listesi okunamadı:\n{e}")
            groups = []
        dlg = _DoorEditDialog(
            door_index=door_index,
            current_label=door.get('label') or '',
            current_group_id=door.get('group_id'),
            groups=groups,
            bm=self.bm,
            parent=self,
            current_show_label=bool(int(door.get('show_label', 1) or 0)),
            current_stop_group_id=door.get('stop_group_id'),
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        new_label = dlg.selected_label()
        new_group_id = dlg.selected_group_id()  # None veya int
        new_stop_group_id = dlg.selected_stop_group_id()  # None veya int
        new_show = dlg.selected_show_label()
        try:
            self.bm.update_door_label(
                door_index, label=new_label, group_id=new_group_id,
                show_label=1 if new_show else 0,
                stop_group_id=new_stop_group_id,
            )
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Kapı kaydedilemedi:\n{e}")
            return
        try:
            self.refresh_active_batch()
        except Exception:
            pass
        # Grup adını mesajda göster
        gname = '(grupsuz)'
        if new_group_id is not None:
            for g in groups:
                if g.get('id') == new_group_id:
                    gname = g.get('name') or gname
                    break
            if gname == '(grupsuz)':
                # yeni grup oluşturulmuş olabilir; tekrar listele
                try:
                    for g in self.bm.list_door_groups():
                        if g.get('id') == new_group_id:
                            gname = g.get('name') or gname
                            break
                except Exception:
                    pass
        QMessageBox.information(
            self, "Kapı Kaydedildi",
            f"Kapı #{door_index} → '{new_label or '(adsız)'}' · Grup: {gname}"
        )

    # ── RFID → port renklendirme (GLT canlı veri köprüsü) ──────
    def _invalidate_rfid_cache(self):
        self._rfid_to_port = None

    def _build_rfid_cache(self) -> dict[str, int]:
        cache: dict[str, int] = {}
        try:
            for p in self.bm.get_port_labels():
                tag = (p.get('rfid_tag') or '').strip().upper()
                if tag and tag not in cache:
                    cache[tag] = int(p['port_index'])
        except Exception:
            pass
        return cache

    def on_rfid_state_changed(self, device_name: str, rfid_tag: str,
                              is_active: bool):
        """ESP-NOW panelinden RFID algılama/uzaklaşma bildirimi.

        Eşleşen ORAPS port mesh'ini 3D viewer'da yeşil ('occupied') yakar,
        RFID uzaklaşınca nötr renge döndürür. Eşleşme yoksa sessiz geç.
        """
        if self._rfid_to_port is None:
            self._rfid_to_port = self._build_rfid_cache()

        if is_active:
            tag = (rfid_tag or '').strip().upper()
            if not tag:
                return
            idx = self._rfid_to_port.get(tag)
            if not idx:
                return
            self._device_active_rfid[device_name] = tag
            try:
                self.viewer.apply_port_states({str(idx): 'occupied'})
            except Exception:
                pass
        else:
            # RFID uzaklaştırıldı — cihaz için en son aktif RFID'yi temizle.
            tag = self._device_active_rfid.pop(device_name, None)
            if not tag:
                return
            idx = self._rfid_to_port.get(tag)
            if not idx:
                return
            try:
                self.viewer.apply_port_states({str(idx): 'neutral'})
            except Exception:
                pass


def _escape_html(text: str) -> str:
    return (
        text.replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
    )


# Audit hook'unun açıklama başına eklediği "[KP-01]" tarzı alarm kodu
# öneki. Genel Bakış görünümünde etiket zaten kodu içerdiğinden çift
# görünmesin diye gösterimden önce temizlenir (audit kaydında korunur).
_CODE_PREFIX_RE = re.compile(r'^\s*\[[A-Z]{1,4}-?\d{0,3}\]\s*')


def _strip_code_prefix(text: str) -> str:
    return _CODE_PREFIX_RE.sub('', text or '')


class _RfidPickerDialog(QDialog):
    """ORAPS port'una GLT'de kayıtlı bir RFID atamak için seçici.

    Tablo: name | rfid_tag — kullanıcı bir satıra dokunup OK'a basar.
    'Eşlemeyi Temizle' butonu mevcut atamayı kaldırır (NULL yazar).
    """

    def __init__(self, port_index: int, port_label: str,
                 current_rfid: str, rfids: list, parent=None,
                 current_show_label: bool = True):
        super().__init__(parent)
        self.setWindowTitle(f"RFID Eşleme · Port #{port_index}")
        self.setMinimumSize(560, 480)
        self._rfids = list(rfids)
        self._chosen: str | None = current_rfid or None
        self._initial_label = port_label or f"Port {port_index}"
        self._initial_show_label = bool(current_show_label)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        hdr = QLabel(
            f"<b>{_escape_html(port_label)}</b> portuna atanacak RFID'yi seçin. "
            f"Mevcut: <b>{_escape_html(current_rfid) if current_rfid else '—'}</b>"
        )
        hdr.setTextFormat(Qt.RichText)
        hdr.setWordWrap(True)
        lay.addWidget(hdr)

        # Port adı (opsiyonel — boş bırakılırsa mevcut isim korunur değil,
        # mevcut isim line-edit'te zaten dolu gelir; kullanıcı isterse değiştirir).
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Port adı:"))
        self.label_edit = QLineEdit()
        self.label_edit.setText(self._initial_label)
        self.label_edit.setPlaceholderText("Örn: Eldiven 1 (Sol)")
        name_row.addWidget(self.label_edit, 1)
        lay.addLayout(name_row)

        # Etiket görünürlüğü (Faz-7): kullanıcı bu port için ad etiketini
        # toptan "Ad Etiketleri" toggle'ına rağmen gizleyebilir.
        self.show_label_chk = QCheckBox("3D'de bu portun ad etiketini göster")
        self.show_label_chk.setChecked(self._initial_show_label)
        lay.addWidget(self.show_label_chk)

        # Filtre kutusu
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filtrele (isim veya RFID)…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter_edit)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["İsim", "RFID"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemDoubleClicked.connect(lambda *_: self.accept())
        lay.addWidget(self.table)

        self._populate(self._rfids)

        # Mevcut atama varsa seç
        if current_rfid:
            for r in range(self.table.rowCount()):
                if (self.table.item(r, 1).text() or '').upper() == current_rfid.upper():
                    self.table.selectRow(r)
                    break

        btn_row = QHBoxLayout()
        self.clear_btn = QPushButton("✖ Eşlemeyi Temizle")
        self.clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("✓ Eşle")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self._on_ok)
        bb.rejected.connect(self.reject)
        btn_row.addWidget(bb)
        lay.addLayout(btn_row)

    def _populate(self, rows: list):
        self.table.setRowCount(0)
        for entry in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            name_item = QTableWidgetItem(entry.get('name') or '')
            rfid_item = QTableWidgetItem(entry.get('rfid_tag') or '')
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, rfid_item)

    def _apply_filter(self, text: str):
        t = (text or '').strip().lower()
        if not t:
            self._populate(self._rfids)
            return
        filtered = [
            e for e in self._rfids
            if t in (e.get('name', '') or '').lower()
            or t in (e.get('rfid_tag', '') or '').lower()
        ]
        self._populate(filtered)

    def _on_clear(self):
        self._chosen = ''
        self.accept()

    def _on_ok(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(
                self, "Seçim", "Lütfen tablodan bir RFID seçin."
            )
            return
        r = rows[0].row()
        self._chosen = self.table.item(r, 1).text().strip()
        self.accept()

    def selected_rfid(self) -> str:
        """'' → eşlemeyi temizle, aksi halde seçilen rfid_tag."""
        return self._chosen if self._chosen is not None else ''

    def selected_label(self) -> str:
        """Port adı (boş dönebilir → adı kaldır/gizle)."""
        return (self.label_edit.text() or '').strip()

    def selected_show_label(self) -> bool:
        """Kullanıcı 3D'de ad etiketini görmek istiyor mu."""
        return bool(self.show_label_chk.isChecked())


class _DoorEditDialog(QDialog):
    """ORAPS kapı isim + grup atama dialog'u.

    Kapı adı (zorunlu), grup combobox'ı (boş = grupsuz). Combobox yanında
    ➕ ile yeni grup oluşturulabilir, 🗑 ile seçili grup silinebilir
    (silme tüm üyeleri gruptan çıkarır).
    """

    _NO_GROUP_TEXT = "— Grupsuz —"

    def __init__(self, door_index: int, current_label: str,
                 current_group_id, groups: list, bm, parent=None,
                 current_show_label: bool = True,
                 current_stop_group_id=None):
        super().__init__(parent)
        self.setWindowTitle(f"Kapı Düzenle · #{door_index}")
        self.setMinimumWidth(440)
        self._door_index = int(door_index)
        self._bm = bm
        self._initial_label = current_label or f"Kapı {door_index}"
        self._initial_group_id = current_group_id
        self._initial_stop_group_id = current_stop_group_id
        self._initial_show_label = bool(current_show_label)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        hdr = QLabel(
            f"<b>Kapı #{door_index}</b> için ad ve grup atamasını düzenleyin."
        )
        hdr.setTextFormat(Qt.RichText)
        hdr.setWordWrap(True)
        root.addWidget(hdr)

        form = QFormLayout()
        self.label_edit = QLineEdit()
        self.label_edit.setText(self._initial_label)
        self.label_edit.setPlaceholderText("Örn: Sol Üst Kapak")
        form.addRow("Kapı adı:", self.label_edit)

        # Grup satırı: combo + ➕ + 🗑
        grp_row = QHBoxLayout()
        grp_row.setSpacing(6)
        self.group_combo = QComboBox()
        grp_row.addWidget(self.group_combo, 1)
        self.add_grp_btn = QPushButton("➕")
        self.add_grp_btn.setToolTip("Yeni kapı grubu oluştur")
        self.add_grp_btn.setFixedWidth(36)
        self.add_grp_btn.clicked.connect(
            lambda: self._on_add_group(target='lock'))
        grp_row.addWidget(self.add_grp_btn)
        self.del_grp_btn = QPushButton("🗑")
        self.del_grp_btn.setToolTip(
            "Seçili grubu sil (üyeler gruptan çıkar)"
        )
        self.del_grp_btn.setFixedWidth(36)
        self.del_grp_btn.clicked.connect(self._on_delete_group)
        grp_row.addWidget(self.del_grp_btn)
        form.addRow("Grup:", grp_row)

        # Faz-10b: makine durdurma grubu — kilit grubundan BAĞIMSIZ ikinci
        # üyelik. Bu gruptaki kapılar batch sırasında açılırsa machine_stop
        # DO'suna bağlı röle çeker (makine durur).
        stop_row = QHBoxLayout()
        stop_row.setSpacing(6)
        self.stop_group_combo = QComboBox()
        self.stop_group_combo.setToolTip(
            "Bu kapı seçilen makine durdurma grubuna dahil edilir. "
            "Grubun tetiklemesi için bir DO kanalının bu gruba "
            "'machine_stop' rolüyle bağlı olması gerekir."
        )
        stop_row.addWidget(self.stop_group_combo, 1)
        self.add_stop_grp_btn = QPushButton("➕")
        self.add_stop_grp_btn.setToolTip(
            "Yeni grup oluştur (makine durdurma için)")
        self.add_stop_grp_btn.setFixedWidth(36)
        self.add_stop_grp_btn.clicked.connect(
            lambda: self._on_add_group(target='stop'))
        stop_row.addWidget(self.add_stop_grp_btn)
        form.addRow("🛑 Durdurma Grubu:", stop_row)
        root.addLayout(form)

        # Etiket görünürlüğü (Faz-7): kullanıcı bu kapı için ad etiketini
        # toptan "Ad Etiketleri" toggle'ına rağmen gizleyebilir.
        self.show_label_chk = QCheckBox("3D'de bu kapının ad etiketini göster")
        self.show_label_chk.setChecked(self._initial_show_label)
        root.addWidget(self.show_label_chk)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("💾 Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self._reload_groups(groups, select_id=self._initial_group_id,
                            select_stop_id=self._initial_stop_group_id)

    def _fill_group_combo(self, combo, groups: list, select_id=None,
                          count_key: str = 'member_count'):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self._NO_GROUP_TEXT, None)
        for g in groups:
            combo.addItem(
                f"{g['name']} ({g.get(count_key, 0)} kapı)",
                int(g['id']),
            )
        target_idx = 0
        if select_id is not None:
            for i in range(combo.count()):
                if combo.itemData(i) == select_id:
                    target_idx = i
                    break
        combo.setCurrentIndex(target_idx)
        combo.blockSignals(False)

    def _reload_groups(self, groups: list, select_id=None,
                       select_stop_id=None):
        self._fill_group_combo(self.group_combo, groups, select_id)
        # Durdurma combosunda üye sayısı stop_group_id'den sayılır —
        # kilit sayacı gösterilince kullanıcı '0 kapı' görüyordu (2026-08-03).
        self._fill_group_combo(self.stop_group_combo, groups, select_stop_id,
                               count_key='stop_member_count')
        # Silme butonu: yalnızca bir grup seçiliyse aktif
        self.del_grp_btn.setEnabled(self.group_combo.currentData() is not None)
        self.group_combo.currentIndexChanged.connect(
            lambda *_: self.del_grp_btn.setEnabled(
                self.group_combo.currentData() is not None
            )
        )

    def _on_add_group(self, target: str = 'lock'):
        name, ok = QInputDialog.getText(
            self, "Yeni Kapı Grubu", "Grup adı:"
        )
        if not ok:
            return
        name = (name or '').strip()
        if not name:
            return
        try:
            new_id = self._bm.create_door_group(name)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Grup oluşturulamadı:\n{e}")
            return
        try:
            groups = self._bm.list_door_groups()
        except Exception:
            groups = []
        # Yeni grubu, ➕'a basılan satırın combosunda seç; diğerinin
        # mevcut seçimini koru.
        cur_lock = self.group_combo.currentData()
        cur_stop = self.stop_group_combo.currentData()
        if target == 'stop':
            self._reload_groups(groups, select_id=cur_lock,
                                select_stop_id=new_id)
        else:
            self._reload_groups(groups, select_id=new_id,
                                select_stop_id=cur_stop)

    def _on_delete_group(self):
        gid = self.group_combo.currentData()
        if gid is None:
            return
        gname = self.group_combo.currentText()
        ans = QMessageBox.question(
            self, "Grup Sil",
            f"'{gname}' grubunu silmek istiyor musunuz?\n"
            "Üye kapılar gruptan çıkacak (kapılar silinmez).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        try:
            self._bm.delete_door_group(int(gid))
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Grup silinemedi:\n{e}")
            return
        try:
            groups = self._bm.list_door_groups()
        except Exception:
            groups = []
        self._reload_groups(groups, select_id=None,
                            select_stop_id=self.stop_group_combo.currentData())

    def selected_label(self) -> str:
        """Kapı adı (boş dönebilir → adı kaldır/gizle)."""
        return (self.label_edit.text() or '').strip()

    def selected_group_id(self):
        """None → grupsuz; int → grup id."""
        data = self.group_combo.currentData()
        return None if data is None else int(data)

    def selected_stop_group_id(self):
        """None → durdurma grubunda değil; int → grup id (Faz-10b)."""
        data = self.stop_group_combo.currentData()
        return None if data is None else int(data)

    def selected_show_label(self) -> bool:
        """Kullanıcı 3D'de ad etiketini görmek istiyor mu."""
        return bool(self.show_label_chk.isChecked())
