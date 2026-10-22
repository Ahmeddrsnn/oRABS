"""three.js-based 3D viewer widget for the Oraps application.

Uses QtWebEngine to host a tiny offline HTML page (`assets/viewer/viewer.html`)
that loads three.js + GLTFLoader + OrbitControls from local files. A
QWebChannel bridge exposes a Python `Bridge` object as `bridge` on the JS
side so the Python widget can drive door colouring, camera presets, and
model loading.
"""

from __future__ import annotations

import os
import json
import urllib.parse
from typing import Dict, Optional

from PyQt5.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel


def _viewer_dir() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', 'assets', 'viewer')
    )


class _Bridge(QObject):
    """QObject exposed on the JS side as `bridge`."""

    viewer_ready = pyqtSignal()
    model_loaded = pyqtSignal(int, int, str)  # door_count, port_count, meta_json
    debug_names  = pyqtSignal(str)  # JSON list of node names (debug)
    port_picked  = pyqtSignal(int)  # port_index 1..14 (RFID eşleme modu)
    door_picked  = pyqtSignal(int)  # door_index 1..12 (kapı eşleme modu)
    laf_position_changed = pyqtSignal(int, float, float)  # sensor_id, xPct, yPct
    door_position_changed = pyqtSignal(int, float, float, float)  # idx, dx, dy, dz
    port_position_changed = pyqtSignal(int, float, float, float)  # idx, dx, dy, dz
    door_visibility_changed = pyqtSignal(int, int)  # door_index, is_visible
    port_visibility_changed = pyqtSignal(int, int)  # port_index, is_visible

    @pyqtSlot()
    def on_viewer_ready(self):
        self.viewer_ready.emit()

    @pyqtSlot(int, int)
    @pyqtSlot(int, int, str)
    def on_model_loaded(self, door_count: int, port_count: int = 0,
                        meta_json: str = ''):
        self.model_loaded.emit(door_count, port_count, meta_json or '')

    @pyqtSlot(int, float, float, float)
    def on_door_position_changed(self, door_index: int, dx: float, dy: float, dz: float):
        self.door_position_changed.emit(door_index, dx, dy, dz)

    @pyqtSlot(int, float, float, float)
    def on_port_position_changed(self, port_index: int, dx: float, dy: float, dz: float):
        self.port_position_changed.emit(port_index, dx, dy, dz)

    @pyqtSlot(int, int)
    def on_door_visibility_changed(self, door_index: int, is_visible: int):
        self.door_visibility_changed.emit(door_index, is_visible)

    @pyqtSlot(int, int)
    def on_port_visibility_changed(self, port_index: int, is_visible: int):
        self.port_visibility_changed.emit(port_index, is_visible)

    @pyqtSlot(str)
    def on_debug_names(self, names_json: str):
        self.debug_names.emit(names_json)

    @pyqtSlot(int)
    def on_port_picked(self, port_index: int):
        self.port_picked.emit(port_index)

    @pyqtSlot(int)
    def on_door_picked(self, door_index: int):
        self.door_picked.emit(door_index)

    @pyqtSlot(int, float, float)
    def on_laf_position_changed(self, sensor_id: int, x_pct: float, y_pct: float):
        self.laf_position_changed.emit(sensor_id, x_pct, y_pct)


