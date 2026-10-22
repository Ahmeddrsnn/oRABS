import serial
import time
import sys

# Windows console encoding fix
sys.stdout.reconfigure(encoding='utf-8')

def monitor_slave():
    port = "COM23"
    print(f"Monitoring Slave on {port}...")
    
    try:
        ser = serial.Serial(port, 115200, timeout=0.1)
        ser.dtr = True
        ser.rts = True
        
        while True:
            if ser.in_waiting:
                try:
                    line = ser.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        # Filter out spam
                        if "UART: RFID Aktif" in line:
                            continue
                        if "Ping" in line or "PING" in line:
                            continue
                            
                        print(f"[SLAVE] {line}")
                        
                        if "SET_TIME" in line or "Zaman" in line or "Saat" in line:
                            print(f"[Captured] Potential Time Sync Event: {line}")
                except Exception as e:
                    pass
            time.sleep(0.01)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    monitor_slave()
