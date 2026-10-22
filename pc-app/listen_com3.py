"""
COM3 Listener - Listen for periodic data
"""
import serial
import time
import sys

try:
    print("Listening to COM3 (Ctrl+C to stop)...")
    ser = serial.Serial('COM3', 115200, timeout=1)
    
    start_time = time.time()
    while time.time() - start_time < 10:  # Listen for 10 seconds
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f"RECV: {line}")
        time.sleep(0.01)
        
    ser.close()
    print("\nDone.")
    
except Exception as e:
    print(f"Error: {e}")
