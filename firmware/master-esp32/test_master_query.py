"""
Test Script: Master ESP-NOW Query Test
COM13 - Master device GET_NEW_RFIDS test
"""

import serial
import time
import sys

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

def test_master_query():
    print("=" * 60)
    print("MASTER ESP-NOW QUERY TEST (COM13)")
    print("=" * 60)
    
    # Connect to master
    try:
        ser = serial.Serial('COM13', 115200, timeout=2)
        print("[OK] COM13 baglandi (Master)")
        time.sleep(2)
        
        # Clear buffer
        ser.reset_input_buffer()
        
        # Test 1: Get help and slave list
        print("\n[TEST 1] Slave listesi aliniyor...")
        ser.write(b"help\n")
        time.sleep(2)
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print(response)
        
        # Check if slave exists
        if "TestAparati" not in response:
            print("\n[AUTO-FIX] TestAparati slave bulunamadi, ekleniyor...")
            # Known MAC from slave boot log: 70:04:1D:CD:88:14
            add_cmd = "addslave TestAparati 70:04:1D:CD:88:14"
            print(f"Komut: {add_cmd}")
            ser.write((add_cmd + "\n").encode('utf-8'))
            time.sleep(2)
            add_response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
            print(add_response)
            
            # Verify
            print("\n[VERIFY] Slave eklendi mi kontrol ediliyor...")
            ser.write(b"list\n")
            time.sleep(1)
            verify_response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
            print(verify_response)
            
            if "TestAparati" in verify_response:
                print("[OK] Slave basariyla eklendi!")
            else:
                print("[ERROR] Slave eklenemedi - devam ediliyor...")
        else:
            print("[OK] TestAparati slave mevcut")
        
        # Test 2: Query new RFIDs from slave
        print("\n[TEST 2] Slave'den yeni RFID'ler sorgulanıyor...")
        command = 'send TestAparati {"cmd":"GET_NEW_RFIDS"}'
        print(f"Komut: {command}")
        ser.write((command + "\n").encode('utf-8'))
        time.sleep(3)  # Wait for response from slave
        
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print("\n--- RESPONSE ---")
        print(response)
        print("--- END RESPONSE ---")
        
        # Test 3: Send test message
        print("\n[TEST 3] Test mesaji gonderiliyor...")
        ser.write(b'send TestAparati Hello from PC!\n')
        time.sleep(2)
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print(response)
        
        # Test 4: List slaves again
        print("\n[TEST 4] Slave listesi tekrar kontrol...")
        ser.write(b"list\n")
        time.sleep(1)
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print(response)
        
        print("\n" + "=" * 60)
        print("TEST TAMAMLANDI")
        print("=" * 60)
        print("\nBeklenen Sonuc:")
        print("- Slave listesinde TestAparati BAGLI gorunmeli")
        print("- GET_NEW_RFIDS response:")
        print('  [TestAparati] {"cmd":"NEW_RFIDS_RESPONSE","data":[...]}')
        print('  data: [{"rfid":"0x004FD0CF","port":1,"name":"...","admin":false}]')
        print("\nEger slave BAGLANTIKESILDI ise:")
        print("- Slave (COM11) calistigini kontrol edin")
        print("- Master'da tekrar slave ekleyin")
        
        ser.close()
        
    except serial.SerialException as e:
        print(f"[ERROR] Serial hata: {e}")
        print("\nKontrol:")
        print("- COM13 acik mi? (Arduino IDE serial monitor kapali olmali)")
        print("- Master ESP32 calisıyor mu?")
    except Exception as e:
        print(f"[ERROR] Hata: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_master_query()
