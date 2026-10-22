"""
Layout Management Panel
Main tab for RFID Layout Mapping
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QMessageBox, QInputDialog, QDialog,
                             QSplitter)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from gui.layout_map import LayoutMapWidget, PortItem
from gui.rfid_panel import RFIDPanel
from gui.port_dialogs import AddPortDialog
import os
import shutil
from gui.styles import Styles

class LayoutPanel(QWidget):
    """Panel hosting the interactive layout map"""
    
    new_rfid_signal = pyqtSignal(dict) # Signal to bridge background thread to GUI
    log_signal = pyqtSignal(str, str) # Message, Color
    
    def __init__(self, database, auth_manager, esp32_comm, audit_manager=None, parent=None):
        super().__init__(parent)
        self.db = database
        self.auth = auth_manager
        self.esp32 = esp32_comm
        self.audit = audit_manager
        
        self.init_ui()
        self.load_background()
        self.apply_permissions()
        
        self.sync_duplicates = [] # Store duplicates found during a single fetch session
        
        # Connect Signal
        self.new_rfid_signal.connect(self._handle_new_rfid_gui)
        
    def init_ui(self):
        # Main Layout
        main_layout = QHBoxLayout() 
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # --- Left Side: Buttons + RFID List (Sidebar) ---
        left_container = QWidget()
        left_container.setFixedWidth(420)
        left_container.setStyleSheet("border-right: 1px solid #E5E7EB; background-color: #F9FAFB;")
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(6, 10, 6, 6)
        left_layout.setSpacing(4)

        # Row 1: Yerleşim Planı Yükle
        self.load_bg_btn = QPushButton("🗺️ Yerleşim Planı Yükle")
        self.load_bg_btn.setStyleSheet(Styles.get_button_style("secondary"))
        self.load_bg_btn.clicked.connect(self.upload_background)
        left_layout.addWidget(self.load_bg_btn)

        # Row 2: Reçete Ata + Seçili Portu Sil
        self.assign_recipe_btn = QPushButton("📝 Reçete Ata")
        self.assign_recipe_btn.clicked.connect(self.assign_recipe_handler)
        self.assign_recipe_btn.setStyleSheet(Styles.get_button_style("success"))
        
        self.delete_selected_btn = QPushButton("🗑️ Seçili Portu Sil")
        self.delete_selected_btn.setStyleSheet(Styles.get_button_style("danger"))
        self.delete_selected_btn.clicked.connect(self.delete_selected_handler)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(4)
        btn_row2.addWidget(self.assign_recipe_btn)
        btn_row2.addWidget(self.delete_selected_btn)
        left_layout.addLayout(btn_row2)

        # RFID List
        self.rfid_sidebar = RFIDPanel(self.db)
        self.rfid_sidebar.setStyleSheet("border: none; background: transparent;")
        left_layout.addWidget(self.rfid_sidebar)

        main_layout.addWidget(left_container)
        
        # --- Right Side: Map only (same as batch panel) ---
        self.map_widget = LayoutMapWidget(self.db, self.auth, self.audit)
        self.map_widget.port_deleted_signal.connect(self.rfid_sidebar.refresh_list)
        main_layout.addWidget(self.map_widget, 1)  # stretch=1

        self.setLayout(main_layout)

    def apply_permissions(self):
        """Enable/Disable UI elements based on user role"""
        is_admin = bool(self.auth.current_user and self.auth.current_user.get('role', '').lower() == 'admin')
        self.assign_recipe_btn.setEnabled(is_admin)
        self.load_bg_btn.setEnabled(is_admin)
        if hasattr(self, 'delete_selected_btn'):
            self.delete_selected_btn.setEnabled(is_admin)
        
        if not is_admin:
            self.assign_recipe_btn.setToolTip("Bu işlem için yönetici yetkisi gereklidir.")
            self.load_bg_btn.setToolTip("Bu işlem için yönetici yetkisi gereklidir.")
        
        # Update port drag flags for existing items
        if hasattr(self, 'map_widget'):
            self.map_widget.refresh_port_flags()

    def _handle_new_rfid_gui(self, tag_data):
        """
        Called by signal on Main GUI Thread. Direct and Simple.
        """
        rfid = tag_data.get('rfid')
        port_num = tag_data.get('port')
        
        if not rfid:
            return
        
        # Görev 6: Port 0 ise sessizce bypass — log bile düşürme
        if port_num == 0 or port_num == '0':
            return

        # 1. Check if it exists in DB
        ports = self.db.get_all_ports()
        existing = next((p for p in ports if p.get('rfid_tag') == rfid), None)

        if existing:
            # USER REQUEST: Specific warning for existing tags
            warn_msg = f"{rfid} zaten kayıtlı ({existing.get('name')})"
            self.log_signal.emit(f"UYARI: {warn_msg}. Yeni port eklemek için önce eskisini silmelisiniz!", "orange")
            self.sync_duplicates.append(warn_msg)
            self.refresh_map()
            return

        # 2. Add New Port - DISABLED (User Request)
        # self.log_signal.emit(f"Yeni Veri: {rfid} kaydediliyor...", "blue")
        # Logic removed to prevent spam/conflicts.
        self.log_signal.emit(f"Okunan Tag: {rfid} (Port {port_num}) - Kayıt için arayüzü kullanın.", "blue")
        
        # Auto-registration logic REMOVED.
        # Users must manually register ports using the 'Port Kaydet' button.

    def delete_selected_handler(self):
        """Delete only the selected ports from the sidebar list"""
        is_admin = bool(self.auth.current_user and self.auth.current_user.get('role', '').lower() == 'admin')
        if not is_admin:
            QMessageBox.warning(self, "Yetki Hatası", "Bu islem icin yonetici yetkisi gereklidir.")
            return

        # Batch aktifken port silmeye izin verme
        active_batch = self.db.get_active_batch()
        if active_batch:
            QMessageBox.warning(self, "Batch Aktif",
                                f"'{active_batch['batch_name']}' batch'i aktifken port silinemez.\n"
                                "Önce batch'i tamamlayın veya iptal edin.")
            return

        selected_items = self.rfid_sidebar.table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Seçim Yok", "Lütfen listeden silmek istediğiniz portu/portları seçin.")
            return

        # QMessageBox ÖNCE verileri cache'le — dialog sırasında tablo değişebilir
        rows = sorted(list(set(item.row() for item in selected_items)), reverse=True)
        port_ids = []
        for row in rows:
            tbl_item = self.rfid_sidebar.table.item(row, 1)
            if tbl_item is None:
                continue
            port_ids.append(tbl_item.data(Qt.UserRole))

        if not port_ids:
            return

        reply = QMessageBox.question(self, "Seçilenleri Sil", 
                                   f"Seçili {len(port_ids)} adet portu silmek istediğinize emin misiniz?",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                                   
        if reply == QMessageBox.Yes:
            # Scene item'larını bul ve safe_delete_port ile tek yoldan sil
            success_count = 0
            deleted_rfids = []
            for port_id in port_ids:
                # Scene'de bu port_id'ye ait item'ı bul
                target_item = None
                for scene_item in self.map_widget.scene.items():
                    if isinstance(scene_item, PortItem) and scene_item.port_id == port_id:
                        target_item = scene_item
                        break

                if target_item:
                    rfid_tag = getattr(target_item, 'rfid', None)
                    if self.map_widget.safe_delete_port(target_item):
                        success_count += 1
                        if rfid_tag and rfid_tag != '-' and rfid_tag != '0x00000000':
                            deleted_rfids.append(rfid_tag)
                else:
                    # Scene'de item yok ama DB'de olabilir — direkt DB sil
                    if self.db.delete_glove_port(port_id):
                        success_count += 1
                        if self.audit is not None:
                            try:
                                self.audit.log_action(
                                    'PORT_DELETE',
                                    table_name='glove_ports',
                                    record_id=port_id,
                                    description=f"Port silindi (#{port_id})",
                                    category='GLT',
                                )
                            except Exception:
                                pass
            
            # Silinen tag'ları tüm slave'lere bildir
            if deleted_rfids and self.esp32 and self.esp32.is_connected:
                slaves = self.esp32.slave_devices
                for slave in slaves:
                    slave_name = slave.get('name')
                    if slave_name:
                        for rfid in deleted_rfids:
                            del_cmd = f'{{"cmd":"DELETE_TAG", "rfid":"{rfid}"}}'
                            self.esp32.send_command(f"send {slave_name} {del_cmd}")
                self.log_signal.emit(f"{len(deleted_rfids)} tag silme komutu tüm cihazlara gönderildi.", "blue")
            
            # DB ve scene zaten temiz — sadece sidebar'ı güncelle
            self.rfid_sidebar.refresh_list()
            if success_count > 0:
                self.log_signal.emit(f"{success_count} port başarıyla silindi.", "green")
            else:
                self.log_signal.emit("Portlar silinemedi.", "red")

    def load_background(self):
        path = self.db.get_layout_image()
        if path:
            self.map_widget.set_background_image(path)
            
    def upload_background(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Plan Seç", "", "Resim Dosyaları (*.png *.jpg *.jpeg)")
        if file_path:
            # Yazılabilir dizine kaydet (frozen: %LOCALAPPDATA%, dev: CWD/assets)
            from utils.storage_config import _get_writable_data_dir
            _data = _get_writable_data_dir()
            assets_dir = os.path.join(_data, "assets") if _data else "assets"
            os.makedirs(assets_dir, exist_ok=True)
                
            filename = os.path.basename(file_path)
            dest_path = os.path.join(assets_dir, filename)
            
            try:
                shutil.copy(file_path, dest_path)
                self.db.save_layout_image(dest_path)
                self.load_background()
            except Exception as e:
                QMessageBox.critical(self, "Hata", f"Resim yüklenemedi: {e}")

    def on_new_rfid_detected(self, tag_data):
        """Thread-safe wrapper for RFID detection"""
        # Emit signal so _handle_new_rfid_gui runs on Main Thread
        self.new_rfid_signal.emit(tag_data)

    def highlight_port(self, rfid_tag, device_name):
        """Highlight port on map by RFID tag (called from esp_now_control)"""
        if hasattr(self, 'map_widget'):
            self.map_widget.highlight_port_by_rfid(rfid_tag, device_name)

    def clear_port_highlight(self, device_name):
        """Clear port highlight for a device (RFID removed)"""
        if hasattr(self, 'map_widget'):
            self.map_widget.clear_port_highlight_by_device(device_name)

    def assign_recipe_handler(self):
        """Bulk assign a recipe to selected ports"""
        is_admin = bool(self.auth.current_user and self.auth.current_user.get('role', '').lower() == 'admin')
        if not is_admin:
            QMessageBox.warning(self, "Yetki Hatası", "Bu islem icin yonetici yetkisi gereklidir.")
            return

        selected_items = self.rfid_sidebar.table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Seçim Yok", "Lütfen reçete atamak istediğiniz portları listeden seçin.")
            return

        # Get unique port IDs from selection
        rows = list(set(item.row() for item in selected_items))
        port_ids = []
        port_names = []
        for row in rows:
            name_item = self.rfid_sidebar.table.item(row, 1)
            port_ids.append(name_item.data(Qt.UserRole))
            port_names.append(name_item.text())

        # Fetch recipes
        recipes = self.db.get_all_recipes()
        # Sadece aktif reçeteler görünsün
        recipes = [r for r in recipes if r.get('is_active', 1) and r.get('name') != '4545']
        if not recipes:
            QMessageBox.warning(self, "Reçete Yok", "Sistemde kayıtlı reçete bulunamadı. Lütfen önce Reçete Yönetimi'nden reçete ekleyin.")
            return

        recipe_names = [r['name'] for r in recipes]
        
        recipe_name, ok = QInputDialog.getItem(self, "Reçete Ata", 
                                             f"Seçili {len(port_ids)} porta atanacak reçeteyi seçin:", 
                                             recipe_names, 0, False)
        
        if ok and recipe_name:
            selected_recipe = next(r for r in recipes if r['name'] == recipe_name)
            recipe_id = selected_recipe['id']
            
            success_count = 0
            for p_id in port_ids:
                # Re-finding rows to get RFID
                row = next(r for r in rows if self.rfid_sidebar.table.item(r, 1).data(Qt.UserRole) == p_id)
                rfid_tag = self.rfid_sidebar.table.item(row, 1).data(Qt.UserRole + 1)
                port_text = self.rfid_sidebar.table.item(row, 1).text()
                
                # Extract port number from "Port 3/5" etc.
                from gui.esp_now_control import port_from_db_name
                port_val = port_from_db_name(port_text)
                
                success, _ = self.db.update_glove_port_details(p_id, rfid_tag, recipe_id)
                if success:
                    success_count += 1
                    # --- BROADCAST TO SLAVES ---
                    if self.esp32 and self.esp32.is_connected:
                        # Format: infMaxT-infP-stabT-reinfTh-maxReinf-failTh-testDur-succDropP
                        # Mapping (Example): t1-p1-t2-p2-2-p3-t3-p3
                        r = selected_recipe
                        recipe_str = f"{r.get('t1_inflation', 10)}-{r.get('p1_pressure', 500)}-{r.get('t2_stabilization', 10)}-{r.get('p2_hysteresis', 50)}-{r.get('p3_limit', 100)}-{r.get('t3_measurement', 60)}-{r.get('p8_success_drop', 100)}"
                        
                        # Loop through all known slaves
                        slaves = self.esp32.slave_devices
                        for slave in slaves:
                            sender_name = slave.get('name')
                            if sender_name:
                                # SET_TAG_CONFIG command — port_val already encoded
                                cmd = f'{{"cmd":"SET_TAG_CONFIG", "rfid":"{rfid_tag}", "port":{port_val}, "recipe":"{recipe_str}", "recipe_name":"{recipe_name}"}}'
                                self.esp32.send_command(f"send {sender_name} {cmd}")
                                self.log_signal.emit(f"Donanım Güncelleniyor: {sender_name} ({rfid_tag})", "blue")
            
            if success_count > 0:
                self.log_signal.emit(f"{success_count} porta '{recipe_name}' reçetesi atandı ve cihazlara gönderildi.", "green")
                self.refresh_map()
                QMessageBox.information(self, "Başarılı", f"{success_count} porta '{recipe_name}' reçetesi başarıyla atandı ve cihazlara gönderildi.")
            else:
                QMessageBox.warning(self, "Hata", "Reçete atanamadı.")

    def fetch_rfids_handler(self):
        """
        Manual Trigger: Request all RFIDs from all connected devices.
        This forces slaves to resend their list.
        """
        if not self.esp32 or not self.esp32.is_connected:
            QMessageBox.warning(self, "Bağlantı Hatası", "Cihaz bağlı değil.")
            return

        self.sync_duplicates = [] # Reset for new session
        slaves = self.esp32.slave_devices
        if not slaves:
            self.esp32.get_slave_list() # Try to update list first
            QMessageBox.information(self, "Bilgi", "Cihaz listesi güncelleniyor, lütfen tekrar deneyin.")
            return

        count = 0
        for slave in slaves:
            name = slave.get('name')
            if name:
                # 1. Reset sync status to force resend
                cmd_reset = f"send {name} {{\"cmd\":\"RESET_RFIDS_SYNC\"}}"
                self.esp32.send_command(cmd_reset)
                
                # 2. Request new items immediately (via timer to allow processing)
                QTimer.singleShot(300, lambda n=name: self.esp32.send_command(f"send {n} {{\"cmd\":\"GET_NEW_RFIDS\"}}"))
                count += 1
        
        if count > 0:
            QMessageBox.information(self, "İşlem Başlatıldı", f"{count} cihazdan veriler isteniyor.\nLütfen bekleyin.")
        else:
            QMessageBox.warning(self, "Uyarı", "Görünen cihaz yok.")

    def on_sync_complete(self, sender_name, count):
        """Called by ESPNowControl when sync finishes"""
        if self.sync_duplicates:
            title = f"Senkronizasyon Raporu ({sender_name})"
            msg = f"Tarama tamamlandı. {count} port bildirildi.\n\n"
            msg += "🚨 AŞAĞIDAKİ KAYITLAR ZATEN MEVCUT (EKLENMEDİ):\n"
            msg += "--------------------------------------------------\n"
            msg += "\n".join([f"• {x}" for x in self.sync_duplicates])
            msg += "\n\n⚠️ Bu portları güncellemek için listeden silip tekrar taratın."
            
            QMessageBox.critical(self, title, msg)
            self.sync_duplicates = [] # Clear after showing

    def refresh_map(self):
        self.map_widget.load_ports()
        self.rfid_sidebar.refresh_list()
