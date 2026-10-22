"""
Layout Map Visualization
Custom Graphics Items for interactive floor plan
"""

from PyQt5.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, 
                             QGraphicsPixmapItem, QGraphicsItem, QDialog, QVBoxLayout,
                             QFormLayout, QLineEdit, QComboBox, QDialogButtonBox,
                             QMessageBox, QLabel, QMenu, QAction)
from PyQt5.QtCore import Qt, pyqtSignal, QPointF, QRectF, QTimer
from PyQt5.QtGui import QBrush, QPen, QColor, QFont, QPixmap, QPainter
from PyQt5.QtWidgets import QGraphicsTextItem
import os
from utils.app_logger import get_logger

_logger = get_logger("layout_map")

class LayoutMapWidget(QGraphicsView):
    """Interactive map widget"""
    
    port_selected = pyqtSignal(int) # Emits port_id
    port_deleted_signal = pyqtSignal() # Emits when a port is deleted
    
    def __init__(self, database, auth_manager, audit_manager=None, parent=None):
        super().__init__(parent)
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # Visual settings
        self.setRenderHint(QPainter.Antialiasing) if hasattr(Qt, 'Antialiasing') else None
        self.setDragMode(QGraphicsView.NoDrag)
        
        self.background_item = None
        self._loading = False  # True iken setPos DB'ye yazmaz
        
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
        """Tüm portları görsel olarak viewport sınırları içine sığdır (DB'ye yazmaz)"""
        vr = self._get_viewport_scene_rect()
        if vr.isEmpty():
            return
        # 25 view px'lik daire yarıçapını scene koordinatına çevir
        t = self.transform()
        margin = 25.0 / t.m11() if t.m11() > 0 else 25.0
        self._loading = True
        try:
            for item in self.scene.items():
                if not isinstance(item, PortItem) or getattr(item, 'is_deleting', False):
                    continue
                pos = item.pos()
                x = max(vr.left() + margin, min(pos.x(), vr.right() - margin))
                y = max(vr.top() + margin, min(pos.y(), vr.bottom() - margin))
                if abs(x - pos.x()) > 0.5 or abs(y - pos.y()) > 0.5:
                    item.setPos(x, y)
        finally:
            self._loading = False

    def set_background_image(self, path):
        """Set background floor plan — çerçeveye sığdırılır"""
        self.scene.clear()
        if not path or not os.path.exists(path):
            self.scene.addText("Lütfen bir yerleşim planı yükleyin (Sağ Tık > Plan Yükle)")
            return
            
        pixmap = QPixmap(path)
        self.background_item = QGraphicsPixmapItem(pixmap)
        self.background_item.setZValue(-1)
        self.scene.addItem(self.background_item)
        self.setSceneRect(self.background_item.boundingRect())
        
        # Reload ports on top
        self.load_ports()
        self._fit_background()

    def load_ports(self):
        """Load ports from database and sync with scene items (Incremental Update)"""
        try:
            # 1. Get current items in scene (Excluding those already being deleted)
            existing_items = {item.port_id: item for item in self.scene.items() 
                              if isinstance(item, PortItem) and not getattr(item, 'is_deleting', False)}
            
            # 2. Get latest data from database
            ports_data = self.db.get_all_ports()
            db_port_ids = [p['id'] for p in ports_data]
            
            # 3. Add or Update items — DB yazma engelle (pozisyonlar zaten DB'den geliyor)
            self._loading = True
            for port in ports_data:
                p_id = port['id']
                if p_id in existing_items:
                    # Update Existing
                    item = existing_items[p_id]
                    # Extra safety check
                    if getattr(item, 'is_deleting', False):
                        continue
                        
                    item.setPos(port['x_pos'], port['y_pos'])
                    item.name = port['name']
                    item.update_label()
                    item.update_tooltip()
                else:
                    # Add New
                    self.add_visual_port(port)
            
            self._loading = False
            
            # 4. Remove orphan items from scene only (DB already doesn't have them)
            for p_id, item in existing_items.items():
                if p_id not in db_port_ids and not getattr(item, 'is_deleting', False):
                    self._remove_item_from_scene(item)
                    
        except Exception as e:
            self._loading = False
            _logger.error("Incremental Update Error: %s", e)

    def refresh_port_flags(self):
        """Update movable flag on all port items based on current auth state"""
        is_admin = self.auth.has_permission('Admin')
        for item in self.scene.items():
            if isinstance(item, PortItem) and not getattr(item, 'is_deleting', False):
                flags = (QGraphicsItem.ItemIsSelectable |
                         QGraphicsItem.ItemSendsGeometryChanges |
                         QGraphicsItem.ItemIgnoresTransformations)
                if is_admin:
                    flags |= QGraphicsItem.ItemIsMovable
                item.setFlags(flags)

    def highlight_port_by_rfid(self, rfid_tag, device_name):
        """Highlight the port matching this RFID tag with the device's color"""
        if not rfid_tag:
            return
        try:
            for item in self.scene.items():
                if not isinstance(item, PortItem):
                    continue
                if getattr(item, 'is_deleting', False) or item.scene() is None:
                    continue
                if item.rfid and item.rfid.upper() == rfid_tag.upper():
                    item.set_active_device(device_name)
                    item.update_tooltip()
                    return
        except RuntimeError:
            _logger.debug("highlight_port_by_rfid: C++ object already deleted")

    def clear_port_highlight_by_device(self, device_name):
        """Clear highlight for all ports owned by this device (e.g. RFID removed)"""
        try:
            for item in self.scene.items():
                if not isinstance(item, PortItem):
                    continue
                if getattr(item, 'is_deleting', False) or item.scene() is None:
                    continue
                if item.active_device == device_name:
                    item.set_active_device(None)
                    item.update_tooltip()
        except RuntimeError:
            _logger.debug("clear_port_highlight_by_device: C++ object already deleted")

    def add_visual_port(self, port_data):
        """Add a port item to the scene"""
        item = PortItem(
            port_data['id'], 
            port_data['name'], 
            self.db, 
            self.auth,
            rfid=port_data.get('rfid_tag'),
            recipe=port_data.get('recipe_name', port_data.get('recipe_id')),
            parent_view=self
        )
        self.scene.addItem(item)
        old_loading = self._loading
        self._loading = True
        item.setPos(port_data['x_pos'], port_data['y_pos'])
        self._loading = old_loading
        return item

    def schedule_port_deletion(self, item):
        """Sadece scene'den görsel temizlik — DB silmez."""
        self._remove_item_from_scene(item)

    def safe_delete_port(self, item, skip_db=False):
        """
        Tek silme yolu. Sırayla:
        1. Scene'den çıkar
        3. DB'den sil (skip_db=False ise)
        4. Signal emit
        """
        if not item:
            return False
        if getattr(item, 'is_deleting', False):
            return False

        port_id = item.port_id
        rfid_tag = getattr(item, 'rfid', None)
        port_name = getattr(item, 'name', None) or f"Port #{port_id}"

        # 1. Önce C++ tarafını temizle (crash önlemi)
        self._remove_item_from_scene(item)

        # 2. DB'den sil
        if not skip_db:
            self.db.delete_glove_port(port_id)
            # Audit trail: port/RFID silindi
            if self.audit is not None:
                try:
                    has_rfid = rfid_tag and rfid_tag not in ('-', '0x00000000')
                    self.audit.log_action(
                        'RFID_DELETE' if has_rfid else 'PORT_DELETE',
                        table_name='glove_ports',
                        record_id=port_id,
                        old_value=rfid_tag if has_rfid else None,
                        description=(
                            f"RFID/port silindi: {rfid_tag} ({port_name})"
                            if has_rfid else f"Port silindi: {port_name}"
                        ),
                        category='GLT',
                    )
                except Exception:
                    pass

        # 3. Signal
        self.port_deleted_signal.emit()
        return True

    def _remove_item_from_scene(self, item):
        """Item'ı scene'den güvenli şekilde çıkar. DB'ye dokunmaz."""
        if not item or getattr(item, 'is_deleting', False):
            return
        try:
            item.is_deleting = True
            item.setEnabled(False)
            item.setVisible(False)
            item.setFlags(QGraphicsItem.ItemIsSelectable)
            # Scene'den çıkar
            if item.scene() is not None and item.scene() == self.scene:
                self.scene.removeItem(item)
        except RuntimeError:
            _logger.debug("_remove_item_from_scene: C++ object already deleted")


