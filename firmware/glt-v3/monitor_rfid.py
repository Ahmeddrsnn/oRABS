import serial
import time
import sys

def monitor(port='COM24', baudrate=115200):
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        print(f"Monitoring {port} @ {baudrate}...")
        
        while True:
            if ser.in_waiting:
                try:
                    line = ser.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        print(line)
                except Exception as e:
                    print(f"Error reading line: {e}")
            time.sleep(0.01)
            
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    monitor()
