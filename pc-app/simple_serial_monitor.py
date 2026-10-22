import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import threading
import queue
import time

class SerialMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Python Seri Port Monitör")
        self.root.geometry("600x450")
        
        # Seri port ve thread değişkenleri
        self.serial_port = None
        self.is_reading = False
        self.read_thread = None
        self.data_queue = queue.Queue()
        
        # Arayüzü oluştur
        self.create_widgets()
        
        # Portları listele
        self.populate_ports()
        
        # Kuyruk işleme döngüsünü başlat
        self.process_queue()

    def create_widgets(self):
        # Ayarlar Paneli (Üst kısım)
        settings_frame = ttk.LabelFrame(self.root, text="Bağlantı Ayarları", padding="10")
        settings_frame.pack(fill="x", padx=10, pady=5)
        
        # Port Seçimi
        ttk.Label(settings_frame, text="Port:").pack(side="left", padx=5)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(settings_frame, textvariable=self.port_var, width=10, state="readonly")
        self.port_combo.pack(side="left", padx=5)
        
        # Yenile Butonu (Portları tekrar taramak için)
        ttk.Button(settings_frame, text="↻", width=3, command=self.populate_ports).pack(side="left", padx=2)
        
        # Baud Rate Seçimi
        ttk.Label(settings_frame, text="Baud:").pack(side="left", padx=5)
        self.baud_var = tk.StringVar(value="115200")
        self.baud_combo = ttk.Combobox(settings_frame, textvariable=self.baud_var, width=10, state="readonly")
        self.baud_combo['values'] = ('9600', '19200', '38400', '57600', '115200', '230400', '460800', '921600')
        self.baud_combo.pack(side="left", padx=5)
        
        # Bağlan / Kes Butonları
        self.connect_btn = ttk.Button(settings_frame, text="Bağlan", command=self.toggle_connection)
        self.connect_btn.pack(side="left", padx=20)
        
        # Veri Alanı (Orta kısım)
        data_frame = ttk.LabelFrame(self.root, text="Gelen Veri", padding="10")
        data_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.text_area = scrolledtext.ScrolledText(data_frame, state='disabled', height=10)
        self.text_area.pack(fill="both", expand=True)
        self.text_area.configure(font=("Consolas", 10))
        
        # Alt Panel (Temizle ve Durum)
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Button(bottom_frame, text="Temizle", command=self.clear_text).pack(side="left")
        self.status_label = ttk.Label(bottom_frame, text="Durum: Bağlı Değil", relief=tk.SUNKEN, anchor="w")
        self.status_label.pack(side="right", fill="x", expand=True, padx=(10, 0))

    def populate_ports(self):
        """Mevcut seri portları bul ve Combobox'a ekle"""
        ports = serial.tools.list_ports.comports()
        port_list = [port.device for port in ports]
        self.port_combo['values'] = port_list
        if port_list:
            self.port_combo.current(0)
        else:
            self.port_combo.set("")
            
    def toggle_connection(self):
        """Bağlan/Kes butonu mantığı"""
        if self.serial_port and self.serial_port.is_open:
            self.disconnect_serial()
        else:
            self.connect_serial()
            
    def connect_serial(self):
        """Seri porta bağlan"""
        port = self.port_var.get()
        baud = self.baud_var.get()
        
        if not port:
            messagebox.showwarning("Uyarı", "Lütfen bir Port seçin!")
            return
            
        try:
            self.serial_port = serial.Serial(port, int(baud), timeout=1)
            self.is_reading = True
            
            # Thread başlat
            self.read_thread = threading.Thread(target=self.read_from_port, daemon=True)
            self.read_thread.start()
            
            # UI Güncelle
            self.connect_btn.config(text="Kes")
            self.port_combo.config(state="disabled")
            self.baud_combo.config(state="disabled")
            self.status_label.config(text=f"Durum: Bağlandı ({port} @ {baud})", foreground="green")
            self.append_text(f"--- BAĞLANDI: {port} {baud}bd ---\n", "system")
            
        except serial.SerialException as e:
            messagebox.showerror("Hata", f"Port açılamadı:\n{str(e)}")
        except Exception as e:
            messagebox.showerror("Hata", f"Beklenmeyen hata:\n{str(e)}")

    def disconnect_serial(self):
        """Bağlantıyı kes"""
        self.is_reading = False
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception:
                pass
        
        # UI Güncelle
        self.connect_btn.config(text="Bağlan")
        self.port_combo.config(state="readonly")
        self.baud_combo.config(state="readonly")
        self.status_label.config(text="Durum: Bağlı Değil", foreground="black")
        self.append_text("--- BAĞLANTI KESİLDİ ---\n", "system")

    def read_from_port(self):
        """Ayrı thread'de çalışan okuma döngüsü"""
        while self.is_reading and self.serial_port and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting > 0:
                    # Veriyi oku (byte olarak)
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    # Queue'ya at (ana thread işlesin)
                    self.data_queue.put(data)
                else:
                    time.sleep(0.01) # CPU'yu yormamak için kısa bekleme
            except Exception as e:
                self.data_queue.put(e) # Hatayı da kuyruğa at
                self.is_reading = False
                break

    def process_queue(self):
        """Kuyruktaki verileri arayüze yazan metot (Ana thread)"""
        while not self.data_queue.empty():
            item = self.data_queue.get()
            
            if isinstance(item, Exception):
                self.disconnect_serial()
                messagebox.showerror("Bağlantı Hatası", f"Veri okunurken hata oluştu:\n{str(item)}")
            elif isinstance(item, bytes):
                try:
                    # Byte verisini string'e çevir (utf-8, hataları yoksay)
                    text_data = item.decode('utf-8', errors='replace')
                    self.append_text(text_data)
                except Exception:
                    pass
        
        # Kendini tekrar çağır (100ms sonra)
        self.root.after(100, self.process_queue)

    def append_text(self, text, tag=None):
        """Metin alanına ekleme yap ve en alta kaydır"""
        self.text_area.configure(state='normal')
        self.text_area.insert(tk.END, text)
        self.text_area.configure(state='disabled')
        self.text_area.see(tk.END)

    def clear_text(self):
        self.text_area.configure(state='normal')
        self.text_area.delete(1.0, tk.END)
        self.text_area.configure(state='disabled')

if __name__ == "__main__":
    root = tk.Tk()
    
    # Pencere kapatıldığında düzgün çıkış yap
    app = SerialMonitorApp(root)
    
    def on_closing():
        app.disconnect_serial()
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
