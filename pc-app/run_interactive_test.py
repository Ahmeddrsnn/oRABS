
import sys
import os
import time
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, QObject
import json

# Setup paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Mock Login Dialog to bypass authentication
from gui import login_dialog
class AutoLoginDialog:
    Accepted = 1
    def __init__(self, auth): pass
    def exec_(self): return 1 # Accepted

login_dialog.LoginDialog = AutoLoginDialog

# Import Main components
from main import main
from gui.main_window import MainWindow

# We need to hook into the MainWindow to access the panel
# We can wrap MainWindow
OriginalMainWindow = MainWindow

class TestController(QObject):
    def __init__(self, app_window):
        super().__init__()
        self.window = app_window
        self.step = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.run_scenario)
        self.timer.start(2000) # Start 2s after launch

    def run_scenario(self):
        # Find the ESPNow Panel
        # MainWindow -> centralWidget -> (Maybe TabWidget?) -> Find ESPNowMasterPanel
        # Or look at self.window.structure
        # Let's search children
        # But wait, MainWindow initializes `self.esp_now_panel`.
        # Assuming MainWindow structure from typical design.
        
        panel = getattr(self.window, 'esp_now_tab', None)
        if not panel:
            # Maybe inside a tab widget
            # Let's try to find it by type
            from gui.esp_now_control import ESPNowMasterPanel # Use correct import? 
            # Wait, verify class name in src/gui/esp_now_control.py -> ESPNOWMasterPanel (checked in step 1096-1100)
            from gui.esp_now_control import ESPNOWMasterPanel
            panel = self.window.findChild(ESPNOWMasterPanel)
            
        if not panel:
            print("[TEST] ESPNOW Panel Bulunamadı!")
            return

        self.step += 1
        sender = "TestAparati"
        
        if self.step == 1:
            print("\n[TEST SENARYO] Adım 1: Duplicate ve Orphan Verisi Gönderiliyor...")
            # 1. Duplicate on Port 1 
            # 2. Orphan on Port 5
            # 3. Missing on Port 2 (Implicit, we don't send it)
            
            payloads = [
                # Duplicate Port 1
                {"cmd":"RFID_ITEM","rfid":"TAG_A_CORRECT","port":1,"name":"Admin"},
                {"cmd":"RFID_ITEM","rfid":"TAG_X_WRONG","port":1,"name":"Old"},
                # Orphan Port 5
                {"cmd":"RFID_ITEM","rfid":"TAG_ORPHAN","port":5,"name":"Unknown"}
            ]
            
            for p in payloads:
                # Inject via raw string signal
                print(f"[TEST TX] {json.dumps(p)}")
                panel.on_rx_data(json.dumps(p))
                
        elif self.step == 2:
            print("\n[TEST SENARYO] Adım 2: SYNC_COMPLETE Gönderiliyor (Logik Tetikleme)...")
            sync_msg = {"cmd":"SYNC_COMPLETE", "count":3}
            print(f"[TEST TX] {json.dumps(sync_msg)}")
            panel.on_rx_data(json.dumps(sync_msg))
            
        elif self.step == 3:
            print("\n[TEST SENARYO] Tamamlandı. Uygulama Kapanıyor...")
            # We can't easily capture the logs unless we hooked the signal.
            # But the App logs output to stdout via print if configured?
            # Or we hook the panel.log_message signal?
            QApplication.quit()
        
    def hook_logging(self, panel):
        # Connect log signal to stdout printer
        panel.log_message.connect(lambda msg, c, b: print(f"[APP LOG] {msg}"))

# Monkey Patch MainWindow to hook controller
def HookedMainWindow(*args, **kwargs):
    w = OriginalMainWindow(*args, **kwargs)
    
    # Open log file
    log_file = open("test_result.log", "w", encoding="utf-8")
    def file_log(msg):
        print(msg)
        log_file.write(msg + "\n")
        log_file.flush()

    file_log("[TEST] MainWindow Hooked. Starting Test Controller...")
    
    # Try to hook logging immediately
    from gui.esp_now_control import ESPNOWMasterPanel
    panel = w.findChild(ESPNOWMasterPanel)
    
    if panel:
        file_log("[TEST] Panel bulundu, loglar yönlendiriliyor...")
        panel.log_message.connect(lambda msg, c, b: file_log(f"[APP LOG] {msg}"))
        
    # Start Test Controller
    w.test_ctrl = TestController(w)
    # Patch controller to use file_log
    w.test_ctrl.log = file_log
    
    # Hook logging later if findChild failed initially (e.g. init delay)
    if not panel:
         QTimer.singleShot(1000, lambda: w.test_ctrl.hook_logging(w.findChild(ESPNOWMasterPanel), file_log))
         
    return w

# Patch TestController to use custom log
def run_scenario(self):
    log = getattr(self, 'log', print)
    # Find the ESPNow Panel
    panel = getattr(self.window, 'esp_now_tab', None)
    if not panel:
        from gui.esp_now_control import ESPNOWMasterPanel
        panel = self.window.findChild(ESPNOWMasterPanel)
        
    if not panel:
        log("[TEST] ESPNOW Panel Bulunamadı!")
        return

    self.step += 1
    sender = "TestAparati"
    
    if self.step == 1:
        log("\n[TEST SENARYO] Adım 1: Duplicate ve Orphan Verisi Gönderiliyor...")
        payloads = [
            # Duplicate Port 1
            {"cmd":"RFID_ITEM","rfid":"TAG_A_CORRECT","port":1,"name":"Admin"},
            {"cmd":"RFID_ITEM","rfid":"TAG_X_WRONG","port":1,"name":"Old"},
            # Orphan Port 5
            {"cmd":"RFID_ITEM","rfid":"TAG_ORPHAN","port":5,"name":"Unknown"}
        ]
        
        for p in payloads:
            log(f"[TEST TX] {json.dumps(p)}")
            panel.on_rx_data(json.dumps(p))
            
    elif self.step == 2:
        log("\n[TEST SENARYO] Adım 2: SYNC_COMPLETE Gönderiliyor (Logik Tetikleme)...")
        sync_msg = {"cmd":"SYNC_COMPLETE", "count":3}
        log(f"[TEST TX] {json.dumps(sync_msg)}")
        panel.on_rx_data(json.dumps(sync_msg))
        
    elif self.step == 3:
        log("\n[TEST SENARYO] Tamamlandı. Uygulama Kapanıyor...")
        QApplication.quit()

def hook_logging(self, panel, logger=print):
    if panel:
        logger("[TEST] Panel sonradan bulundu, loglar bağlandı.")
        panel.log_message.connect(lambda msg, c, b: logger(f"[APP LOG] {msg}"))

TestController.run_scenario = run_scenario
TestController.hook_logging = hook_logging

import gui.main_window
gui.main_window.MainWindow = HookedMainWindow

if __name__ == "__main__":
    print("--- REAL GUI TEST LAUNCHER ---")
    try:
        main()
    except SystemExit:
        pass
    print("--- REAL GUI TEST FINISHED ---")