class Viewer3D(QWidget):
    """three.js viewer wrapped as a QWidget.

    If PyQtWebEngine is unavailable, displays a friendly fallback message.
    """

    ready = pyqtSignal()
    model_loaded = pyqtSignal(int, int, str)  # door_count, port_count, meta_json
    port_picked  = pyqtSignal(int)  # 3D viewer’da pick mode açıkken glove port tıklandı
    door_picked  = pyqtSignal(int)  # 3D viewer’da pick mode açıkken kapı tıklandı
    laf_position_changed = pyqtSignal(int, float, float)  # sensor_id, xPct, yPct (drag-place)
    door_position_changed = pyqtSignal(int, float, float, float)  # door_index, dx, dy, dz
    port_position_changed = pyqtSignal(int, float, float, float)  # port_index, dx, dy, dz
    door_visibility_changed = pyqtSignal(int, int)  # door_index, is_visible
    port_visibility_changed = pyqtSignal(int, int)  # port_index, is_visible

    def __init__(self, parent=None):
        super().__init__(parent)
        self._available = False
        self._web = None
        self._channel = None
        self._bridge = None
        self._pending_model: Optional[str] = None
        self._pending_states: Optional[Dict[str, str]] = None
        self._pending_laf_overlay: Optional[list] = None
        self._pending_layout_edit: Optional[bool] = None
        self._pending_door_labels: Optional[list] = None
        self._pending_port_labels: Optional[list] = None
        self._pending_door_labels_visible: Optional[bool] = None
        self._js_ready = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineView
            from PyQt5.QtWebChannel import QWebChannel
        except ImportError as exc:
            # Graceful fallback — viewer disabled, app still works.
            msg = QLabel(
                "🛈 3D görüntüleyici kullanılamıyor.\n\n"
                "PyQtWebEngine yüklenemedi:\n"
                f"   {exc}\n\n"
                "Aktif Python ortamında şu komutu çalıştırın:\n\n"
                "    pip install PyQtWebEngine\n\n"
                "Not: PyQt5.QtWebEngineWidgets, QApplication oluşturulmadan ÖNCE\n"
                "import edilmelidir (main.py bunu yapar)."
            )
            msg.setWordWrap(True)
            msg.setStyleSheet(
                "background:#f3f4f6;color:#374151;padding:24px;"
                "font:13px 'Segoe UI';border:1px dashed #d1d5db;border-radius:8px;"
            )
            layout.addWidget(msg)
            return

        self._available = True
        self._web = QWebEngineView(self)
        # QWebEnginePage subclass: JS console.log/error/exception'ları
        # Python stderr'e forward et (debug için).
        from PyQt5.QtWebEngineWidgets import QWebEnginePage

        class _LoggingPage(QWebEnginePage):
            def javaScriptConsoleMessage(self, level, msg, line, source):
                try:
                    lvl_name = {0: 'INFO', 1: 'WARN', 2: 'ERROR'}.get(int(level), '?')
                    print(f"[viewer.js {lvl_name}] {source}:{line}  {msg}")
                except Exception:
                    pass
        self._web.setPage(_LoggingPage(self._web))
        layout.addWidget(self._web)

        # Disable HTTP/disk cache so viewer.js/viewer.html edits take effect
        # immediately on app restart (otherwise QtWebEngine keeps the old JS
        # and the user sees stale behaviour).
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineProfile
            prof = self._web.page().profile()
            prof.setHttpCacheType(QWebEngineProfile.NoCache)
            prof.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
            prof.clearHttpCache()
        except Exception:
            pass

        self._channel = QWebChannel(self._web.page())
        self._bridge = _Bridge()
        self._channel.registerObject('bridge', self._bridge)
        self._web.page().setWebChannel(self._channel)
        self._bridge.viewer_ready.connect(self._on_js_ready)
        self._bridge.model_loaded.connect(self.model_loaded)
        self._bridge.debug_names.connect(self._on_debug_names)
        self._bridge.port_picked.connect(self.port_picked)
        self._bridge.door_picked.connect(self.door_picked)
        # Faz-5: LAF chip drag-place → chip pozisyonu Python'a forward.
        # Viewer3D'nin laf_position_changed sinyaline bağla.
        self._bridge.laf_position_changed.connect(self.laf_position_changed)
        # Faz-5: kapı/port chip drag + görünürlük toggle → Python'a forward.
        self._bridge.door_position_changed.connect(self.door_position_changed)
        self._bridge.port_position_changed.connect(self.port_position_changed)
        self._bridge.door_visibility_changed.connect(self.door_visibility_changed)
        self._bridge.port_visibility_changed.connect(self.port_visibility_changed)

        html_path = os.path.join(_viewer_dir(), 'viewer.html')
        if os.path.exists(html_path):
            self._web.load(QUrl.fromLocalFile(html_path))
        else:
            self._show_error(f"viewer.html bulunamadı: {html_path}")

    # ── Public API ──────────────────────────────────────────────
    def is_available(self) -> bool:
        return self._available

    def load_model(self, glb_path: str):
        """Load a GLB into the viewer (absolute or relative to src/)."""
        if not self._available:
            return
        if not glb_path:
            self._show_no_model("Henüz bir 3D model yüklenmedi.\n"
                                "Ayarlar → ORAPS sekmesinden bir GLB dosyası seçin.")
            return
        if not os.path.isabs(glb_path):
            src_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), '..')
            )
            glb_path = os.path.join(src_dir, glb_path)
        if not os.path.exists(glb_path):
            self._show_no_model(
                "Tanımlı GLB modeli bulunamadı:\n"
                f"  {glb_path}\n\n"
                "Ayarlar → ORAPS sekmesinden geçerli bir model seçin."
            )
            return
        # Use file:// URL so the WebEngine can fetch the binary
        url = QUrl.fromLocalFile(glb_path).toString()
        if self._js_ready:
            self._run_js(f"OrapsViewer.loadModel({json.dumps(url)});")
        else:
            self._pending_model = url

    def apply_door_states(self, states: Dict[str, str]):
        """Apply {'1':'open','2':'locked',...} to the loaded model."""
        if not self._available:
            return
        payload = json.dumps(states or {})
        if self._js_ready:
            self._run_js(f"OrapsViewer.applyDoorStates({payload});")
        else:
            self._pending_states = states

    def reset_doors(self):
        if not self._available:
            return
        self._run_js("OrapsViewer.resetDoors();")

    # ── Port state (Faz-5: GLT canlı veri) ──────────────────────
    def apply_port_states(self, states: Dict[str, str]):
        """Apply {'1':'occupied','2':'empty','3':'motion',...} to ports."""
        if not self._available:
            return
        payload = json.dumps(states or {})
        if self._js_ready:
            self._run_js(f"OrapsViewer.applyPortStates({payload});")

    def reset_ports(self):
        if self._available:
            self._run_js("OrapsViewer.resetPorts();")

    def set_enabled_views(self, views):
        """Show only the named views (subset of front/back/left/right)."""
        if not self._available:
            return
        payload = json.dumps(list(views or []))
        self._run_js(f"OrapsViewer.setEnabledViews({payload});")

    # ── LAF overlay (Faz-5) ─────────────────────────────────────
    # GLB üzerinde sensör değer chip'leri — three.js sahnesinin DIŞINDA
    # DOM katmanı; render loop'u etkilemez → GLB titremesi olmaz.
    def set_laf_overlay(self, sensors):
        """sensors: list of {'id', 'label', 'unit', 'value', 'xPct', 'yPct'}.
        Eksik chip'leri ekler, fazla olanları kaldırır. Pozisyon yüzdelik.
        Viewer henüz hazır değilse pending'e koyup ready olunca uygular."""
        if not self._available:
            return
        sensors_list = list(sensors or [])
        if not self._js_ready:
            self._pending_laf_overlay = sensors_list
            return
        payload = json.dumps(sensors_list)
        self._run_js(f"OrapsViewer.setLafSensors({payload});")

    def update_laf_value(self, sensor_id, value_str: str, unit: str = ''):
        """Bir LAF chip'inin sadece değerini güncelle (DOM rebuild yok)."""
        if not self._available or not self._js_ready:
            return
        self._run_js(
            f"OrapsViewer.updateLafValue({json.dumps(str(sensor_id))},"
            f"{json.dumps(str(value_str))},{json.dumps(unit or '')});"
        )

    def set_layout_edit_mode(self, enabled: bool):
        """LAF chip'lerinin drag-place modunu aç/kapa. Viewer hazır değilse
        pending olarak saklanıp ready olunca uygulanır."""
        if not self._available:
            return
        if not self._js_ready:
            self._pending_layout_edit = bool(enabled)
            return
        self._run_js(
            f"OrapsViewer.setLayoutEditMode({json.dumps(bool(enabled))});"
        )

    # ── Kapı / Port 3D ad etiketleri (sprite, Faz-5) ────────────
    def set_door_name_labels(self, doors):
        """3D kapı ad etiketleri (sprite) — kapının üstünde, kameraya bakan
        yazı. items: {'index','label','state','sub','offset'}. Yalnızca adı
        olan (label boş değil) kapılar gösterilir."""
        if not self._available:
            return
        items = list(doors or [])
        if not self._js_ready:
            self._pending_door_labels = items
            return
        self._run_js(f"OrapsViewer.setDoorNameLabels({json.dumps(items)});")

    def set_port_name_labels(self, ports):
        """3D port ad etiketleri (sprite). items: {'index','label','state',
        'sub','offset'}. Yalnızca adı olan portlar gösterilir."""
        if not self._available:
            return
        items = list(ports or [])
        if not self._js_ready:
            self._pending_port_labels = items
            return
        self._run_js(f"OrapsViewer.setPortNameLabels({json.dumps(items)});")

    def set_labels_visible(self, enabled: bool):
        """3D kapı + port ad etiketlerini toptan göster/gizle."""
        if not self._available:
            return
        if not self._js_ready:
            self._pending_door_labels_visible = bool(enabled)
            return
        self._run_js(
            f"OrapsViewer.setLabels3DVisible({json.dumps(bool(enabled))});"
        )

    # Geriye uyum
    def set_door_labels_visible(self, enabled: bool):
        self.set_labels_visible(enabled)

    def set_pick_mode(self, enabled):
        """Pick mode'u aç/kapa.

        Geri uyumluluk: bool kabul edilir (True → 'port', False → kapalı).
        Yeni: 'port' | 'door' | None / '' / False string'i de kabul edilir.
        Tıklanınca ilgili port_picked / door_picked sinyali emit edilir.
        """
        if not self._available:
            return
        if enabled is True:
            mode = 'port'
        elif enabled is False or enabled is None or enabled == '':
            mode = ''
        else:
            mode = str(enabled).lower()
            if mode not in ('port', 'door'):
                mode = ''
        self._run_js(
            f"OrapsViewer.setPickMode({json.dumps(mode)});"
        )

    def set_rotate_enabled(self, enabled: bool):
        """Faz-7: pick modu içinde GLB'nin serbest döndürme toggle'ı.
        True → pointer drag = 360° yaw/pitch; False → drag inaktif, pointer
        = pick."""
        if not self._available:
            return
        self._run_js(
            f"OrapsViewer.setRotateEnabled({json.dumps(bool(enabled))});"
        )

    def view_front(self):
        if self._available: self._run_js("OrapsViewer.viewFront();")

    def view_top(self):
        if self._available: self._run_js("OrapsViewer.viewTop();")

    def view_iso(self):
        if self._available: self._run_js("OrapsViewer.viewIso();")

    def view_reset(self):
        if self._available: self._run_js("OrapsViewer.viewReset();")

    # ── Internal ────────────────────────────────────────────────
    def _on_js_ready(self):
        self._js_ready = True
        if self._pending_model:
            self._run_js(f"OrapsViewer.loadModel({json.dumps(self._pending_model)});")
            self._pending_model = None
        # Door states are applied after the model fires model_loaded;
        # we cache them but the caller usually re-pushes after loading.
        if self._pending_states is not None:
            self._run_js(
                f"OrapsViewer.applyDoorStates({json.dumps(self._pending_states)});"
            )
            self._pending_states = None
        # Faz-5 pending: LAF overlay ve layout edit mode
        if self._pending_laf_overlay is not None:
            self._run_js(
                f"OrapsViewer.setLafSensors({json.dumps(self._pending_laf_overlay)});"
            )
            self._pending_laf_overlay = None
        if self._pending_layout_edit is not None:
            self._run_js(
                f"OrapsViewer.setLayoutEditMode({json.dumps(self._pending_layout_edit)});"
            )
            self._pending_layout_edit = None
        if self._pending_door_labels is not None:
            self._run_js(
                f"OrapsViewer.setDoorNameLabels({json.dumps(self._pending_door_labels)});"
            )
            self._pending_door_labels = None
        if self._pending_port_labels is not None:
            self._run_js(
                f"OrapsViewer.setPortNameLabels({json.dumps(self._pending_port_labels)});"
            )
            self._pending_port_labels = None
        if self._pending_door_labels_visible is not None:
            self._run_js(
                f"OrapsViewer.setLabels3DVisible({json.dumps(self._pending_door_labels_visible)});"
            )
            self._pending_door_labels_visible = None
        self.ready.emit()

    def _run_js(self, code: str):
        if self._web is not None:
            self._web.page().runJavaScript(code)

    def _on_debug_names(self, names_json: str):
        """JS reports node names when 0 doors matched the regex."""
        try:
            names = json.loads(names_json)
        except Exception:
            names = []
        try:
            from utils.app_logger import get_logger
            log = get_logger('oraps.viewer')
            log.warning("Viewer: 0 doors matched. GLB node names (%d):", len(names))
            for n in names[:80]:
                log.warning("    %r", n)
            if len(names) > 80:
                log.warning("    ... (+%d more)", len(names) - 80)
        except Exception:
            print(f"[oraps.viewer] 0 doors matched. {len(names)} names:")
            for n in names[:80]:
                print(f"    {n!r}")

    def _show_error(self, text: str):
        if self._web is None:
            return
        html = (
            "<html><body style='font-family:Segoe UI;background:#1f2937;"
            "color:#f87171;padding:24px;'>"
            f"<h3>3D görüntüleyici hatası</h3><p>{urllib.parse.quote(text)}</p>"
            "</body></html>"
        )
        self._web.setHtml(html)

    def _show_no_model(self, text: str):
        """GLB yokken çirkin hata yerine zarif bilgi sayfası göster."""
        if self._web is None:
            return
        safe = (text or "").replace("&", "&amp;").replace("<", "&lt;")
        safe = safe.replace("\n", "<br>")
        html = (
            "<!DOCTYPE html><html><body style=\"margin:0;padding:0;"
            "background:#111827;color:#e5e7eb;font-family:Segoe UI,sans-serif;"
            "display:flex;align-items:center;justify-content:center;"
            "height:100vh;width:100vw;text-align:center;\">"
            "<div style=\"max-width:480px;padding:32px;border:1px dashed #374151;"
            "border-radius:12px;background:rgba(31,41,55,0.6);\">"
            "<div style=\"font-size:42px;margin-bottom:8px;\">📦</div>"
            "<h3 style=\"margin:8px 0 12px;color:#f9fafb;font-weight:600;\">"
            "3D Model Yüklenmedi</h3>"
            f"<p style=\"line-height:1.55;color:#9ca3af;font-size:13px;\">{safe}</p>"
            "</div></body></html>"
        )
        self._web.setHtml(html)
