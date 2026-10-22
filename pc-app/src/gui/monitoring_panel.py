"""
Monitoring Panel
Real-time display of test data and parameters
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QLabel, QLCDNumber, QProgressBar)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt


class MonitoringPanel(QWidget):
    """Real-time monitoring panel for test data"""
    
    def __init__(self, esp32_comm, parent=None):
        super().__init__(parent)
        self.esp32 = esp32_comm
        self.pressure_data = []
        self.temperature_data = []
        self.time_data = []
        self.max_points = 3600
        
        self.init_ui()
        
        # Set up ESP32 data callback
        self.esp32.set_data_callback(self.update_data)
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_displays)
        self.update_timer.start(1000)  # Update every second
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout()
        
        # Current Values Display
        values_group = QGroupBox("Current Values")
        values_layout = QHBoxLayout()
        
        # Pressure Display
        pressure_layout = QVBoxLayout()
        pressure_label = QLabel("Pressure (kPa)")
        pressure_label.setAlignment(Qt.AlignCenter)
        self.pressure_lcd = QLCDNumber()
        self.pressure_lcd.setDigitCount(6)
        self.pressure_lcd.setSegmentStyle(QLCDNumber.Flat)
        self.pressure_lcd.display("0.00")
        pressure_layout.addWidget(pressure_label)
        pressure_layout.addWidget(self.pressure_lcd)
        values_layout.addLayout(pressure_layout)
        
        # Temperature Display
        temp_layout = QVBoxLayout()
        temp_label = QLabel("Temperature (°C)")
        temp_label.setAlignment(Qt.AlignCenter)
        self.temp_lcd = QLCDNumber()
        self.temp_lcd.setDigitCount(6)
        self.temp_lcd.setSegmentStyle(QLCDNumber.Flat)
        self.temp_lcd.display("0.00")
        temp_layout.addWidget(temp_label)
        temp_layout.addWidget(self.temp_lcd)
        values_layout.addLayout(temp_layout)
        
        values_group.setLayout(values_layout)
        layout.addWidget(values_group)
        
        # Status Indicators
        status_group = QGroupBox("Test Status")
        status_layout = QVBoxLayout()
        
        self.status_label = QLabel("Status: IDLE")
        self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: gray;")
        self.status_label.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self.status_label)
        
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("Progress:"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        status_layout.addLayout(progress_layout)
        
        self.leak_indicator = QLabel("Leak Detection: OK")
        self.leak_indicator.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px; font-weight: bold;")
        self.leak_indicator.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self.leak_indicator)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Charts
        chart_group = QGroupBox("Real-Time Data")
        chart_layout = QVBoxLayout()
        
        # Create matplotlib figure
        self.figure = Figure(figsize=(8, 4))
        self.canvas = FigureCanvas(self.figure)
        
        # Create subplots
        self.ax1 = self.figure.add_subplot(211)
        self.ax2 = self.figure.add_subplot(212)
        
        self.ax1.set_title('Pressure vs Time')
        self.ax1.set_xlabel('Time (s)')
        self.ax1.set_ylabel('Pressure (kPa)')
        self.ax1.grid(True)
        
        self.ax2.set_title('Temperature vs Time')
        self.ax2.set_xlabel('Time (s)')
        self.ax2.set_ylabel('Temperature (°C)')
        self.ax2.grid(True)
        
        self.figure.tight_layout()
        
        chart_layout.addWidget(self.canvas)
        chart_group.setLayout(chart_layout)
        layout.addWidget(chart_group)
        
        self.setLayout(layout)
    
    def update_data(self, data):
        """Update data from ESP32"""
        if 'pressure' in data:
            self.pressure_data.append(data['pressure'])
            self.pressure_lcd.display(f"{data['pressure']:.2f}")
        
        if 'temperature' in data:
            self.temperature_data.append(data['temperature'])
            self.temp_lcd.display(f"{data['temperature']:.2f}")
        
        if 'timestamp' in data:
            if len(self.time_data) == 0:
                self.time_data.append(0)
            else:
                self.time_data.append(len(self.time_data))
        
        # Limit data points
        if len(self.pressure_data) > self.max_points:
            self.pressure_data.pop(0)
            self.temperature_data.pop(0)
            self.time_data.pop(0)
        
        # Check leak detection
        if 'leak_detected' in data:
            if data['leak_detected']:
                self.leak_indicator.setText("Leak Detection: LEAK DETECTED!")
                self.leak_indicator.setStyleSheet("background-color: #f44336; color: white; padding: 5px; font-weight: bold;")
            else:
                self.leak_indicator.setText("Leak Detection: OK")
                self.leak_indicator.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px; font-weight: bold;")
    
    def update_displays(self):
        """Update chart displays"""
        if len(self.pressure_data) > 0:
            self.ax1.clear()
            self.ax1.plot(self.time_data, self.pressure_data, 'b-')
            self.ax1.set_title('Pressure vs Time')
            self.ax1.set_xlabel('Time (s)')
            self.ax1.set_ylabel('Pressure (kPa)')
            self.ax1.grid(True)
            
            self.ax2.clear()
            self.ax2.plot(self.time_data, self.temperature_data, 'r-')
            self.ax2.set_title('Temperature vs Time')
            self.ax2.set_xlabel('Time (s)')
            self.ax2.set_ylabel('Temperature (°C)')
            self.ax2.grid(True)
            
            self.figure.tight_layout()
            self.canvas.draw()
    
    def start_monitoring(self, test_params):
        """Start monitoring a new test"""
        self.pressure_data = []
        self.temperature_data = []
        self.time_data = []
        
        self.status_label.setText("Status: RUNNING")
        self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: green;")
        self.progress_bar.setValue(0)
    
    def stop_monitoring(self):
        """Stop monitoring"""
        self.status_label.setText("Status: STOPPED")
        self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: orange;")
        self.progress_bar.setValue(100)
