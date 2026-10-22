"""
Recipe Management Panel
Interface for managing test recipes with Pressure Decay Method
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QLineEdit, QLabel, QMessageBox, QDialog, 
                             QFormLayout, QComboBox, QDialogButtonBox,
                             QHeaderView, QDoubleSpinBox, QSpinBox, QTextEdit,
                             QScrollArea)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage
import os

from gui.styles import Styles
from gui.recipe_graph_widget import RecipeGraphWidget

class RecipeManagementPanel(QWidget):
    """Panel for managing test recipes"""
    
    # Default test recipe name
    TEST_RECIPE_NAME = "Test Reçetesi"
    
    def __init__(self, database, esp32_comm, auth_manager, audit_manager, parent=None):
        super().__init__(parent)
        self.db = database
        self.esp32 = esp32_comm
        self.auth = auth_manager
        self.audit = audit_manager
        
        self.init_ui()
        self._ensure_test_recipe_exists()
        self.load_recipes()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Recipe List Group
        list_group = QGroupBox("Kayıtlı Reçeteler (Basınç Düşümü Testi)")
        list_group.setStyleSheet(Styles.GROUP_BOX)
        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(15, 25, 15, 15)
        list_layout.setSpacing(10)
        
        # --- Buttons (Top) ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.add_btn = QPushButton("➕ Yeni Reçete")
        self.add_btn.setStyleSheet(Styles.get_button_style("primary"))
        self.add_btn.clicked.connect(self.add_recipe)
        
        self.edit_btn = QPushButton("✏️ Düzenle")
        self.edit_btn.setStyleSheet(Styles.get_button_style("warning"))
        self.edit_btn.clicked.connect(self.edit_recipe)
        
        self.active_btn = QPushButton("✓ Aktif Yap")
        self.active_btn.setStyleSheet(Styles.get_button_style("success"))
        self.active_btn.clicked.connect(self.toggle_active)
        
        self.passive_btn = QPushButton("✗ Pasif Yap")
        self.passive_btn.setStyleSheet(Styles.get_button_style("secondary"))
        self.passive_btn.clicked.connect(self.toggle_passive)
        
        # Permissions — Admin veya Supervisor reçete oluşturabilir/düzenleyebilir
        self.apply_permissions()
        
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.active_btn)
        btn_layout.addWidget(self.passive_btn)
        btn_layout.addStretch()
        
        list_layout.addLayout(btn_layout)
        
        # --- Recipe Table ---
        self.recipe_table = QTableWidget()
        self.recipe_table.setColumnCount(11)
        self.recipe_table.setHorizontalHeaderLabels([
            "ID", "Reçete Adı", "Durum", "Hedef (p2)", "Süre (p7)", "Kabul Ed. Basınç Düşümü (p6)", "Kritik Basınç Sınırı (p8)", "Şişirme (p1)", "Dengele (p3)", "Yeniden Şişirme Eşiği (p4)", "Açıklama"
        ])
        self.recipe_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.recipe_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.recipe_table.setColumnWidth(1, 180)
        self.recipe_table.horizontalHeader().setSectionResizeMode(10, QHeaderView.Stretch)
        self.recipe_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.recipe_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recipe_table.setStyleSheet(Styles.TABLE)
        self.recipe_table.setAlternatingRowColors(True)
        self.recipe_table.itemSelectionChanged.connect(self._on_selection_changed)
        
        list_layout.addWidget(self.recipe_table)
        
        list_group.setLayout(list_layout)
        
        layout.addWidget(list_group)
        self.setLayout(layout)

    def _ensure_test_recipe_exists(self):
        """Ensure the Test Reçetesi exists in the database"""
        recipes = self.db.get_all_recipes()
        if not any(r['name'] == self.TEST_RECIPE_NAME for r in recipes):
            # Create default test recipe
            _user = self.auth.current_user['username'] if self.auth.current_user else 'SYSTEM'
            self.db.create_recipe(
                name=self.TEST_RECIPE_NAME,
                glove_type="Test",
                p1=10, p2=3000, p3=5,
                p4=2800, p5=0, p6=150, p7=30, p8=200,
                description="Varsayılan test reçetesi",
                created_by=_user
            )

    def _on_selection_changed(self):
        """Handle table selection change"""
        pass  # Selection tracking kept for future use

    def load_recipes(self):
        """Load recipes from database"""
        recipes = self.db.get_all_recipes()
        
        # Görev 7: Hayalet reçete "4545" filtreleme
        recipes = [r for r in recipes if r.get('name') != '4545']
        
        self.recipe_table.setRowCount(len(recipes))
        
        for row, r in enumerate(recipes):
            self.recipe_table.setItem(row, 0, QTableWidgetItem(str(r['id'])))
            self.recipe_table.setItem(row, 1, QTableWidgetItem(r['name']))
            
            # Active/Passive status
            is_active = r.get('is_active', True)
            status_item = QTableWidgetItem("Aktif" if is_active else "Pasif")
            status_item.setForeground(Qt.darkGreen if is_active else Qt.gray)
            self.recipe_table.setItem(row, 2, status_item)
            
            # Handle legacy/new fields safely
            # p1-p8 mapping
            p1 = r.get('t1_inflation', 10)
            p2 = r.get('p1_pressure', 3000)
            p3 = r.get('t2_stabilization', 5)
            p4 = r.get('p2_hysteresis', 50)
            p7 = r.get('t3_measurement', 30)
            p6 = r.get('p3_limit', 150)
            p8 = r.get('p8_success_drop', 200)
            
            for col, text in [
                (3, f"{p2} Pa"), (4, f"{p7} sn"), (5, f"{p6} Pa"),
                (6, f"{p8} Pa"), (7, f"{p1} sn"), (8, f"{p3} sn"),
                (9, f"{p4} Pa"),
            ]:
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.recipe_table.setItem(row, col, item)
            self.recipe_table.setItem(row, 10, QTableWidgetItem(r.get('description', '')))

    def get_selected_recipe_id(self):
        selected = self.recipe_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Uyarı", "Lütfen bir reçete seçin.")
            return None
        return int(self.recipe_table.item(selected[0].row(), 0).text())

    def get_selected_recipe_data(self):
        selected = self.recipe_table.selectedItems()
        if not selected:
            return None
        rid = int(self.recipe_table.item(selected[0].row(), 0).text())
        recipes = self.db.get_all_recipes()
        return next((r for r in recipes if r['id'] == rid), None)

    def add_recipe(self):
        dialog = RecipeDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            recipe_name = data.pop('name')  # Remove name from data dict
            # Create recipe with all p1-p8 parameters
            success, result = self.db.create_recipe(
                recipe_name, "Standard", **data
            )
            
            if success:
                self.load_recipes()  # Auto refresh
                self.audit.log_action("RECIPE_CREATED", description=f"Created recipe: {recipe_name}")
            else:
                QMessageBox.critical(self, "Hata", result)

    def edit_recipe(self):
        """Edit selected recipe"""
        recipe = self.get_selected_recipe_data()
        if not recipe:
            return
        
        dialog = RecipeDialog(self, recipe=recipe)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            recipe_name = data.pop('name')
            data['name'] = recipe_name
            success, result = self.db.update_recipe(recipe['id'], data)
            if success:
                self.load_recipes()
                self.audit.log_action("RECIPE_UPDATED", description=f"Updated recipe: {recipe_name}")
            else:
                QMessageBox.critical(self, "Hata", result)

    def toggle_active(self):
        """Set selected recipe to active"""
        recipe = self.get_selected_recipe_data()
        if not recipe:
            return
        
        success, result = self.db.update_recipe(recipe['id'], {'is_active': True})
        if success:
            self.load_recipes()
            self.audit.log_action("RECIPE_ACTIVATED", description=f"Activated recipe: {recipe['name']}")
        else:
            QMessageBox.critical(self, "Hata", result)

    def toggle_passive(self):
        """Set selected recipe to passive"""
        recipe = self.get_selected_recipe_data()
        if not recipe:
            return
        
        success, result = self.db.update_recipe(recipe['id'], {'is_active': False})
        if success:
            self.load_recipes()
            self.audit.log_action("RECIPE_DEACTIVATED", description=f"Deactivated recipe: {recipe['name']}")
        else:
            QMessageBox.critical(self, "Hata", result)

    def apply_permissions(self):
        """Rol tabanlı buton yetkilendirmesi — Admin veya Supervisor aktif."""
        can_manage = self.auth.has_permission('Supervisor')
        self.add_btn.setEnabled(can_manage)
        self.edit_btn.setEnabled(can_manage)
        self.active_btn.setEnabled(can_manage)
        self.passive_btn.setEnabled(can_manage)


class RecipeDialog(QDialog):
    def __init__(self, parent=None, recipe=None):
        super().__init__(parent)
        self.recipe = recipe
        self.setWindowTitle("Reçete Düzenle" if recipe else "Yeni Reçete")
        self.resize(1150, 650)
        self.init_ui()
        
    def init_ui(self):
        main_layout = QHBoxLayout()
        
        # --- LEFT SIDE: inputs ---
        input_widget = QWidget()
        input_layout = QVBoxLayout()
        
        # Header Info (no glove type)
        form_layout = QFormLayout()
        self.name_edit = QLineEdit()
        if self.recipe:
            self.name_edit.setText(self.recipe['name'])
        form_layout.addRow("Reçete Adı:", self.name_edit)
        
        input_layout.addLayout(form_layout)
        
        # Parameter Table
        param_group = QGroupBox("Test Parametreleri (Grafiğe Bakın)")
        param_layout = QVBoxLayout()
        
        self.param_table = QTableWidget()
        self.param_table.setColumnCount(3)
        self.param_table.setHorizontalHeaderLabels(["Parametre", "Açıklama", "Değer"])
        from PyQt5.QtWidgets import QHeaderView
        self.param_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.param_table.setColumnWidth(0, 80)
        self.param_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.param_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.param_table.setColumnWidth(2, 80)
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.setRowCount(7)
        
        # Parameters definition (p1-p8, p5 unused)
        # Default values from "kaan" recipe (1001 Pa target)
        self.params_def = [
            ("p1", "Maksimum Şişirme Süresi", "sn", 120, 't1_inflation'),
            ("p2", "Hedef Test Basıncı", "Pa", 1000, 'p1_pressure'),
            ("p3", "Stabilizasyon Süresi", "sn", 120, 't2_stabilization'),
            ("p4", "Yeniden Şişirme Tetikleme Eşiği", "Pa", 50, 'p2_hysteresis'),
            ("p6", "Kritik Basınç Düşüş Eşiği", "Pa", 150, 'p3_limit'),
            ("p7", "Sızdırmazlık İzleme Süresi", "sn", 30, 't3_measurement'),
            ("p8", "Kabul Edilebilir Basınç Düşüş Limiti", "Pa", 200, 'p8_success_drop')
        ]
        
        for row, (code, desc, unit, default, field) in enumerate(self.params_def):
            item_code = QTableWidgetItem(f"{code} ({unit})")
            item_code.setBackground(Qt.lightGray)
            item_code.setFlags(Qt.ItemIsEnabled)
            self.param_table.setItem(row, 0, item_code)
            
            item_desc = QTableWidgetItem(desc)
            item_desc.setFlags(Qt.ItemIsEnabled)
            self.param_table.setItem(row, 1, item_desc)
            
            sb = QSpinBox()
            sb.setRange(0, 5000)
            if code == "p5":
                sb.setEnabled(False)
            if code == "p7": # Test Duration
                sb.setMaximum(120) # HARD LIMIT: Matching Firmware Rolling Window Size
            val = default
            if self.recipe:
                val = self.recipe.get(field, default)
                if val is None:
                    val = default
            sb.setValue(int(val))
            self.param_table.setCellWidget(row, 2, sb)
            
        param_layout.addWidget(self.param_table)
        param_group.setLayout(param_layout)
        input_layout.addWidget(param_group)
        
        # Description
        input_layout.addWidget(QLabel("Açıklama:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(80)
        if self.recipe:
            self.desc_edit.setText(self.recipe.get('description', ''))
        input_layout.addWidget(self.desc_edit)
        
        # Theoretical Max Duration Info
        self.info_label = QLabel()
        self.info_label.setStyleSheet("""
            QLabel {
                background-color: #E3F2FD;
                border-left: 4px solid #2196F3;
                padding: 8px;
                border-radius: 4px;
                font-size: 11px;
                color: #1565C0;
            }
        """)
        self.info_label.setWordWrap(True)
        input_layout.addWidget(self.info_label)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        input_layout.addWidget(buttons)
        
        input_widget.setLayout(input_layout)
        
        # --- RIGHT SIDE: Interactive Graph ---
        chart_widget = QWidget()
        chart_layout = QVBoxLayout()
        
        self.graph_widget = RecipeGraphWidget()
        chart_layout.addWidget(self.graph_widget)
        
        chart_widget.setLayout(chart_layout)
        
        # Combine
        main_layout.addWidget(input_widget, 40)
        main_layout.addWidget(chart_widget, 60)
        
        self.setLayout(main_layout)
        
        # Connect parameter changes to graph updates
        self._connect_graph_updates()
        self._update_graph_from_params()
        self._update_max_duration_info()
        
    def _connect_graph_updates(self):
        """Connect all parameter spinboxes to graph update"""
        for row in range(7):  # All 7 parameters (p5 yok)
            spinbox = self.param_table.cellWidget(row, 2)
            if spinbox:
                spinbox.valueChanged.connect(self._update_graph_from_params)
                spinbox.valueChanged.connect(self._update_max_duration_info)
    
    def _update_graph_from_params(self):
        """Update graph with current parameter values"""
        try:
            # Reçete parametreleri (table rows):
            # Row 0: p1 - Şişirme Max Süresi (sn)
            # Row 1: p2 - Hedef Basınç (Pa)
            # Row 2: p3 - Dengeleme Süresi (sn)
            # Row 3: p4 - Re-inflate Eşiği (Pa)
            # Row 4: p5 - (Kullanılmıyor)
            # Row 5: p6 - Ani Düşüş Limiti (Pa)
            # Row 6: p7 - Test Süresi (sn)
            # Row 7: p8 - Toplam Düşüş Limiti (Pa)
            
            # Grafik parametreleri:
            # p1: Hedef Basınç (Pa)
            # p2: Hysteresis/Dalgalanma (Pa)
            # p3: Kabul Limiti/Düşüş Limiti (Pa)
            # t1: Şişirme süresi (sn)
            # t2: Dengeleme süresi (sn)
            # t3: Test süresi (sn)
            
            hedef_basinc = self.param_table.cellWidget(1, 2).value()       # p2 → Hedef Basınç (Pa)
            sisirme_sure = self.param_table.cellWidget(0, 2).value()       # p1 → Şişirme Süresi (sn)
            dengeleme_sure = self.param_table.cellWidget(2, 2).value()     # p3 → Dengeleme Süresi (sn)
            reinflate_esigi = self.param_table.cellWidget(3, 2).value()    # p4 → Re-inflate Eşiği (Pa)
            
            p6_esik = self.param_table.cellWidget(4, 2).value()
            test_sure = self.param_table.cellWidget(5, 2).value()
            dusus_limiti = self.param_table.cellWidget(6, 2).value()
            
            # Hysteresis/Salınım: Stabilizasyon süresinde minimum düşeceği değer (re-inflate eşiği)
            salınim = reinflate_esigi
            
            # Grafik güncelle
            self.graph_widget.update_parameters(hedef_basinc, salınim, dusus_limiti, 
                                               sisirme_sure, dengeleme_sure, test_sure)
            
            # Teorik max süreyi de gönder
            teorik_max_sure = int((p6_esik / dusus_limiti) * test_sure) if dusus_limiti > 0 else 0
            self.graph_widget.set_theoretical_max_time(teorik_max_sure)
        except Exception as e:
            print(f"Graph update error: {e}")
    
    def _update_max_duration_info(self):
        """Update theoretical max duration info label"""
        try:
            p6 = self.param_table.cellWidget(4, 2).value()
            p7 = self.param_table.cellWidget(5, 2).value()
            p8 = self.param_table.cellWidget(6, 2).value()
            
            # Validation: p8 should not be less than p6
            if p8 < p6:
                self.info_label.setStyleSheet("""
                    QLabel {
                        background-color: #FFEBEE;
                        border-left: 4px solid #F44336;
                        padding: 8px;
                        border-radius: 4px;
                        font-size: 11px;
                        color: #C62828;
                    }
                """)
                self.info_label.setText(
                    f"⚠️ <b>HATA:</b> Kritik Basınç Sınırı (p8={p8} Pa), Kabul Edilebilir Basınç Düşümü (p6={p6} Pa)'ndan küçük olamaz!<br>"
                    f"<i>Test hiçbir zaman başarılı olamaz çünkü p6 seviyesinde fail olabilir.</i>"
                )
                return
            
            if p8 > 0:
                max_duration = int((p6 / p8) * p7)
                
                # Normal blue info box
                self.info_label.setStyleSheet("""
                    QLabel {
                        background-color: #E3F2FD;
                        border-left: 4px solid #2196F3;
                        padding: 8px;
                        border-radius: 4px;
                        font-size: 11px;
                        color: #1565C0;
                    }
                """)
                
                self.info_label.setText(
                    f"ℹ️ <b>Teorik Maksimum Test Süresi:</b> {max_duration} saniye "
                    f"(= {p6} Pa ÷ {p8} Pa × {p7} sn)<br>"
                    f"<i>Not: Gerçek test süresi genellikle çok daha kısa olur.</i>"
                )
            else:
                self.info_label.setStyleSheet("""
                    QLabel {
                        background-color: #FFF3E0;
                        border-left: 4px solid #FF9800;
                        padding: 8px;
                        border-radius: 4px;
                        font-size: 11px;
                        color: #E65100;
                    }
                """)
                self.info_label.setText(
                    "⚠️ <b>Uyarı:</b> Max Düşüş (p8) değeri 0'dan büyük olmalıdır."
                )
        except Exception as e:
            self.info_label.setText(f"⚠️ Hesaplama hatası: {e}")
        
    def accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Hata", "Lütfen bir reçete adı girin.")
            return

        # p6 ve p8 kontrolü: p8 < p6 engellenecek
        p6 = self.param_table.cellWidget(4, 2).value()
        p8 = self.param_table.cellWidget(6, 2).value()
        if p8 < p6:
            QMessageBox.critical(self, "Hata", f"Kritik Basınç Sınırı (p8={p8} Pa), Kabul Edilebilir Basınç Düşümü (p6={p6} Pa)'ndan küçük olamaz!\nLütfen değerleri düzeltin.")
            return

        # 5 saniyelik geri sayımlı onay dialogu
        confirm_dialog = QDialog(self)
        confirm_dialog.setWindowTitle("Onay")
        confirm_dialog.setMinimumWidth(350)
        dlg_layout = QVBoxLayout(confirm_dialog)
        
        # Uyarı metni
        warn_label = QLabel("⚠️ Emin misiniz?\nBu işlem geri alınamaz.")
        warn_label.setAlignment(Qt.AlignCenter)
        warn_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        dlg_layout.addWidget(warn_label)
        
        # Buton satırı: İptal (sol) - OK (sağ)
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("İptal")
        ok_btn = QPushButton("")
        ok_btn.setEnabled(False)
        
        cancel_btn.setMinimumHeight(36)
        ok_btn.setMinimumHeight(36)
        cancel_btn.setStyleSheet("font-size: 13px;")
        ok_btn.setStyleSheet("font-size: 13px; font-weight: bold;")
        
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        dlg_layout.addLayout(btn_layout)
        
        self._countdown = 5
        ok_btn.setText(f"⏳ {self._countdown}s")
        
        def _tick():
            self._countdown -= 1
            if self._countdown > 0:
                ok_btn.setText(f"⏳ {self._countdown}s")
            else:
                _timer.stop()
                ok_btn.setText("✓ Kaydet")
                ok_btn.setEnabled(True)
        
        _timer = QTimer(confirm_dialog)
        _timer.timeout.connect(_tick)
        _timer.start(1000)
        
        cancel_btn.clicked.connect(confirm_dialog.reject)
        ok_btn.clicked.connect(confirm_dialog.accept)
        
        if confirm_dialog.exec_() == QDialog.Accepted:
            super().accept()
        
    def get_data(self):
        data = {
            'name': self.name_edit.text(),
            'description': self.desc_edit.toPlainText()
        }
        
        # Map directly to DB column names
        data['t1_inflation']     = self.param_table.cellWidget(0, 2).value()
        data['p1_pressure']      = self.param_table.cellWidget(1, 2).value()
        data['t2_stabilization'] = self.param_table.cellWidget(2, 2).value()
        data['p2_hysteresis']    = self.param_table.cellWidget(3, 2).value()
        data['p3_limit']         = self.param_table.cellWidget(4, 2).value()
        data['t3_measurement']   = self.param_table.cellWidget(5, 2).value()
        data['p8_success_drop']  = self.param_table.cellWidget(6, 2).value()
        
        return data
