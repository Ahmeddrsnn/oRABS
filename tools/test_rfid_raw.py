
import serial
import serial.tools.list_ports
import time

def list_ports():
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]

def main():
    print("--- GLT v3 RFID Raw Debug Tool ---")
    ports = list_ports()
    
    if not ports:
        print("HATA: Hiçbir COM port bulunamadı!")
        input("Çıkmak için Enter'a bas...")
        return
        
    print(f"Bulunan Portlar: {ports}")
    
    # Try to auto-detect Master or ask user
    selected_port = None
    for p in ports:
        # Check description if possible (Windows only)
        # Assuming user knows or we pick last one
        pass
        
    if len(ports) == 1:
        selected_port = ports[0]
    else:
        print("Lütfen Port Girin (örn: COM13):")
        selected_port = input().strip().upper()
        
    print(f"Baglaniliyor: {selected_port} @ 115200...")
    
    try:
        ser = serial.Serial(selected_port, 115200, timeout=0.1)
        time.sleep(2) # Wait for DTR reset
        
        print("Baglanti Basarili! Veri bekleniyor (CTRL+C ile cikis)...")
        print("-" * 50)
        
        while True:
            if ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"[RAW] {line}")
                except Exception as e:
                    print(f"Okuma Hatasi: {e}")
                    
            time.sleep(0.01)
            
    except serial.SerialException as e:
        print(f"Port Hatasi: {e}")
    except KeyboardInterrupt:
        print("\nKapatiliyor...")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
    
    input("Cikmak icin Enter...")

if __name__ == "__main__":
    main()
