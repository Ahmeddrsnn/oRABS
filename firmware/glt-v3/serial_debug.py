import serial
import sys
import time

def monitor(port='COM23', baudrate=115200):
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        print(f"--- Monitoring {port} ---")
        while True:
            if ser.in_waiting:
                # Use errors='replace' and encode to handle non-ascii in same terminals
                line_raw = ser.readline()
                try:
                    line = line_raw.decode('utf-8', errors='replace').strip()
                    if line:
                        # Print as ascii to avoid codec errors in constrained terminals
                        # or just bypass the print error
                        sys.stdout.buffer.write(line.encode('utf-8') + b'\n')
                        sys.stdout.flush()
                except Exception as e:
                    print(f"Error decoding: {e}")
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
