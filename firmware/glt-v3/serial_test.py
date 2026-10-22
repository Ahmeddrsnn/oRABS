import serial
import time
import sys

# Kısa süre seri port oku ve kapat
port = 'COM11'
baud = 115200

try:
    ser = serial.Serial(port, baud, timeout=1)
    print(f"[SERIAL] {port} açıldı, 5 saniye okuyorum...")
    time.sleep(0.5)  # Kurulum için bekle
    
    start_time = time.time()
    while (time.time() - start_time) < 5:  # 5 saniye oku
        if ser.in_waiting:
            data = ser.readline().decode('utf-8', errors='ignore').strip()
            if data:
                print(data)
        time.sleep(0.01)
    
    ser.close()
    print(f"\n[SERIAL] {port} kapatıldı ✓")
    
except Exception as e:
    print(f"[HATA] {e}")
    sys.exit(1)
