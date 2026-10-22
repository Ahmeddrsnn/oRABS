import serial
import time

port = 'COM22'
baud = 115200

try:
    print(f"Connecting to {port}...")
    ser = serial.Serial(port, baud, timeout=1)
    time.sleep(1) # Wait for connection to settle
    
    print("Sending STREAM command...")
    ser.write(b'STREAM\n')
    
    print("Listening for 10 seconds...")
    start = time.time()
    while time.time() - start < 10:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f"[RX] {line}")
        time.sleep(0.01)
        
    ser.close()
    print("Done.")
    
except Exception as e:
    print(f"Error: {e}")
