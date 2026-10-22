import serial
import time
import sys

def read_serial(port='COM11', baudrate=115200, duration=5):
    """Serial portunu aç, duration saniye oku, kapat"""
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        print(f"[OK] {port} acildi, {duration} saniye okunuyor...\n")
        
        start_time = time.time()
        while time.time() - start_time < duration:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(line)
        
        ser.close()
        print(f"\n[OK] {port} kapatildi")
        
    except serial.SerialException as e:
        print(f"[ERROR] Serial port hatasi: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[STOP] Kullanici tarafindan durduruldu")
        if 'ser' in locals() and ser.is_open:
            ser.close()
        sys.exit(0)

if __name__ == "__main__":
    # Komut satırından port ve süre alınabilir
    port = sys.argv[1] if len(sys.argv) > 1 else 'COM11'
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    
    read_serial(port, duration=duration)
