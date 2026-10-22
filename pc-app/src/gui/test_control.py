"""
Test Control Panel
Interface for controlling glove tests and configuring parameters
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QLabel, QLineEdit, QDoubleSpinBox, QSpinBox,
                             QPushButton, QTextEdit, QComboBox, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont
from datetime import datetime
import json


class TestControlPanel(QWidget):
    """Widget for test control and parameter configuration"""
    
    test_started = pyqtSignal(dict)  # Emits test parameters
    test_stopped = pyqtSignal()
    
    def __init__(self, esp32_comm, database, auth_manager, audit_manager, parent=None):
        super().__init__(parent)
        self.esp32 = esp32_comm
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        self.current_test_id = None
        self.current_record_id = None
        self.test_running = False
        self.test_data_log = []
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout()
        
        # Connection Status
        connection_group = QGroupBox("ESP32 Connection")
        conn_layout = QVBoxLayout()
        
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("COM Port:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        port_layout.addWidget(self.port_combo)
        
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_ports)
        port_layout.addWidget(self.refresh_button)
        
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        port_layout.addWidget(self.connect_button)
        
        conn_layout.addLayout(port_layout)
        
        self.connection_status = QLabel("Status: Disconnected")
        self.connection_status.setStyleSheet("color: red; font-weight: bold;")
        conn_layout.addWidget(self.connection_status)
        
        connection_group.setLayout(conn_layout)
        layout.addWidget(connection_group)
        
        # Test Information
        info_group = QGroupBox("Test Information")
        info_layout = QVBoxLayout()
        
        test_id_layout = QHBoxLayout()
        test_id_layout.addWidget(QLabel("Test ID:"))
        self.test_id_input = QLineEdit()
        self.test_id_input.setPlaceholderText("AUTO-GENERATED")
        self.test_id_input.setReadOnly(True)
        test_id_layout.addWidget(self.test_id_input)
        info_layout.addLayout(test_id_layout)
        
        batch_layout = QHBoxLayout()
        batch_layout.addWidget(QLabel("Glove Batch:"))
        self.batch_input = QLineEdit()
        self.batch_input.setPlaceholderText("Enter batch number")
        batch_layout.addWidget(self.batch_input)
        info_layout.addLayout(batch_layout)
        
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Glove Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Nitrile", "Latex", "Vinyl", "Neoprene", "Other"])
        type_layout.addWidget(self.type_combo)
        info_layout.addLayout(type_layout)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Test Parameters
        param_group = QGroupBox("Test Parameters")
        param_layout = QVBoxLayout()
        
        pressure_layout = QHBoxLayout()
        pressure_layout.addWidget(QLabel("Target Pressure (kPa):"))
        self.pressure_spin = QDoubleSpinBox()
        self.pressure_spin.setRange(0.0, 100.0)
        self.pressure_spin.setValue(50.0)
        self.pressure_spin.setSingleStep(0.1)
        pressure_layout.addWidget(self.pressure_spin)
        param_layout.addLayout(pressure_layout)
        
        temp_layout = QHBoxLayout()
        temp_layout.addWidget(QLabel("Target Temperature (°C):"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 50.0)
        self.temp_spin.setValue(25.0)
        self.temp_spin.setSingleStep(0.1)
        temp_layout.addWidget(self.temp_spin)
        param_layout.addLayout(temp_layout)
        
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("Test Duration (seconds):"))
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 3600)
        self.duration_spin.setValue(300)
        duration_layout.addWidget(self.duration_spin)
        param_layout.addLayout(duration_layout)
        
        param_group.setLayout(param_layout)
        layout.addWidget(param_group)
        
        # Control Buttons
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("Start Test")
        self.start_button.clicked.connect(self.start_test)
        self.start_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.start_button.setEnabled(False)
        button_layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("Stop Test")
        self.stop_button.clicked.connect(self.stop_test)
        self.stop_button.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)
        
        layout.addLayout(button_layout)
        
        # Log Display
        log_group = QGroupBox("Test Log")
        log_layout = QVBoxLayout()
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumHeight(150)
        log_layout.addWidget(self.log_display)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        layout.addStretch()
        self.setLayout(layout)
    
    def refresh_ports(self):
        """Refresh available COM ports"""
        self.port_combo.clear()
        ports = self.esp32.list_available_ports()
        self.port_combo.addItems(ports if ports else ["No ports available"])
    
    def toggle_connection(self):
        """Toggle ESP32 connection"""
        if self.esp32.is_connected:
            self.esp32.disconnect()
            self.connection_status.setText("Status: Disconnected")
            self.connection_status.setStyleSheet("color: red; font-weight: bold;")
            self.connect_button.setText("Connect")
            self.start_button.setEnabled(False)
            self.log("Disconnected from ESP32")
        else:
            port = self.port_combo.currentText()
            if port == "No ports available":
                QMessageBox.warning(self, "Connection Error", "No COM ports available")
                return
            
            success, message = self.esp32.connect(port)
            if success:
                self.connection_status.setText(f"Status: Connected ({port})")
                self.connection_status.setStyleSheet("color: green; font-weight: bold;")
                self.connect_button.setText("Disconnect")
                self.start_button.setEnabled(True)
                self.log(f"Connected to ESP32 on {port}")
                
                # Set up callbacks
                self.esp32.set_data_callback(self.handle_esp32_data)
                self.esp32.set_status_callback(self.handle_esp32_status)
            else:
                QMessageBox.critical(self, "Connection Failed", message)
                self.log(f"Connection failed: {message}")
    
    def start_test(self):
        """Start a new test"""
        # Validate inputs
        batch = self.batch_input.text().strip()
        if not batch:
            QMessageBox.warning(self, "Input Error", "Please enter glove batch number")
            return
        
        if not self.auth.has_permission('Operator'):
            QMessageBox.critical(self, "Permission Denied", 
                               "You do not have permission to start tests.\nRequired role: Operator")
            return
        
        # Generate test ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_test_id = f"GT_{timestamp}"
        self.test_id_input.setText(self.current_test_id)
        
        # Gather parameters
        params = {
            'test_id': self.current_test_id,
            'operator_id': self.auth.current_user['id'],
            'glove_batch_number': batch,
            'glove_type': self.type_combo.currentText(),
            'test_start_time': datetime.now().isoformat(),
            'target_pressure': self.pressure_spin.value(),
            'target_temperature': self.temp_spin.value(),
            'test_duration': self.duration_spin.value(),
            'test_status': 'RUNNING',
            'data_json': json.dumps([])
        }
        
        # Create database record
        try:
            self.current_record_id = self.db.create_test_record(params)
            self.audit.log_test_action('STARTED', self.current_test_id, 
                                      f"Batch: {batch}, Type: {self.type_combo.currentText()}")
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Failed to create test record:\n{str(e)}")
            return
        
        # Send command to ESP32
        if self.esp32.is_connected:
            success = self.esp32.start_test(
                params['target_pressure'],
                params['target_temperature'],
                params['test_duration']
            )
            
            if not success:
                QMessageBox.warning(self, "ESP32 Error", 
                                  "Failed to start test on device.\nTest record created but device not responding.")
        
        # Update UI
        self.test_running = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.batch_input.setEnabled(False)
        self.type_combo.setEnabled(False)
        self.pressure_spin.setEnabled(False)
        self.temp_spin.setEnabled(False)
        self.duration_spin.setEnabled(False)
        
        self.test_data_log = []
        self.log(f"Test {self.current_test_id} started")
        
        self.test_started.emit(params)
    
    def stop_test(self):
        """Stop current test"""
        if not self.test_running:
            return
        
        # Send stop command to ESP32
        if self.esp32.is_connected:
            self.esp32.stop_test()
        
        # Update database record
        updates = {
            'test_end_time': datetime.now().isoformat(),
            'test_status': 'COMPLETED',
            'test_result': 'STOPPED_BY_USER',
            'data_json': json.dumps(self.test_data_log)
        }
        
        self.db.update_test_record(self.current_record_id, updates)
        self.audit.log_test_action('STOPPED', self.current_test_id, "Test stopped by user")
        
        # Update UI
        self.test_running = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.batch_input.setEnabled(True)
        self.type_combo.setEnabled(True)
        self.pressure_spin.setEnabled(True)
        self.temp_spin.setEnabled(True)
        self.duration_spin.setEnabled(True)
        
        self.log(f"Test {self.current_test_id} stopped")
        self.test_stopped.emit()
        
        QMessageBox.information(self, "Test Complete", 
                              f"Test {self.current_test_id} has been stopped and saved.")
    
    def handle_esp32_data(self, data):
        """Handle real-time data from ESP32"""
        if self.test_running:
            self.test_data_log.append(data)
            # This will be handled by monitoring panel
    
    def handle_esp32_status(self, status):
        """Handle status updates from ESP32"""
        self.log(f"ESP32 Status: {status.get('status', 'UNKNOWN')}")
    
    def log(self, message):
        """Add message to log display"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_display.append(f"[{timestamp}] {message}")
