import serial
import time
import sys

def send_command(port='COM11', baudrate=115200, command="", wait_time=2):
    """Serial'e komut gönder ve cevabı oku"""
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        print(f"[OK] {port} acildi")
        time.sleep(0.5)  # Bağlantı stabilizasyonu
        
        # Komutu gönder
        print(f"[CMD] Gonderiliyor: {command}")
        ser.write((command + '\n').encode())
        ser.flush()
        
        # Cevabı bekle
        print(f"[WAIT] {wait_time} saniye bekleniyor...\n")
        start_time = time.time()
        while time.time() - start_time < wait_time:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(line)
        
        ser.close()
        print(f"\n[OK] {port} kapatildi")
        return True
        
    except serial.SerialException as e:
        print(f"[ERROR] Serial port hatasi: {e}")
        return False
    except KeyboardInterrupt:
        print("\n[STOP] Kullanici tarafindan durduruldu")
        if 'ser' in locals() and ser.is_open:
            ser.close()
        return False

if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else 'COM11'
    command = sys.argv[2] if len(sys.argv) > 2 else "HELP"
    wait_time = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    
    send_command(port, command=command, wait_time=wait_time)
