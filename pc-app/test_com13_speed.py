"""
Direct COM13 Speed Test
Measures actual message frequency and throughput
"""

import serial
import time
from datetime import datetime

def test_com13_speed():
    print("=" * 60)
    print("COM13 Veri Hizi Testi")
    print("=" * 60)
    
    try:
        # Connect to COM13
        ser = serial.Serial('COM13', 115200, timeout=0.01)
        print(f"[OK] COM13'e baglandi")
        time.sleep(1)
        
        # Clear buffer
        ser.reset_input_buffer()
        
        print("\n[~] 10 saniye boyunca veri akisi olculuyor...\n")
        
        start_time = time.time()
        message_count = 0
        stream_count = 0
        last_messages = []
        last_timestamp = None
        min_interval = float('inf')
        max_interval = 0
        intervals = []
        
        while time.time() - start_time < 10:
            if ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        current_time = time.time()
                        message_count += 1
                        
                        # Track STREAM messages specifically
                        if '@S:' in line:
                            stream_count += 1
                            
                            # Calculate interval
                            if last_timestamp is not None:
                                interval = (current_time - last_timestamp) * 1000  # ms
                                intervals.append(interval)
                                min_interval = min(min_interval, interval)
                                max_interval = max(max_interval, interval)
                            
                            last_timestamp = current_time
                            
                            # Show last 5 STREAM messages
                            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            display = f"[{timestamp}] {line[:80]}"
                            print(display)
                            last_messages.append(display)
                            if len(last_messages) > 5:
                                last_messages.pop(0)
                                
                except Exception as e:
                    pass
        
        duration = time.time() - start_time
        
        # Results
        print("\n" + "=" * 60)
        print("SONUCLAR")
        print("=" * 60)
        print(f"Sure:              {duration:.2f} saniye")
        print(f"Toplam Mesaj:      {message_count}")
        print(f"STREAM Mesaj:      {stream_count}")
        print(f"Mesaj/Saniye:      {message_count/duration:.2f}")
        print(f"STREAM/Saniye:     {stream_count/duration:.2f}")
        
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            print(f"\nSTREAM Araliklari:")
            print(f"  Ortalama:        {avg_interval:.1f} ms")
            print(f"  Minimum:         {min_interval:.1f} ms")
            print(f"  Maksimum:        {max_interval:.1f} ms")
            print(f"  Beklenen:        100 ms (10 mesaj/sn)")
            
            if avg_interval < 150:
                print(f"\n[OK] Veri akisi HIZLI! (~{1000/avg_interval:.1f} mesaj/sn)")
            else:
                print(f"\n[!] Veri akisi YAVAS! (Beklenen: 100ms, Gercek: {avg_interval:.1f}ms)")
        
        print("=" * 60)
        
        ser.close()
        
    except serial.SerialException as e:
        print(f"[HATA] COM13 acilamadi: {e}")
    except KeyboardInterrupt:
        print("\n\n[~] Test kullanici tarafindan durduruldu")

if __name__ == "__main__":
    test_com13_speed()
