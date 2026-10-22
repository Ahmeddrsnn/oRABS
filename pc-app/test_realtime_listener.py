"""
Real-time COM13 Listener WITHOUT GUI
Tests if Python can handle 100ms messages without PyQt
"""

import serial
import time
import sys
from datetime import datetime

def listen_realtime():
    print("=" * 80)
    print("GERÇEK ZAMANLI DİNLEYİCİ (GUI YOK - Sadece Python)")
    print("=" * 80)
    
    try:
        ser = serial.Serial('COM13', 115200, timeout=0.01)
        print(f"[OK] COM13'e bağlandı\n")
        
        ser.reset_input_buffer()
        
        message_count = 0
        stream_count = 0
        last_stream_time = None
        
        print("CANLI VERİ AKIŞI (Ctrl+C ile durdurun):\n")
        
        buffer = ""
        
        while True:
            # Fast polling like esp32_comm.py
            if ser.in_waiting > 0:
                try:
                    received = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    buffer += received
                except:
                    continue
                
                # Process lines
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    
                    if line:
                        message_count += 1
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        
                        # Track STREAM messages
                        if '@S:' in line:
                            stream_count += 1
                            current_time = time.time()
                            
                            interval_str = ""
                            if last_stream_time is not None:
                                interval = (current_time - last_stream_time) * 1000
                                interval_str = f" [Δ{interval:.1f}ms]"
                            
                            last_stream_time = current_time
                            
                            # Parse STREAM
                            if '[' in line and ']' in line:
                                parts = line.split('@S:')
                                if len(parts) >= 2:
                                    device = line[line.find('[')+1:line.find(']')]
                                    data = parts[1].split('|')
                                    if len(data) >= 12:
                                        rfid = data[0]
                                        port = data[1]
                                        recipe = data[11]
                                        
                                        print(f"[{timestamp}]{interval_str} {device}: RFID={rfid} Port={port} Recipe={recipe}")
                        
                        elif 'PING' in line:
                            print(f"[{timestamp}] >>> PING <<< {line}")
                        
                        elif 'HELLO' in line:
                            print(f"[{timestamp}] >>> HELLO <<< {line}")
                        
                        elif 'RFID_DETECTED' in line or 'RFID_REMOVED' in line:
                            print(f"[{timestamp}] >>> RFID EVENT <<< {line}")
                        
                        # Every 100 messages, show stats
                        if message_count % 100 == 0:
                            print(f"\n--- STATS: {message_count} mesaj, {stream_count} STREAM ---\n")
            else:
                time.sleep(0.001)  # 1ms sleep, same as esp32_comm.py
                
    except KeyboardInterrupt:
        print("\n\n[~] Test durduruldu")
        print(f"\nTOPLAM: {message_count} mesaj, {stream_count} STREAM")
    except serial.SerialException as e:
        print(f"[HATA] {e}")
    except Exception as e:
        print(f"[HATA] {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'ser' in locals():
            ser.close()

if __name__ == "__main__":
    listen_realtime()
