"""Oraps application package (Faz-4).

The Oraps tab is the second top-level application alongside GLT. It is
mounted inside the outer QTabWidget by `gui.main_window`.

Submodules
----------
oraps_main           QTabWidget container with 4 inner tabs.
overview_panel       3D viewer + device info side panel.
batch_panel          Door-lock config management + active batch control.
batch_config_dialog  Modal editor for door configurations.
viewer_3d            QtWebEngine-based three.js viewer widget.
"""

from .oraps_main import OrapsMain

__all__ = ['OrapsMain']
