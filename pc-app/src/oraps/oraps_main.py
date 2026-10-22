"""Oraps application root widget (Faz-4).

Hosts four inner tabs:
  🏠 Genel Bakış      — 3D viewer + device info
  🔢 Batch            — door-lock configurations + active batch control
  📜 Audit Trail      — AuditTrailPanel locked to ORAPS category
  ⚙ Ayarlar          — SettingsPanel showing only the 'oraps' group

Cross-talk
----------
- Batch panel emits `batch_changed` whenever active batch / configs change.
  We use that to refresh the Overview viewer colours and the Settings
  panel does not need to be touched.
- Settings panel exposes `oraps_settings_changed` (added in Faz-4) so the
  Overview reloads the GLB when the path / unit changes.
"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from gui.audit_trail_panel import AuditTrailPanel
from gui.settings_panel import SettingsPanel

from .overview_panel import OrapsOverviewPanel
from .batch_panel import OrapsBatchPanel
from .laf_panel import LafPanel
from .io_panel import IoPanel
from core.batch_manager import BatchManager
from core.weidmuller_bridge import WeidmullerBridge


_TAB_QSS = """
QTabBar::tab {
    height: 36px; padding: 0 18px; margin-right: 2px;
    font-family: 'Segoe UI'; font-size: 13px; color: #4B5563;
    background: #F3F4F6;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #FFFFFF; color: #2563EB;
    border-bottom: 2px solid #2563EB; font-weight: 600;
}
QTabBar::tab:hover { background: #E5E7EB; }
QTabWidget::pane { border: none; background: #FFFFFF; }
"""


class OrapsMain(QWidget):
    """Top-level Oraps widget mounted into the outer QTabWidget."""

    # Overview'da bir GLT cihaz kartına tıklandığında frılatılır—
    # MainWindow outer_tabs'i GLT'ye + glt_tabs'i ESP-NOW ana sekmesine geçirir.
    glt_card_clicked = pyqtSignal(str)

    def __init__(self, database, auth_manager, audit_manager,
                 pdf_generator, esp32_comm=None,
                 esp_now_control=None, parent=None):
        super().__init__(parent)
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        self.pdf_gen = pdf_generator
        self.esp32 = esp32_comm
        self.esp_now_control = esp_now_control

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(_TAB_QSS)
        root.addWidget(self.tabs)

        # 1. Overview (3D viewer + info)
        self.overview = OrapsOverviewPanel(
            self.db, self.auth, self.audit,
            pdf_generator=self.pdf_gen,
            esp32_comm=self.esp32,
            esp_now_control=self.esp_now_control,
        )
        # Forward GLT card clicks up to MainWindow
        self.overview.glt_card_clicked.connect(self.glt_card_clicked)
        self.tabs.addTab(self.overview, "🏠 Genel Bakış")

        # 2. Batch
        self.batch = OrapsBatchPanel(self.db, self.auth, self.audit)
        self.batch.batch_changed.connect(self.overview.refresh_active_batch)
        self.tabs.addTab(self.batch, "🔢 Batch")

        # 3. LAF (Laminar Air Flow live readings + alarm log)
        self.laf_panel = LafPanel(self.db, self.auth, self.audit)
        self.tabs.addTab(self.laf_panel, "🌬 LAF")

        # 4. IO (Weidmüller — admin-only, lazy created in on_login_complete)
        self.io_panel: 'IoPanel | None' = None

        # Headless IO bridge — owns workers, drives lock DOs from active
        # batch. Created always so an Operator-initiated batch still
        # controls hardware even when the admin IO tab is closed.
        self._bm_for_bridge = BatchManager(self.db, self.auth, self.audit)
        self.io_bridge = WeidmullerBridge(
            self.db, self.auth, self.audit, self._bm_for_bridge,
        )
        self.batch.batch_changed.connect(self.io_bridge.on_batch_changed)
        # Faz-9: Ana ekrandan (overview quick buttons) tetiklenen
        # batch_changed sinyali batch panel'in kendi UI'sını da güncellesin.
        # Kendi start/finish çağrıları zaten self.refresh() yapıyor; bu
        # bağlantı sadece dış tetiklemeler (overview → emit) için gereklidir.
        self.batch.batch_changed.connect(self.batch.refresh)
        # Overview paneli DI sensör → 3D viewer sarı boyama için bridge'i
        # bağla. Bridge oluştuktan hemen sonra geçilmesi gerekiyor ki
        # set_io_bridge cache'i okuyup ilk render'da sensor_open kapıları
        # da uygulanabilsin.
        try:
            self.overview.set_io_bridge(self.io_bridge)
        except Exception:
            pass
        # Batch paneli batch config dialog'unda yalnızca DO (kilit) çıkışına
        # bağlı kapı gruplarını göstersin diye bridge'i alır.
        try:
            self.batch.set_io_bridge(self.io_bridge)
        except Exception:
            pass
        # ESP-NOW control'a bridge'i bağla — test kaydedildiğinde
        # batch_complete DO sinyalini tetikleyebilsin.
        try:
            if self.esp_now_control is not None:
                self.esp_now_control.set_io_bridge(self.io_bridge)
        except Exception:
            pass

        # 5. Audit Trail (ORAPS-scoped) — Şuanlık sekme gizli
        # (kullanıcı isteği 2026-06-29). Panel instance'ı oluşturuluyor
        # ki IO sekmesi insert mantığı (indexOf(audit_panel)) ve
        # apply_language gibi referanslar bozulmasın; outer
        # 'Audit Trail' sekmesi tek görünür ekran olsun.
        self.audit_panel = AuditTrailPanel(
            self.audit, self.pdf_gen, category_filter='oraps'
        )
        # self.tabs.addTab(self.audit_panel, "📜 Audit Trail")

        # 4. Settings (only Oraps group)
        self.settings = SettingsPanel(
            self.auth, self.db,
            visible_groups={'oraps'},
            custom_header={'tr': 'Oraps Ayarları', 'en': 'Oraps Settings'},
            custom_subtitle={
                'tr': 'Oraps uygulamasına özel ayarlar (sadece admin değiştirebilir)',
                'en': 'Settings specific to the Oraps application (admin only)',
            },
            audit_manager=self.audit,
        )
        # Settings panel emits this when Oraps settings are saved
        if hasattr(self.settings, 'oraps_settings_changed'):
            self.settings.oraps_settings_changed.connect(
                self.overview.refresh_from_settings
            )
        if hasattr(self.settings, 'laf_settings_changed'):
            self.settings.laf_settings_changed.connect(
                self.laf_panel.on_settings_changed
            )
        if hasattr(self.settings, 'weidmuller_settings_changed'):
            self.settings.weidmuller_settings_changed.connect(
                self._on_io_settings_changed
            )
        self.tabs.addTab(self.settings, "⚙ Ayarlar")
        self._settings_added = True  # Track ORAPS Ayarlar sekmesi (admin-only)
        self._batch_added = True     # Track ORAPS Batch sekmesi (operator gizli)
        self._laf_added = True       # Track ORAPS LAF sekmesi (operator gizli)

    # ── Lifecycle hooks ───────────────────────────────
    def on_login_complete(self):
        """Called by main_window after user logs in."""
        # Önce role-based görünürlüğü uygula (Operator → yalnız Overview)
        self._apply_operator_visibility()
        # Overview header buton görünürlüğü (Operator'da admin butonlarını gizle).
        try:
            if hasattr(self.overview, 'apply_role_visibility'):
                self.overview.apply_role_visibility()
        except Exception:
            pass
        self.batch.refresh()
        if hasattr(self.settings, 'refresh_admin_visibility'):
            self.settings.refresh_admin_visibility()
        if hasattr(self.settings, 'refresh_oraps_editable'):
            self.settings.refresh_oraps_editable()
        # Önce UI'yi kur (ana thread DB okuması), SONRA worker'ları
        # başlat. Worker'lar başlatıldıktan sonra view'ları onlara bağla
        # ki status_lbl 'Bağlı' / 'Bekleniyor' güncellemesini alıp Overview
        # kartıyla senkron olsun.
        self._apply_io_visibility()
        self._apply_settings_visibility()
        try:
            self.io_bridge.start_all()
            self.io_bridge.on_batch_changed()
        except Exception:
            import traceback; traceback.print_exc()
        if self.io_panel is not None:
            try:
                self.io_panel.attach_workers_from_bridge()
            except Exception:
                import traceback; traceback.print_exc()

        # Faz-9: DB ayarlarından iç sekme görünürlüğünü uygula (rol-bazlı
        # görünürlük üzerine sadece gizleme yönünde).
        try:
            self.apply_tab_visibility()
        except Exception:
            pass

    def on_logout(self):
        """Called by main_window before user logs out."""
        self._teardown_io_panel()
        # ORAPS iç 'Ayarlar' sekmesini gizle (operatör login'inde tekrar
        # _apply_settings_visibility doğru karar verir).
        if getattr(self, '_settings_added', False):
            idx = self.tabs.indexOf(self.settings)
            if idx >= 0:
                self.tabs.removeTab(idx)
            self._settings_added = False
        try:
            self.io_bridge.stop_all()
        except Exception:
            pass

    # ── IO panel (admin-only) ─────────────────────
    # Faz-9 ────────────────────────────────────────────────────────────
    def apply_tab_visibility(self):
        """DB'deki `tab_visible_orabs_*` ayarlarını iç sekmelere uygula.

        Rol-bazlı `_apply_operator_visibility` / `_apply_settings_visibility`
        / `_apply_io_visibility` sekmeleri fiziksel ekliyor/kaldırıyor.
        Bu metod sadece ayarda '0' olan sekmeleri `setTabVisible(False)`
        ile gizler; rol tarafından hiç eklenmemiş sekmelere etki etmez.
        """
        inner_map = {
            'tab_visible_orabs_overview': self.overview,
            'tab_visible_orabs_batch':    self.batch,
            'tab_visible_orabs_laf':      self.laf_panel,
            'tab_visible_orabs_io':       self.io_panel,
        }
        for key, widget in inner_map.items():
            if widget is None:
                continue
            try:
                raw = str(self.db.get_setting(key, '1') or '1').strip()
                want = raw not in ('0', 'false', 'False')
                idx = self.tabs.indexOf(widget)
                if idx >= 0:
                    self.tabs.setTabVisible(idx, want)
            except Exception:
                pass

    def _apply_operator_visibility(self):
        """Operator için yalnız Genel Bakış sekmesi görünür; Batch ve LAF
        sekmeleri gizlenir. Widget'lar canlı kalır (sinyal bağlantıları
        bozulmasın); sadece QTabWidget'a ekli olup olmaması değişir.
        IO ve Ayarlar zaten admin-only kontrolüyle gizleniyor.
        """
        try:
            role = self.auth.get_current_user_role()
        except Exception:
            role = None
        is_operator = (role == 'Operator')

        # Batch — Operator gizler, diğer roller gösterir.
        batch_idx = self.tabs.indexOf(self.batch)
        if is_operator and batch_idx >= 0:
            self.tabs.removeTab(batch_idx)
            self._batch_added = False
        elif not is_operator and batch_idx < 0:
            # Overview daima 0; Batch hemen sağına.
            self.tabs.insertTab(1, self.batch, "🔢 Batch")
            self._batch_added = True

        # LAF — Operator gizler.
        laf_idx = self.tabs.indexOf(self.laf_panel)
        if is_operator and laf_idx >= 0:
            self.tabs.removeTab(laf_idx)
            self._laf_added = False
        elif not is_operator and laf_idx < 0:
            # LAF — Batch'in sağına (yoksa Overview'un sağına).
            insert_at = self.tabs.indexOf(self.batch) + 1
            if insert_at <= 0:
                insert_at = 1
            self.tabs.insertTab(insert_at, self.laf_panel, "🌬 LAF")
            self._laf_added = True

    def _apply_settings_visibility(self):
        """ORAPS iç 'Ayarlar' sekmesini sadece admin'e göster, operatöre gizle.

        Widget her zaman canlı kalır (sinyal bağlantıları ve
        `refresh_admin_visibility` çağrıları bozulmasın); sadece QTabWidget'a
        ekli olup olmaması değişir. Sekme her zaman ORAPS inner tabs'ın en
        sağında kalır (IO'nun da sağında).
        """
        try:
            is_admin = self.auth.get_current_user_role() == 'Admin'
        except Exception:
            is_admin = False
        currently_added = getattr(self, '_settings_added', False)
        if is_admin and not currently_added:
            self.tabs.addTab(self.settings, "⚙ Ayarlar")
            self._settings_added = True
        elif not is_admin and currently_added:
            idx = self.tabs.indexOf(self.settings)
            if idx >= 0:
                self.tabs.removeTab(idx)
            self._settings_added = False

    def _apply_io_visibility(self):
        try:
            is_admin = self.auth.get_current_user_role() == 'Admin'
        except Exception:
            is_admin = False
        if is_admin and self.io_panel is None:
            self.io_panel = IoPanel(self.db, self.auth, self.audit,
                                    bridge=self.io_bridge)
            # IO sekmesini Ayarlar'ın soluna ekle (Ayarlar her zaman sağda kalsın).
            idx = self.tabs.indexOf(self.settings)
            if idx < 0:
                self.tabs.addTab(self.io_panel, "🔌 IO")
            else:
                self.tabs.insertTab(idx, self.io_panel, "🔌 IO")
        elif not is_admin and self.io_panel is not None:
            self._teardown_io_panel()

    def _teardown_io_panel(self):
        if self.io_panel is None:
            return
        try:
            self.io_panel.shutdown()
        except Exception:
            pass
        idx = self.tabs.indexOf(self.io_panel)
        if idx >= 0:
            self.tabs.removeTab(idx)
        self.io_panel.setParent(None)
        self.io_panel.deleteLater()
        self.io_panel = None

    def _on_io_settings_changed(self):
        # Sıra önemli: önce worker thread'leri DURDUR, sonra ana thread'de
        # view'ları DB'den okutarak yeniden kur, sonra worker'ları başlat,
        # son olarak view'ları yeni worker'lara bağla.
        try:
            self.io_bridge.stop_all()
        except Exception:
            import traceback; traceback.print_exc()
        if self.io_panel is not None:
            try:
                self.io_panel.on_settings_changed()
            except Exception:
                import traceback; traceback.print_exc()
        try:
            self.io_bridge.start_all()
            self.io_bridge.on_batch_changed()
        except Exception:
            import traceback; traceback.print_exc()
        if self.io_panel is not None:
            try:
                self.io_panel.attach_workers_from_bridge()
            except Exception:
                import traceback; traceback.print_exc()
        # Overview bağlantı kartını ve cihaz sayılarını hemen tazele
        if hasattr(self.overview, 'refresh_io_status'):
            self.overview.refresh_io_status()
        if hasattr(self.overview, '_refresh_device_counts'):
            self.overview._refresh_device_counts()
    def apply_language(self, lang_code: str):
        """Mirror the parent main window's language switch."""
        if hasattr(self.audit_panel, 'apply_language'):
            self.audit_panel.apply_language(lang_code)
        if hasattr(self.settings, 'current_lang') and self.settings.current_lang != lang_code:
            self.settings.current_lang = lang_code
            try:
                idx = self.settings.lang_combo.findData(lang_code)
                if idx >= 0:
                    self.settings.lang_combo.blockSignals(True)
                    self.settings.lang_combo.setCurrentIndex(idx)
                    self.settings.lang_combo.blockSignals(False)
            except Exception:
                pass
            try:
                self.settings.translate_ui()
            except Exception:
                pass

    def shutdown(self):
        """Release background resources (LAF + IO worker threads)."""
        try:
            self.laf_panel.shutdown()
        except Exception:
            pass
        self._teardown_io_panel()
