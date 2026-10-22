import serial
import time
import sys

try:
    ser = serial.Serial('COM22', 115200, timeout=1)
    print("Connected to COM11. Monitoring Pressure every 1s (Press Ctrl+C to stop)...")
    
    start_main = time.time()
    last_query = 0
    
    # Start streaming
    ser.write(b'STREAM\n')
    print("Sent STREAM command...")
    
    # Run for 15 seconds
    while time.time() - start_main < 15:
        if ser.in_waiting:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f">>> {line}")
            except Exception:
                pass
        time.sleep(0.01)
                
        time.sleep(0.01)
        
    ser.close()
    print("Finished.")

except KeyboardInterrupt:
    if 'ser' in locals() and ser.is_open:
        ser.close()
    print("Stopped by user.")
except Exception as e:
    print(f"Error: {e}")
