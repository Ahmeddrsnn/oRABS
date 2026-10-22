import sys
import os
import json
import logging

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

# Mocking PyQt5 because we don't want to launch GUI
from unittest.mock import MagicMock
sys.modules['PyQt5'] = MagicMock()
sys.modules['PyQt5.QtWidgets'] = MagicMock()
sys.modules['PyQt5.QtCore'] = MagicMock()
sys.modules['PyQt5.QtGui'] = MagicMock()
sys.modules['sip'] = MagicMock() # Fix for matplotlib backend

# Mock Matplotlib to prevent backend loading
mpl_mock = MagicMock()
sys.modules['matplotlib'] = mpl_mock
sys.modules['matplotlib.pyplot'] = MagicMock()
sys.modules['matplotlib.backends'] = MagicMock()
sys.modules['matplotlib.backends.backend_qt5agg'] = MagicMock()
sys.modules['matplotlib.figure'] = MagicMock()

# Mock internal GUI modules that cause trouble
sys.modules['gui.device_detail_dialog'] = MagicMock()
sys.modules['gui.device_card'] = MagicMock()


# Setup QTimer mock to fire immediately for 'timeout'
class MockQTimer:
    def __init__(self):
        self.singleShot = False
        self.timeout = MagicMock()
        self.timeout.connect = lambda func: setattr(self, '_callback', func)
    def setSingleShot(self, val): self.singleShot = val
    def start(self, ms): pass # Do nothing or allow manual trigger
    def stop(self): pass

sys.modules['PyQt5.QtCore'].QTimer = MockQTimer

# Mock Database
class MockDB:
    def get_all_ports(self):
        return [
            {'name': 'Port 01', 'rfid_tag': '004FD0CF', 'recipe_id': 1},
            {'name': 'Port 02', 'rfid_tag': '0031DA54', 'recipe_id': 1}
        ]
    def get_recipe(self, id):
        return {'t1_inflation':10, 'name': 'Test Reçete'}

# Import ESPNowMasterPanel (partially mocked)
# We need to bypass the __init__ UI setup
from gui.esp_now_control import ESPNOWMasterPanel

class TestPanel(ESPNOWMasterPanel):
    def __init__(self):
        self.db = MockDB()
        self.esp32 = MagicMock()
        self.esp32.send_command = MagicMock(side_effect=lambda cmd: print(f"TX > {cmd}"))
        self.log = lambda msg, *args, **kwargs: print(f"LOG: {msg}") # Handle args
        self.slave_sync_buffers = {}
        self.sync_timers = {}
        self.last_rfid_state = {}
        self.device_cards = {}
        # We don't call super().__init__ because we don't want UI setup

def run_simulation():
    print("=== Başlatılıyor: Sync Simülasyonu ===")
    panel = TestPanel()
    
    sender = "TestAparati"
    
    # SENARYO 1: Kullanıcının verdiği Loglardaki Durum
    # Port 1'de İKİ tane kayıt var (Çakışma)
    # Port 2'de bir kayıt var.
    # Port 4'te bir kayıt var (Orphan/Fazlalık - DB'de yok)
    
    messages = [
        # Port 1 - Doğru (DB'de var)
        {"cmd":"RFID_ITEM","rfid":"0x004FD0CF","port":1,"name":"VarsayilanAdmin","recipe":"..."},
        # Port 1 - Yanlış (Çakışma)
        {"cmd":"RFID_ITEM","rfid":"0x005092F2","port":1,"name":"Yeni Kayit","recipe":"..."},
        # Port 2 - Doğru
        {"cmd":"RFID_ITEM","rfid":"0x0031DA54","port":2,"name":"Yeni Kayit","recipe":"..."},
        # Port 4 - Fazlalık (DB'de Port 4 yok)
        {"cmd":"RFID_ITEM","rfid":"0x004FE1B5","port":4,"name":"Yeni Kayit","recipe":"..."}
    ]
    
    print("\nAdım 1: RFID_ITEM mesajları gönderiliyor...")
    for msg in messages:
        # Simulate FastStream or JSON? The logic uses JSON buffer.
        # on_rx_data parses JSON.
        # We can call logic directly or via on_rx_data if we mock msg parsing.
        # Let's interact with buffers directly to test _process_slave_sync logic
        
        # Add to buffer
        if sender not in panel.slave_sync_buffers: panel.slave_sync_buffers[sender] = []
        panel.slave_sync_buffers[sender].append(msg)
        print(f"RX < {msg}")

    print("\nAdım 2: SYNC_COMPLETE (veya Timeout) tetikleniyor...")
    # Trigger Logic
    panel._process_slave_sync(sender)
    
    print("\n=== Simülasyon Bitti ===")
    
if __name__ == "__main__":
    run_simulation()