class PortItem(QGraphicsEllipseItem):
    """Draggable circular port representation"""
    
    BASE_COLOR = '#3498db'    # Default Blue (idle)
    ACTIVE_COLOR = '#2ECC71'  # Green (device reading RFID)
    
    def __init__(self, port_id, name, db, auth, rfid=None, recipe=None, parent_view=None):
        # Circle size 50x50
        super().__init__(-25, -25, 50, 50) 
        
        self.port_id = port_id
        self.name = name
        self.db = db
        self.auth = auth
        self.parent_view = parent_view
        self.is_deleting = False
        self.rfid = rfid
        self.recipe_info = recipe
        self.active_device = None  # Which device is using this port
        
        # Appearance - Better Visuals
        self.setBrush(QBrush(QColor(self.BASE_COLOR))) # Base Blue
        self.setPen(QPen(Qt.white, 2)) # White border
        
        # Flags - Only movable if Admin
        flags = (QGraphicsItem.ItemIsSelectable |
                 QGraphicsItem.ItemSendsGeometryChanges |
                 QGraphicsItem.ItemIgnoresTransformations)
        if self.auth.has_permission('Admin'):
            flags |= QGraphicsItem.ItemIsMovable
            
        self.setFlags(flags)
        
        # Label (Number only)
        display_text = name.replace("Port ", "") if "Port " in name else name.split()[0]
        
        # Parent is SELF - Qt handles deletion
        self.label = QGraphicsTextItem(display_text, self)
        self.label.setDefaultTextColor(Qt.white)
        self.label.setFont(QFont("Arial", 14, QFont.Bold)) 
        
        # Center the text
        self.update_label()
        
        # Tooltip
        rfid_text = rfid if rfid else "Yok"
        recipe_text = recipe if recipe else "Yok"
        self.setToolTip(f"Port: {name}\nRFID: {rfid_text}\nReçete: {recipe_text}")

    def paint(self, painter, option, widget=None):
        if self.is_deleting:
            return
        super().paint(painter, option, widget)

    def update_label(self):
        """Update the numeric label display"""
        try:
            if not getattr(self, 'label', None):
                return
            text = self.name.replace("Port ", "") if "Port " in self.name else self.name.split()[0]
            self.label.setPlainText(text)
            rect = self.label.boundingRect()
            self.label.setPos(-rect.width() / 2, -rect.height() / 2)
        except Exception:
            _logger.debug("Label update failed", exc_info=True)

    def update_tooltip(self):
        """Update tooltip if needed (external call)"""
        try:
            # Stronger check: local reference AND scene check
            if not self.db or self.is_deleting:
                return
            if not self.scene(): # Detached items should not update
                return
                
            ports = self.db.get_all_ports()
            port_data = next((p for p in ports if p['id'] == self.port_id), None)
            if port_data:
                rfid = port_data.get('rfid_tag', 'Yok')
                recipe = port_data.get('recipe_name', 'Yok')
                device_text = self.active_device if self.active_device else 'Yok'
                self.setToolTip(f"ID: {self.port_id}\nRFID: {rfid}\nReçete: {recipe}\nCihaz: {device_text}")
        except Exception as e:
            _logger.error("Tooltip update error: %s", e)
    
    def set_active_device(self, device_name):
        """Set the active device using this port and change color"""
        if self.is_deleting:
            return
        self.active_device = device_name
        if device_name:
            self.setBrush(QBrush(QColor(self.ACTIVE_COLOR)))
            self.setPen(QPen(QColor('#FFFFFF'), 3))
        else:
            self.setBrush(QBrush(QColor(self.BASE_COLOR)))
            self.setPen(QPen(Qt.white, 2))
        self.update()
            
    def mouseDoubleClickEvent(self, event):
        """Open edit dialog on double click - Admin Only"""
        if self.is_deleting:
            return
        if self.auth.has_permission('Admin'):
            self.open_properties_dialog()
        else:
            QMessageBox.information(None, "Yetki Yetersiz", "Port özelliklerini değiştirmek için Admin yetkisi gereklidir.")
        super().mouseDoubleClickEvent(event)
        
    def itemChange(self, change, value):
        """Handle movement to save position — portlar arka plan resmi sınırları içinde kalır"""
        if self.is_deleting:
            return super().itemChange(change, value)
            
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            new_pos = value
            # Arka plan resmi sınırlarına clamp et (viewport değil!)
            # Böylece pencere boyutu değişince portlar kaymaz
            scene_rect = self.scene().sceneRect()
            if not scene_rect.isEmpty():
                x = max(scene_rect.left(), min(new_pos.x(), scene_rect.right()))
                y = max(scene_rect.top(), min(new_pos.y(), scene_rect.bottom()))
                return QPointF(x, y)
        elif change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            new_pos = value
            try:
                # Sadece kullanıcı sürüklemesinde DB'ye yaz (_loading sırasında değil)
                view = self.parent_view
                if not view:
                    views = self.scene().views()
                    view = views[0] if views else None
                if not self.is_deleting and view and not getattr(view, '_loading', False):
                    self.db.update_glove_port_position(self.port_id, int(new_pos.x()), int(new_pos.y()))
            except Exception:
                _logger.debug("Position save failed", exc_info=True)
            
        return super().itemChange(change, value)
    
    def mousePressEvent(self, event):
        if self.is_deleting:
            event.ignore()
            return
        super().mousePressEvent(event)
        
    def mouseReleaseEvent(self, event):
        if self.is_deleting:
            event.ignore()
            return
        super().mouseReleaseEvent(event)
        
    def hoverEnterEvent(self, event):
        if self.is_deleting:
            return
        super().hoverEnterEvent(event)
            
    def hoverLeaveEvent(self, event):
        if self.is_deleting:
            return
        super().hoverLeaveEvent(event)
    
    def prepare_for_deletion(self):
        """Prepare item for safe removal from scene"""
        self.is_deleting = True
        self.setFlags(QGraphicsItem.ItemIsSelectable) # Remove Movable flags
    def contextMenuEvent(self, event):
        if self.is_deleting:
            return
        if not self.auth.has_permission('Admin'):
             return
        
        menu = QMenu()
        prop_action = menu.addAction("Özellikler")
        del_action = menu.addAction("Sil")
        
        selected = menu.exec_(event.screenPos())
        
        if selected == prop_action:
            self.open_properties_dialog()
            
        elif selected == del_action:
            reply = QMessageBox.question(None, "Onay", "Bu portu silmek istiyor musunuz?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                scene = self.scene()
                if scene and scene.views():
                    view = scene.views()[0]
                    if hasattr(view, 'safe_delete_port'):
                        view.safe_delete_port(self)

    def open_properties_dialog(self):
        dialog = PortPropertiesDialog(self.port_id, self.db)
        if dialog.exec_() == QDialog.Accepted:
            self.update_tooltip()
            # If name changed, update label (implementation detail: DB update happens in dialog)


class PortPropertiesDialog(QDialog):
    """Dialog to edit port RFID and Recipe"""
    
    def __init__(self, port_id, db, parent=None):
        super().__init__(parent)
        self.port_id = port_id
        self.db = db
        self.setWindowTitle("Port Özellikleri")
        self.setMinimumWidth(300)
        
        self.init_ui()
        self.load_data()
        
    def init_ui(self):
        layout = QFormLayout()
        
        self.name_display = QLabel()
        layout.addRow("Port Adı:", self.name_display)
        
        self.rfid_edit = QLineEdit()
        layout.addRow("RFID Etiketi:", self.rfid_edit)
        
        self.recipe_combo = QComboBox()
        self.load_recipes()
        layout.addRow("Atanan Reçete:", self.recipe_combo)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
        self.setLayout(layout)
    
    def load_recipes(self):
        self.recipe_combo.addItem("Seçiniz...", None)
        recipes = self.db.get_all_recipes()
        for r in recipes:
            self.recipe_combo.addItem(f"{r['name']} ({r['glove_type']})", r['id'])
            
    def load_data(self):
        ports = self.db.get_all_ports()
        port = next((p for p in ports if p['id'] == self.port_id), None)
        if port:
            self.name_display.setText(port['name'])
            self.rfid_edit.setText(port.get('rfid_tag', ''))
            
            recipe_id = port.get('recipe_id')
            if recipe_id:
                index = self.recipe_combo.findData(recipe_id)
                if index >= 0:
                    self.recipe_combo.setCurrentIndex(index)
                    
    def save(self):
        rfid = self.rfid_edit.text()
        recipe_id = self.recipe_combo.currentData()
        
        success, msg = self.db.update_glove_port_details(self.port_id, rfid, recipe_id)
        if success:
            self.accept()
        else:
            QMessageBox.critical(self, "Hata", msg)

