import serial
import time

try:
    ser = serial.Serial('COM11', 115200, timeout=1)
    print(f"Connected to {ser.name}")
    
    start_time = time.time()
    # Send 'P' command to trigger pressure dump in case it's quiet
    time.sleep(1)
    ser.write(b'P\n')
    
    print("Reading data for 5 seconds...")
    while time.time() - start_time < 5:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f"[RX] {line}")
        time.sleep(0.01)
        
    ser.close()
except Exception as e:
    print(f"Error: {e}")
