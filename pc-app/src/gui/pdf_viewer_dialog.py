"""In-app PDF viewer dialog.

QWebEngineView (Chromium) tabanlı, tam ekran açılan basit bir PDF
görüntüleyici. Chromium'un yerleşik PDF UI'sini kullanır — zoom, sayfa
gezinti, yazdır, indir düğmeleri ekranın üst köşesinde otomatik gelir.

Kullanım:
    dlg = PdfViewerDialog(pdf_path, parent=self)
    dlg.exec_()

Bağımlılık: PyQtWebEngine (proje zaten ORAPS 3D viewer için kullanıyor).
Yüklenemezse dialog `os.startfile` fallback'i sunar.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox,
    QSizePolicy, QFrame,
)


class PdfViewerDialog(QDialog):
    """Fullscreen in-app PDF viewer.

    Args:
        pdf_path: Görüntülenecek PDF dosyasının mutlak yolu.
        parent:   Ata widget (opsiyonel).
    """

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self.pdf_path = os.path.abspath(pdf_path)
        self._web = None

        self.setWindowTitle(os.path.basename(self.pdf_path))
        # Modal + frameless kombinasyonu bazı sistemlerde ESC ile
        # kapanmayı tetiklemiyor; modal + normal frame + fullscreen
        # kombinasyonunu tercih ediyoruz. Ana pencere üzerine gelir.
        self.setModal(True)

        self._build_ui()

        # Fullscreen ile aç — kullanıcı sağ alttaki "Çıkış" butonu ile
        # kapatır. Alt tab / ESC ile de kapanır (QDialog default).
        # showFullScreen()'i exec_() öncesinde çağırmak yerine
        # showEvent'te tetikliyoruz ki dialog geometrisi hazır olsun.

    # ── UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
        except ImportError as exc:
            # PyQtWebEngine yok — fallback mesajı + Windows ile aç butonu
            fallback = QLabel(
                "🛈 In-app PDF görüntüleyici kullanılamıyor.\n\n"
                f"PyQtWebEngine yüklenemedi:\n   {exc}\n\n"
                "Aşağıdaki butonla dosyayı sistem varsayılan PDF "
                "okuyucusuyla açabilirsiniz."
            )
            fallback.setWordWrap(True)
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setStyleSheet(
                "background:#f3f4f6;color:#374151;padding:32px;"
                "font:14px 'Segoe UI';"
            )
            root.addWidget(fallback, 1)
            self._add_bottom_bar(root, enable_system_open=True)
            return

        # WebEngineView + PDF plugin ayarları
        self._web = QWebEngineView(self)
        self._web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        try:
            s = self._web.settings()
            # Qt 5.13+ ile gelen dahili PDF görüntüleyici.
            if hasattr(QWebEngineSettings, 'PdfViewerEnabled'):
                s.setAttribute(QWebEngineSettings.PdfViewerEnabled, True)
            s.setAttribute(QWebEngineSettings.PluginsEnabled, True)
        except Exception:
            pass
        root.addWidget(self._web, 1)
        self._web.load(QUrl.fromLocalFile(self.pdf_path))

        self._add_bottom_bar(root, enable_system_open=False)

    def _add_bottom_bar(self, root: QVBoxLayout, enable_system_open: bool):
        """Alt bar: sol tarafta dosya adı, sağ altta 'Windows ile Aç' (deaktif)
        ve kırmızı 'Çıkış' butonu."""
        bar = QHBoxLayout()
        bar.setContentsMargins(16, 10, 16, 12)
        bar.setSpacing(10)

        # Dosya yolu / ad göstergesi (sol taraf, uzun ise ellipsis'e girer)
        info = QLabel(self.pdf_path)
        info.setStyleSheet(
            "color:#6b7280; font:12px 'Segoe UI'; padding-right:12px;"
        )
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bar.addWidget(info, 1)

        # "Windows ile Aç" — şu an devre dışı (görünür ama gri).
        # İleride user isterse setEnabled(True) ile aktif edilebilir.
        self.btn_system_open = QPushButton("🪟 Windows ile Aç")
        self.btn_system_open.setToolTip(
            "Şu an devre dışı. PDF'ler yalnızca uygulama içinde açılır."
        )
        self.btn_system_open.setCursor(Qt.PointingHandCursor)
        self.btn_system_open.setStyleSheet(
            "QPushButton { padding:10px 18px; border:1px solid #d1d5db;"
            " background:#ffffff; color:#374151; border-radius:6px;"
            " font:600 13px 'Segoe UI'; }"
            " QPushButton:hover:!disabled { background:#f3f4f6; }"
            " QPushButton:disabled { color:#9ca3af; background:#f9fafb; }"
        )
        self.btn_system_open.setEnabled(enable_system_open)
        self.btn_system_open.clicked.connect(self._on_system_open)
        bar.addWidget(self.btn_system_open)

        # Sağ alt: kırmızı büyük Çıkış butonu
        self.btn_close = QPushButton("✕ Çıkış")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setFixedSize(140, 48)
        self.btn_close.setStyleSheet(
            "QPushButton { background:#dc2626; color:white; border:none;"
            " border-radius:8px; font:700 15px 'Segoe UI'; }"
            " QPushButton:hover { background:#b91c1c; }"
            " QPushButton:pressed { background:#991b1b; }"
        )
        self.btn_close.clicked.connect(self.accept)
        bar.addWidget(self.btn_close)

        # Barı ana layout'a ekle (fixed yükseklik — viewer'ı ezmez)
        bar_widget = QFrame()
        bar_widget.setFixedHeight(72)
        bar_widget.setStyleSheet(
            "QFrame { background:#f9fafb; border-top:1px solid #e5e7eb; }"
        )
        bar_widget.setLayout(bar)
        root.addWidget(bar_widget)

    # ── Slots ──────────────────────────────────────────────────
    def _on_system_open(self):
        """'Windows ile Aç' — yalnızca deaktif değilse çağrılır."""
        if not os.path.exists(self.pdf_path):
            QMessageBox.warning(self, "Dosya Yok",
                                f"PDF bulunamadı:\n{self.pdf_path}")
            return
        try:
            if sys.platform.startswith('win'):
                os.startfile(self.pdf_path)  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', self.pdf_path])
            else:
                subprocess.Popen(['xdg-open', self.pdf_path])
        except Exception as e:
            QMessageBox.critical(self, "Açılamadı",
                                 f"PDF sistem programıyla açılamadı:\n{e}")

    # ── Qt event overrides ─────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        # Modal dialog fullscreen açılsın (native window state).
        # show() sonrası setWindowState ile çağırıyoruz ki geometri
        # doğru hesaplansın.
        if not self.isFullScreen():
            self.showFullScreen()

    def keyPressEvent(self, event):
        """ESC ile kapansın (kullanıcı alışkanlığı)."""
        if event.key() == Qt.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(event)
