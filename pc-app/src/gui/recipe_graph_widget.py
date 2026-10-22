"""
Recipe Graph Widget
Interactive matplotlib widget showing 3-phase test procedure visualization
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt5.QtCore import Qt
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np


class RecipeGraphWidget(QWidget):
    """
    Interactive widget displaying test recipe parameters as a graph
    Shows 3 phases: Inflation, Stabilization, Measurement
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Default parameters
        self.p1 = 500  # Test pressure (Pa)
        self.p2 = 50   # Hysteresis (Pa)
        self.p3 = 100  # Acceptance limit (Pa)
        self.t1 = 10   # Inflation time (s)
        self.t2 = 10   # Stabilization time (s)
        self.t3 = 60   # Measurement time (s)
        self.theoretical_max_time = 0  # Theoretical max time (optional)
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create matplotlib figure
        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        
        # Initial draw
        self.update_graph()
        
    def update_parameters(self, p1, p2, p3, t1, t2, t3):
        """Update parameters and redraw graph"""
        self.p1 = p1
        self.p2 = p2
        self.p3 = p3
        self.t1 = t1
        self.t2 = t2
        self.t3 = t3
        self.update_graph()
    
    def set_theoretical_max_time(self, max_time):
        """Set theoretical maximum test time for visualization"""
        self.theoretical_max_time = max_time
        self.update_graph()
        
    def update_graph(self):
        """Draw/update the graph with current parameters"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        
        # Calculate time points
        total_time = self.t1 + self.t2 + self.t3
        
        # Phase 1: Inflation (0 to t1)
        t1_points = np.linspace(0, self.t1, 50)
        # Ramp up to p1 (exponential approach reaching ~99.75% of target)
        p1_values = self.p1 * (1 - np.exp(-6 * t1_points / self.t1))
        
        # Phase 2: Stabilization (t1 to t1+t2)
        t2_points = np.linspace(self.t1, self.t1 + self.t2, 100)
        # Pulse pattern around p1 with hysteresis
        pulse_freq = 5  # frequency of pulses
        p2_values = self.p1 + self.p2 * 0.5 * np.sin(pulse_freq * 2 * np.pi * (t2_points - self.t1) / self.t2)
        
        # Phase 3: Measurement (t1+t2 to total_time)
        t3_points = np.linspace(self.t1 + self.t2, total_time, 100)
        
        # Two scenarios: tight glove (green) vs leaky glove (red)
        # Tight glove: small decay within p3 limit
        decay_tight = self.p1 - (self.p3 * 0.6) * (t3_points - self.t1 - self.t2) / self.t3
        
        # Leaky glove: large decay exceeding p3 limit
        decay_leaky = self.p1 - (self.p3 * 2.0) * (t3_points - self.t1 - self.t2) / self.t3
        
        # Plot Phase 1: Inflation (Orange)
        ax.plot(t1_points, p1_values, color='#FF8C00', linewidth=2.5, label='Phase 1: Inflation', zorder=3)
        
        # Plot Phase 2: Stabilization (Blue with pulses)
        ax.plot(t2_points, p2_values, color='#0066CC', linewidth=2, label='Phase 2: Stabilization', zorder=3)
        
        # Plot Phase 3: Measurement - Both scenarios
        ax.plot(t3_points, decay_tight, color='#00AA00', linewidth=2.5, label='Phase 3: Pass (Tight)', 
                linestyle='-', zorder=3)
        ax.plot(t3_points, decay_leaky, color='#FF0000', linewidth=2, label='Phase 3: Fail (Leaky)', 
                linestyle='--', alpha=0.7, zorder=2)
        
        # Horizontal reference lines
        ax.axhline(y=self.p1, color='#666', linestyle='--', linewidth=1, alpha=0.6, label=f'P1: {self.p1} Pa')
        ax.axhline(y=self.p1 - self.p3, color='#CC0000', linestyle=':', linewidth=1.5, 
                  alpha=0.7, label=f'P3 Limit: {self.p1 - self.p3} Pa')
        
        # Vertical phase separators
        ax.axvline(x=self.t1, color='#999', linestyle='-.', linewidth=1, alpha=0.5)
        ax.axvline(x=self.t1 + self.t2, color='#999', linestyle='-.', linewidth=1, alpha=0.5)
        
        # Phase labels - positioned at middle of graph height
        label_y_pos = self.p1 / 2  # Middle of the pressure range
        ax.text(self.t1 / 2, label_y_pos, 't₁', ha='center', fontsize=12, fontweight='bold', 
                color='#FF8C00', bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='#FF8C00', alpha=0.8))
        ax.text(self.t1 + self.t2 / 2, label_y_pos, 't₂', ha='center', fontsize=12, fontweight='bold', 
                color='#0066CC', bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='#0066CC', alpha=0.8))
        ax.text(self.t1 + self.t2 + self.t3 / 2, label_y_pos, 't₃', ha='center', fontsize=12, fontweight='bold', 
                color='#00AA00', bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='#00AA00', alpha=0.8))
        
        # Styling
        ax.set_xlabel('Time (s)', fontsize=11, fontweight='bold')
        ax.set_ylabel('Pressure (Pa)', fontsize=11, fontweight='bold')
        ax.set_title('Test Procedure: 3-Phase Pressure Decay', fontsize=13, fontweight='bold', pad=15)
        ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
        ax.legend(loc='lower right', fontsize=9, framealpha=0.95, shadow=True, fancybox=True)
        
        # Show theoretical max time if set
        if self.theoretical_max_time > 0:
            # Teorik max süre test fazının başından (t1+t2) itibaren hesaplanır
            theoretical_max_x = self.t1 + self.t2 + self.theoretical_max_time
            ax.axvline(x=theoretical_max_x, color='#FF00FF', linestyle=':', linewidth=2.5, 
                      alpha=0.8, label=f'Teorik Max: {self.theoretical_max_time}s')
            # Re-draw legend to include new item
            ax.legend(loc='lower right', fontsize=9, framealpha=0.95, shadow=True, fancybox=True)
        
        # Set limits - extend X axis to show theoretical max time if needed
        if self.theoretical_max_time > 0:
            theoretical_max_x = self.t1 + self.t2 + self.theoretical_max_time
            max_x_time = max(total_time, theoretical_max_x)
        else:
            max_x_time = total_time
        ax.set_xlim(-2, max_x_time + 5)
        ax.set_ylim(-100, self.p1 + 100)
        
        # Tight layout
        self.figure.tight_layout()
        
        # Redraw canvas
        self.canvas.draw()
