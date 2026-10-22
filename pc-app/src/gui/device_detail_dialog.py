"""
Device Detail Dialog
Real-time test monitoring and device information display
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QGroupBox, QFrame, QPushButton, QWidget, QGridLayout)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from datetime import datetime


class DeviceDetailDialog(QDialog):
    """
    Detail view for individual device showing real-time test data
    Features:
    - Live pressure graph (time vs pressure)
    - Current phase information
    - Battery status
    - Seal pressure
    - Test timing
    """
    
    def __init__(self, device_name, device_mac, esp32_comm, database, history_buffer=None, parent=None):
        super().__init__(parent)
        self.device_name = device_name
        self.device_mac = device_mac
        self.esp32 = esp32_comm
        self.db = database
        
        # Test data
        self.current_phase = "Unknown"
        self.time_elapsed = 0
        self.total_time = 0
        self.battery = 100
        self.glove_pressure = 0
        self.seal_active = False
        self.test_start_time = None
        self.test_active = False
        self.test_result = None
        self.testing_start_pressure = None  # Actual pressure at start of measurement phase
        self._graph_frozen = False  # True when test is done - graph stops updating
        
        # Graph data (Shared Buffer)
        if history_buffer is None:
            history_buffer = {'time': [], 'pressure': [], 'start_time': None}
            
        self.history_buffer = history_buffer
        # Explicit reference definition preventing copy issues
        self.time_data = self.history_buffer.get('time', [])
        self.pressure_data = self.history_buffer.get('pressure', [])
        
        self.max_points = 4000 # Increased limit matching buffer logic
        
        self.setWindowTitle(f"Device Monitor - {device_name}")
        self.resize(700, 600)
        self.init_ui()
        
        # Update timer (1Hz)
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(1000)
        
        # Request initial status from device
        self.request_initial_status()
        
        # Pencere açılır açılmaz birikmiş geçmiş veriyi hemen çiz
        QTimer.singleShot(100, self.update_graph_only)
        
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)
        
        # --- Header (Compact) ---
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3B82F6, stop:1 #2563EB);
                border-radius: 8px;
            }
        """)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(15, 5, 15, 5)
        
        self.device_title = QLabel(f"📡 {self.device_name}")
        self.device_title.setStyleSheet("font-size: 16px; font-weight: bold; color: white;")
        header_layout.addWidget(self.device_title)
        
        header_layout.addStretch()
        
        self.device_id_label = QLabel(f"ID: {self.device_mac[-8:] if len(self.device_mac) >= 8 else self.device_mac}")
        self.device_id_label.setStyleSheet("font-size: 10px; color: #E0E7FF; margin-left: 10px;")
        header_layout.addWidget(self.device_id_label)
        
        header.setLayout(header_layout)
        layout.addWidget(header)
        
        # ... (rest of UI code remains same until update_display)
        
        # --- Live Pressure Graph ---
        graph_group = QGroupBox("Basınç / Zaman Grafiği (Eldiven)")
        graph_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        graph_layout = QVBoxLayout()
        graph_layout.setContentsMargins(10, 10, 10, 0)
        graph_layout.setSpacing(2)
        
        # Matplotlib figure for real-time pressure graph
        from PyQt5.QtWidgets import QSizePolicy
        self.figure = Figure(figsize=(6, 3.5), facecolor='#F9FAFB')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.figure.add_subplot(111)
        self._setup_graph()
        
        graph_layout.addWidget(self.canvas)
        
        # Additional Info Label (Active RFID & Recipe)
        self.graph_info_label = QLabel("Aktif RFID: -")
        self.graph_info_label.setStyleSheet("font-size: 10px; color: #555; margin-top: 4px;")
        self.graph_info_label.setAlignment(Qt.AlignCenter)
        graph_layout.addWidget(self.graph_info_label)

        # --- Phase 6: Recipe Info Panel ---
        self.recipe_label = QLabel("Aktif Reçete: Bekleniyor...")
        self.recipe_label.setAlignment(Qt.AlignCenter)
        self.recipe_label.setWordWrap(True)
        self.recipe_label.setStyleSheet("""
            QLabel {
                background-color: #F3F4F6;
                color: #1F2937;
                border: 1px solid #E5E7EB;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                font-family: Consolas, monospace;
            }
        """)
        graph_layout.addWidget(self.recipe_label)
        
        graph_group.setLayout(graph_layout)
        layout.addWidget(graph_group, 1)   # stretch=1: pencere büyüyünce grafik büyür
        
        # --- Info Panel (Grid) ---
        info_group = QGroupBox("Test Bilgileri")
        info_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
        """)
        info_layout = QGridLayout()
        info_layout.setSpacing(10)
        info_layout.setContentsMargins(12, 12, 12, 12)
        
        # Phase Info
        phase_label = QLabel("📍 Aşama:")
        phase_label.setStyleSheet("font-weight: 600; font-size: 11px;")
        self.phase_value = QLabel("Bekliyor")
        self.phase_value.setStyleSheet("font-size: 12px; color: #3B82F6; font-weight: bold;")
        info_layout.addWidget(phase_label, 0, 0)
        info_layout.addWidget(self.phase_value, 0, 1)
        
        # Time Info
        time_label = QLabel("⏱️ Süre:")
        time_label.setStyleSheet("font-weight: 600; font-size: 11px;")
        self.time_value = QLabel("0s")
        self.time_value.setStyleSheet("font-size: 12px; color: #10B981; font-weight: bold;")
        info_layout.addWidget(time_label, 1, 0)
        info_layout.addWidget(self.time_value, 1, 1)
        
        # Battery
        battery_label = QLabel("🔋 Batarya:")
        battery_label.setStyleSheet("font-weight: 600; font-size: 11px;")
        self.battery_value = QLabel("100%")
        self.battery_value.setStyleSheet("font-size: 12px; color: #10B981; font-weight: bold;")
        info_layout.addWidget(battery_label, 0, 2)
        info_layout.addWidget(self.battery_value, 0, 3)
        
        # Glove Pressure
        pressure_label = QLabel("📊 Eldiven Basıncı:")
        pressure_label.setStyleSheet("font-weight: 600; font-size: 11px;")
        self.pressure_value = QLabel("0 Pa")
        self.pressure_value.setStyleSheet("font-size: 12px; color: #F59E0B; font-weight: bold;")
        info_layout.addWidget(pressure_label, 1, 2)
        info_layout.addWidget(self.pressure_value, 1, 3)
        
        info_group.setLayout(info_layout)
        from PyQt5.QtWidgets import QSizePolicy as SP
        info_group.setSizePolicy(SP.Expanding, SP.Fixed)
        layout.addWidget(info_group, 0)   # stretch=0: sabit yükseklik
        
        # --- Status Bar ---
        status_layout = QHBoxLayout()
        self.status_indicator = QLabel("● İzleniyor")
        self.status_indicator.setStyleSheet("font-size: 11px; color: #10B981; font-weight: 600;")
        status_layout.addWidget(self.status_indicator)
        status_layout.addStretch()
        
        # Full screen button
        self.fullscreen_btn = QPushButton("⛶ Tam Ekran")
        self.fullscreen_btn.setCheckable(True)
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        self.fullscreen_btn.setStyleSheet("""
            QPushButton {
                background-color: #6B7280;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #4B5563; }
        """)
        status_layout.addWidget(self.fullscreen_btn)
        
        close_btn = QPushButton("Kapat")
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #2563EB; }
        """)
        status_layout.addWidget(close_btn)
        
        layout.addLayout(status_layout)
        
        self.setLayout(layout)

    def toggle_fullscreen(self):
        """Toggle full screen mode for the dialog"""
        if self.fullscreen_btn.isChecked():
            self.showFullScreen()
            self.fullscreen_btn.setText("🗗 Küçült")
        else:
            self.showNormal()
            self.fullscreen_btn.setText("⛶ Tam Ekran")

    def send_recipe(self):
        """Show recipe selection dialog and send parameters"""
        from PyQt5.QtWidgets import QInputDialog
        
        recipes = self.db.get_all_recipes()
        # Filter only active recipes
        active_recipes = [r for r in recipes if r.get('is_active', True)]
        
        if not active_recipes:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Hata", "Hiç aktif kayıtlı reçete yok!")
            return
            
        items = [f"{r['name']} (ID: {r['id']})" for r in active_recipes]
        item, ok = QInputDialog.getItem(self, "Reçete Seç", "Gönderilecek Reçete:", items, 0, False)
        
        if ok and item:
            # Parse ID
            import re
            match = re.search(r'\(ID: (\d+)\)', item)
            if match:
                rid = int(match.group(1))
                recipe = next((r for r in recipes if r['id'] == rid), None)
                if recipe:
                    # Construct recipe string
                    # Format: inflationMax-inflationPascal-stabilization-reinflate-maxReinflate-fail-duration-successDrop
                    # Mapping fields:
                    # P1 = inflationPascal
                    # T1 = inflationMaxTime (approx)
                    # T2 = stabilizationTime
                    # P2 = reinflateThreshold (Hysteresis?) - Let's assume P1 - P2
                    # T3 = testDuration
                    # P3 = failThreshold (Limit)
                    
                    # Using logical mapping from Recipe Dialog fields:
                    # inflationMax = T1
                    # inflationPascal = P1
                    # stabilization = T2
                    # reinflateThreshold = P1 - 200 (Default safety?) or map to P2? 
                    # Let's map strict from DB fields:
                    infMax = int(recipe.get('t1_inflation', 10))
                    infPas = int(recipe.get('p1_pressure', 3000))
                    stabTime = int(recipe.get('t2_stabilization', 5))
                    
                    # Reinflate logic not explicitly in DB, defaulting or using P2 as delta
                    reinfThres = infPas - int(recipe.get('p2_hysteresis', 50)) 
                    maxReinf = 3 # Hardcoded or add to DB later
                    
                    failThres = int(recipe.get('p3_limit', 2000))
                    duration = int(recipe.get('t3_measurement', 10))
                    succDrop = int(recipe.get('p8_success_drop', 200))
                    
                    recipe_str = f"{infMax}-{infPas}-{stabTime}-{reinfThres}-{failThres}-{duration}-{succDrop}"
                    
                    # Send command
                    self.esp32.set_recipe(self.device_name, recipe_str)
                    
                    # Ask to clear RFID New flag too?
                    # Optionally we can do it here if needed
                    
                    from PyQt5.QtWidgets import QMessageBox
                    QMessageBox.information(self, "Başarılı", f"Reçete gönderildi!\n{recipe_str}")

    def _setup_graph(self):
        """Setup matplotlib graph"""
        self.ax.set_xlabel('Zaman (s)', fontsize=9)
        self.ax.set_ylabel('Basınç (Pa)', fontsize=9)
        self.ax.set_title('Gerçek Zamanlı Basınç', fontsize=10)
        self.ax.grid(True, alpha=0.3)
        self.ax.set_facecolor('#FAFAFA')
        
        from matplotlib.lines import Line2D
        self.line = Line2D([], [], color='#2563EB', linewidth=2.5, label='Basinc')
        self.ax.add_line(self.line)
        
        # Limit Lines (Will be updated dynamically based on Recipe)
        self.target_line = self.ax.axhline(y=2000, color='#FFD700', linestyle='--', linewidth=1.5, label='Hedef') # Yellow dashed
        self.fail_line = self.ax.axhline(y=1000, color='#FF0000', linestyle='-', linewidth=2, label='Limit')   # Red solid
        
        # Determine initial Y-axis limits dynamically from the recipe if it exists, otherwise default 0-2400
        recipe = self.history_buffer.get('recipe', {})
        target = float(recipe.get('p2', 2000)) if recipe.get('p2') else 2000
        self.ax.set_ylim(0, target * 1.2)
        self.ax.set_xlim(0, 10)  # Give an initial 10-second empty view instead of 0 to 1
        
        # Legend — Zaman (s) etiketinin hemen altına sabitlenmiş
        self.ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.20),
                       ncol=3, fontsize=7, handlelength=1.2, borderpad=0.4, framealpha=0.85)
        
        # Eksenler aşağıya uzasın (grafik alanı büyür), legend canvas dibine yapışık
        self.figure.subplots_adjust(left=0.12, right=0.97, top=0.92, bottom=0.22)
        
    def _update_graph(self):
        """Update pressure graph with new data and style"""
        if len(self.time_data) > 0:
            self.line.set_data(self.time_data, self.pressure_data)
            
            # --- Dynamic Limit Lines from Real Recipe ---
            recipe = self.history_buffer.get('recipe', {})
            if recipe:
                # P2 = Target Pressure (Yellow)
                p2_target = float(recipe.get('p2', 0))
                # P8 = Max Düşüş. RED LINE = p2 - p8
                p6_fail_thres = float(recipe.get('p6', 0))
                p8_max_drop = float(recipe.get('p8', 0))
                
                
                if p2_target > 0:
                    self.target_line.set_ydata([p2_target])
                    self.target_line.set_label(f'Hedef: {int(p2_target)} Pa')
                    
                    ref_p = self.testing_start_pressure if self.testing_start_pressure is not None else p2_target
                    fail_level = ref_p - p8_max_drop
                    self.fail_line.set_ydata([fail_level])
                    self.fail_line.set_label(f'Limit: {int(fail_level)} Pa')
                    
                    self.ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.20),
                                   ncol=3, fontsize=7, handlelength=1.2, borderpad=0.4, framealpha=0.85)

                # --- Phase 6: Update Recipe Label ---
                recipe_text = (
                    f"Aktif Reçete: Şişirme: {recipe.get('p1',0)}sn | "
                    f"Hedef: {int(p2_target)} Pa | "
                    f"Stabilizasyon: {recipe.get('p3',0)}sn | "
                    f"İzleme Süresi: {recipe.get('p7',0)}sn | "
                    f"Kritik Düşüş: {int(p6_fail_thres)} Pa | "
                    f"Düşüş Limiti: {recipe.get('p8',0)} Pa"
                )
                self.recipe_label.setText(recipe_text)

            self.ax.relim()
            
            # Enforce 0-based Y-axis and ensure target is visible
            target = 100
            if recipe and recipe.get('p2'):
                target = float(recipe.get('p2', 0))
            max_p = max(self.pressure_data) if len(self.pressure_data) > 0 else 0
            max_y = max(max_p, target)
            self.ax.set_ylim(0, max_y * 1.2)
            
            self.ax.autoscale_view(scaley=False)
            self.canvas.draw_idle()

    def update_graph_only(self):
        try:
            buf_frozen = self.history_buffer.get('frozen', False)

            # If frozen and we already drew the final frame → do nothing
            if buf_frozen and self._graph_frozen:
                return

            # If just became unfrozen (new test started) → reset frozen flag
            if not buf_frozen:
                self._graph_frozen = False

            # --- Update RFID / Active Recipe labels from buffer ---
            current_rfid = self.history_buffer.get('current_rfid', '')
            current_recipe_name = self.history_buffer.get('current_recipe_name', '')
            current_port = self.history_buffer.get('current_port', '')

            if current_rfid and current_rfid != '0x00000000':
                self.graph_info_label.setText(
                    f"Aktif RFID: {current_rfid}  |  Port: {current_port}  |  Reçete: {current_recipe_name}"
                )
            else:
                self.graph_info_label.setText("Aktif RFID: -")

            # Update recipe label and limit lines from buffer recipe data
            recipe = self.history_buffer.get('recipe', {})
            if recipe and recipe.get('p2'):
                p2_target = float(recipe.get('p2', 0))
                p6_fail = float(recipe.get('p6', 0))
                p8_max_drop = float(recipe.get('p8', 0))
                recipe_text = (
                    f"Aktif Reçete: Şişirme: {recipe.get('p1',0)}sn | "
                    f"Hedef: {int(p2_target)} Pa | "
                    f"Stabilizasyon: {recipe.get('p3',0)}sn | "
                    f"İzleme Süresi: {recipe.get('p7',0)}sn | "
                    f"Kritik Düşüş: {int(p6_fail)} Pa | "
                    f"Düşüş Limiti: {recipe.get('p8',0)} Pa"
                )
                self.recipe_label.setText(recipe_text)
                if p2_target > 0:
                    self.target_line.set_ydata([p2_target])
                    self.target_line.set_label(f'Hedef: {int(p2_target)} Pa')
                    ref_p = self.testing_start_pressure if self.testing_start_pressure is not None else p2_target
                    fail_level = ref_p - p8_max_drop
                    self.fail_line.set_ydata([fail_level])
                    self.fail_line.set_label(f'Limit: {int(fail_level)} Pa')
                    self.ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.20),
                                   ncol=3, fontsize=7, handlelength=1.2, borderpad=0.4, framealpha=0.85)
            elif current_recipe_name:
                self.recipe_label.setText(f"Aktif Reçete: {current_recipe_name}")

            # --- Update graph line ---
            # Always read fresh references directly from buffer (avoids stale list refs)
            t_data = list(self.history_buffer.get('time', []))
            p_data = list(self.history_buffer.get('pressure', []))
            if len(t_data) > 1 and len(t_data) == len(p_data):
                self.line.set_data(t_data, p_data)
                self.ax.set_xlim(t_data[0], t_data[-1] + 1)

                # Enforce 0-based Y-axis
                target = 100
                if recipe and recipe.get('p2'):
                    target = float(recipe.get('p2', 0))
                max_p = max(p_data) if len(p_data) > 0 else 0
                max_y = max(max_p, target)
                self.ax.set_ylim(0, max_y * 1.2)

                self.ax.relim()
                self.ax.autoscale_view(scaley=False)
                self.canvas.draw_idle()

            # Mark graph as frozen after final draw
            if buf_frozen:
                self._graph_frozen = True
        except Exception as e:
            pass
        
    def update_test_data(self, data):
        """Update with real-time test data from ESP32"""
        try:
            if data.get('device') != self.device_name:
                return
            
            # Map ESP32 phase names to dialog phase names
            phase_mapping = {
                'mounting': 'mounting',
                'inflation': 'inflation',
                'stabilization': 'stabilization',
                'testing': 'measurement',
                'complete': 'complete',
                'finished': 'complete',   # ESP32 sends 'finished' when test ends
                'unknown': 'unknown'
            }
            esp_phase = data.get('phase', 'unknown')
            self.current_phase = phase_mapping.get(esp_phase, 'unknown')
            
            print(f"[DIALOG] update_test_data() - phase: {esp_phase} -> {self.current_phase}, test_status: {data.get('test_status', 'active')}")
            
            self.battery = data.get('battery', 100)
            self.glove_pressure = data.get('glove_pressure', data.get('pressure', 0))
            self.seal_active = data.get('seal_active', False)
            
            # Capture pressure at the START of measurement phase for dynamic limit line
            if self.current_phase == 'measurement' and self.testing_start_pressure is None:
                self.testing_start_pressure = self.glove_pressure
            
            # Check if test is completed
            test_status = data.get('test_status', 'active')
            
            # Test is "active" (timer counts) from mount onwards, excluding finished state
            actual_test_phases = ['mounting', 'inflation', 'stabilization', 'measurement']
            self.test_active = (self.current_phase in actual_test_phases)
            
            # If test completed, store result
            # ESP32 sends phase='finished' + result='PASS'/'FAIL' when test ends
            if test_status == 'completed' or esp_phase == 'finished':
                self.test_result = data.get('result', 'UNKNOWN')
                self.current_phase = 'complete'
                self.seal_active = False
                self.test_active = False
                self._graph_frozen = True  # Freeze graph at final state
                print(f"[DIALOG] Test tamamlandı! Result: {self.test_result}, Phase: {self.current_phase}")
            
            self.total_time = data.get('total_time', 0)
            
            # --- Timing: use ESP32 as source of truth ---
            # test_elapsed_sec = seconds since test (PRE_INFLATION) started → always 0 at START_TEST
            # elapsed_sec = seconds since mount (fallback if test_elapsed_sec missing)
            esp_elapsed = data.get('test_elapsed_sec', data.get('elapsed_sec'))
            if esp_elapsed is not None:
                self.time_elapsed = int(esp_elapsed)
            
            # Use recipe p7 (test duration) as the total reference time
            recipe = self.history_buffer.get('recipe', {})
            if recipe and recipe.get('p7'):
                self.total_time = int(recipe['p7'])
            
            # Graph data is now populated by esp_now_control.py directly into self.history_buffer
            # We just need to refresh the graph
            self._update_graph()
            
            self.update_display()
            
        except Exception as e:
            print(f"Error updating test data: {e}")

    def update_graph_data(self, times, pressures):
        """Called externally to force update graph"""
        # Since we share the list object, we might just need to redraw
        try:
            self._update_graph()
            self.update_display()
            
        except Exception as e:
            print(f"Error updating test data: {e}")
    
    def update_display(self):
        """Update display labels"""

        # NOTE: time_elapsed is set directly from ESP32 elapsed_sec in update_test_data().
        # The 1Hz QTimer still fires update_display() so the display refreshes every second
        # even if no new packet has arrived. No PC-side datetime calculation needed.

        # --- Aşama ---
        if self.current_phase == 'complete':
            result_text = getattr(self, 'test_result', 'UNKNOWN')
            if result_text == 'PASS':
                self.phase_value.setText('✅ GEÇTİ')
                self.phase_value.setStyleSheet('font-size: 13px; color: #059669; font-weight: bold;')
            elif result_text == 'FAIL':
                self.phase_value.setText('❌ KALDI')
                self.phase_value.setStyleSheet('font-size: 13px; color: #DC2626; font-weight: bold;')
            else:
                self.phase_value.setText('Test Tamamlandı')
                self.phase_value.setStyleSheet('font-size: 12px; color: #10B981; font-weight: bold;')
        else:
            phase_names = {
                'mounting': 'Aşama 0: Montaj',
                'inflation': 'Aşama 1: Şişirme',
                'stabilization': 'Aşama 2: Stabilizasyon',
                'measurement': 'Aşama 3: Ölçüm',
                'unknown': 'Bekliyor'
            }
            phase_colors = {
                'mounting': '#9333EA',
                'inflation': '#FF8C00',
                'stabilization': '#0066CC',
                'measurement': '#00AA00',
                'unknown': '#6B7280'
            }
            self.phase_value.setText(phase_names.get(self.current_phase, 'Bekliyor'))
            color = phase_colors.get(self.current_phase, '#6B7280')
            self.phase_value.setStyleSheet(f'font-size: 12px; color: {color}; font-weight: bold;')

        # Time
        self.time_value.setText(f"{self.time_elapsed}s")
        
        # Battery
        self.battery_value.setText(f"{self.battery}%")
        battery_color = '#10B981' if self.battery > 20 else '#EF4444'
        self.battery_value.setStyleSheet(f"font-size: 12px; color: {battery_color}; font-weight: bold;")
        
        # Pressure
        self.pressure_value.setText(f"{self.glove_pressure} Pa")
        
        # Status indicator
        if self.current_phase == 'complete':
            # Test completed - show result
            result_text = getattr(self, 'test_result', 'UNKNOWN')
            print(f"[STATUS] Phase is complete, showing result: {result_text}")
            if result_text == 'PASS':
                self.status_indicator.setText("✓ Test Tamamlandı - BAŞARILI")
                self.status_indicator.setStyleSheet("font-size: 11px; color: #10B981; font-weight: 600;")
            elif result_text == 'FAIL':
                self.status_indicator.setText("✗ Test Tamamlandı - BAŞARISIZ")
                self.status_indicator.setStyleSheet("font-size: 11px; color: #EF4444; font-weight: 600;")
            else:
                self.status_indicator.setText("● Test Tamamlandı")
                self.status_indicator.setStyleSheet("font-size: 11px; color: #6B7280; font-weight: 600;")
        elif self.test_active:
            self.status_indicator.setText("● Test Aktif")
            self.status_indicator.setStyleSheet("font-size: 11px; color: #10B981; font-weight: 600;")
        elif self.seal_active:
            self.status_indicator.setText("● Conta Aktif")
            self.status_indicator.setStyleSheet("font-size: 11px; color: #FF8C00; font-weight: 600;")
        else:
            self.status_indicator.setText("● İzleniyor")
            self.status_indicator.setStyleSheet("font-size: 11px; color: #6B7280; font-weight: 600;")
    
    def reset_for_new_test(self):
        """Reset graph, timers and state for a fresh test cycle.
        Called by esp_now_control when MOUNT is pressed (not START_TEST).
        Resets the timer from mount time so süre tracks from mount start.
        """
        now = datetime.now()
        # Clear shared buffer
        self.history_buffer['time'] = []
        self.history_buffer['pressure'] = []
        self.history_buffer['start_time'] = now
        # Sync local list references
        self.time_data = self.history_buffer['time']
        self.pressure_data = self.history_buffer['pressure']
        # Reset state
        self.test_start_time = now
        self.test_active = True
        self.test_result = None
        self.testing_start_pressure = None  # Reset for next test
        self.time_elapsed = 0
        self._graph_frozen = False
        self.current_phase = 'pre_inflation'
        # Redraw empty graph
        self._setup_graph()
        self.canvas.draw_idle()

    def on_dismount(self):
        """Called by esp_now_control when DISMOUNT is pressed.
        Stops the timer immediately so it doesn't keep running after dismount.
        """
        self.test_active = False
        self.test_start_time = None
        self.time_elapsed = 0
        self.current_phase = 'unknown'
        self._graph_frozen = True
        self.update_display()

    def request_initial_status(self):
        """Request current status from device when dialog opens"""
        try:
            # Get initial battery from parent device card if available
            parent = self.parent()
            if parent and hasattr(parent, 'device_cards'):
                if self.device_name in parent.device_cards:
                    card = parent.device_cards[self.device_name]
                    if hasattr(card, 'battery_level'):
                        self.battery = card.battery_level
                        print(f"[DIALOG] Initial battery from card: {self.battery}%")
                        self.update_display()  # Update display with initial values
            
            # Send status request to ESP32
            import json
            status_request = {
                "cmd": "GET_STATUS",
                "target": self.device_name
            }
            json_str = json.dumps(status_request)
            if self.esp32 and hasattr(self.esp32, 'send_command'):
                self.esp32.send_command(json_str)
                print(f"[DIALOG] Status request sent to {self.device_name}")
        except Exception as e:
            print(f"[DIALOG] Failed to request status: {e}")
            
    def closeEvent(self, event):
        """Cleanup when dialog closes"""
        self.update_timer.stop()
        super().closeEvent(event)
