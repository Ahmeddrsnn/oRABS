#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
İşlem Müzik Oynatıcı (GUI Versiyonu)
Kullanım:
  python play_success_music.py start   -> İşlem başlarken (1 kere çalar, pencere görünmez veya hemen kapanır)
  python play_success_music.py finish  -> İşlem bitince (döngüde çalar, DURDUR butonu ile kapanır)
"""

import os
import sys
import time
import threading
import tkinter as tk
from tkinter import messagebox

# Müzik dosyaları
MUSIC_START = r"C:\Program Files\WindowsApps\AntaraSoftware.AlarmClockHD_7.0.0.0_x64__7jhd16s0b93qm\Assets\AlarmMusic\Smooth11.mp3"
MUSIC_FINISH = r"C:\Program Files\WindowsApps\AntaraSoftware.AlarmClockHD_7.0.0.0_x64__7jhd16s0b93qm\Assets\AlarmMusic\Piano.mp3"

class MusicPlayerGUI:
    def __init__(self, root, mode):
        self.root = root
        self.mode = mode
        self.running = True
        
        self.root.title("İşlem Bildirimi")
        self.root.geometry("400x200")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # UI Elements
        self.status_label = tk.Label(root, text="Başlatılıyor...", font=("Arial", 14, "bold"), pady=20)
        self.status_label.pack()
        
        self.info_label = tk.Label(root, text="", font=("Arial", 10))
        self.info_label.pack()
        
        if mode == "finish":
            stop_btn = tk.Button(root, text="MÜZİĞİ DURDUR VE KAPAT", command=self.on_closing, 
                                bg="red", fg="white", font=("Arial", 12, "bold"), pady=10)
            stop_btn.pack(pady=20)
            self.root.configure(bg="#f0f0f0")
        
        # Start playing in background thread
        self.thread = threading.Thread(target=self.play_music)
        self.thread.daemon = True
        self.thread.start()

    def play_music(self):
        if self.mode == "start":
            self.status_label.config(text=">>> İŞLEM BAŞLADI <<<", fg="blue")
            self.info_label.config(text=f"Müzik: {os.path.basename(MUSIC_START)}")
            
            if os.path.exists(MUSIC_START):
                # Start için sadece 1 kere çal ve kapat
                os.system(f'start /min wmplayer "{MUSIC_START}"')
                time.sleep(2) # Kısa bir süre bekle
                self.root.quit() # Otomatik kapat
            else:
                self.status_label.config(text="Müzik Bulunamadı!", fg="red")
                
        elif self.mode == "finish":
            self.status_label.config(text="✅ İŞLEM TAMAMLANDI ✅", fg="green")
            self.info_label.config(text=f"Müzik: {os.path.basename(MUSIC_FINISH)}")
            
            if not os.path.exists(MUSIC_FINISH):
                self.status_label.config(text="Müzik Dosyası Yok!", fg="red")
                return

            loop_count = 0
            while self.running:
                loop_count += 1
                # UI Update (Thread safe update using after is better but this is simple script)
                # os.system blocks? No, start runs async usually but wmplayer might take focus
                # Using start /min to keep it minimal
                os.system(f'start /min wmplayer "{MUSIC_FINISH}"')
                
                # Wait for music duration (approx 30s)
                for _ in range(30):
                    if not self.running: break
                    time.sleep(1)
                    
    def on_closing(self):
        self.running = False
        # Kill wmplayer
        os.system('taskkill /F /IM wmplayer.exe >nul 2>&1')
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    mode = "finish" # Varsayılan
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
    
    root = tk.Tk()
    
    # Pencereyi her zaman üstte tut (özellikle finish modunda)
    if mode == "finish":
        root.attributes('-topmost', True)
        
    app = MusicPlayerGUI(root, mode)
    
    # Start modu için pencereyi göstermeden kapatabiliriz veya çok kısa gösterebiliriz
    # Kullanıcı GUI istediği için gösteriyoruz ama otomatik kapanacak
    
    root.mainloop()
