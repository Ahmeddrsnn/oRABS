import serial
import time

try:
    # Use 'ignore' to skip bad bytes
    ser = serial.Serial('COM22', 115200, timeout=1)
    print("Monitoring COM22 for 15 seconds (Safe Mode)...")
    
    start = time.time()
    while time.time() - start < 15:
        if ser.in_waiting:
            try:
                # Read bytes and decode safely
                line_bytes = ser.readline()
                line = line_bytes.decode('utf-8', errors='replace').strip()
                if line:
                    print(f"[DEVICE] {line}")
            except Exception:
                pass # Skip partial line errors
                
    ser.close()
except Exception as e:
    print(f"Error: {e}")
