"""
Test Script: Slave RFID Assignment via Serial
COM11 - Slave device RFID kayit testi
"""

import serial
import time
import sys

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

def test_slave_assignment():
    print("=" * 60)
    print("SLAVE RFID ASSIGNMENT TEST (COM11)")
    print("=" * 60)
    
    # Connect to slave
    try:
        ser = serial.Serial('COM11', 115200, timeout=2)
        print("[OK] COM11 baglandi")
        time.sleep(2)
        
        # Clear buffer
        ser.reset_input_buffer()
        
        # Test 1: Get current status
        print("\n[TEST 1] Durum kontrolü...")
        ser.write(b"STATUS\n")
        time.sleep(1)
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print(response)
        
        # Test 2: List current tags
        print("\n[TEST 2] Mevcut tag listesi...")
        ser.write(b"TAGS\n")
        time.sleep(1)
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print(response)
        
        # Test 3: Assign RFID to port
        print("\n[TEST 3] RFID port assignment...")
        print("Komut: ASSIGN:0x004FD0CF:1")
        ser.write(b"ASSIGN:0x004FD0CF:1\n")
        time.sleep(1)
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print(response)
        
        # Test 4: Verify assignment
        print("\n[TEST 4] Assignment doğrulaması...")
        ser.write(b"TAGS\n")
        time.sleep(1)
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print(response)
        
        # Test 5: Check next available port
        print("\n[TEST 5] Sıradaki boş port...")
        ser.write(b"NEXTPORT\n")
        time.sleep(1)
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print(response)
        
        print("\n" + "=" * 60)
        print("TEST TAMAMLANDI")
        print("=" * 60)
        print("\nBeklenen Sonuç:")
        print("- Tag 0x004FD0CF port 1'e atanmış olmalı")
        print("- isNewRecord=true (NVS'de)")
        print("- NEXTPORT komutu 2 döndürmeli")
        print("\nSonraki Adım:")
        print("- Master'dan GET_NEW_RFIDS sorgulanabilir")
        print("- Response: [{\"rfid\":\"0x004FD0CF\",\"port\":1,...}]")
        
        ser.close()
        
    except serial.SerialException as e:
        print(f"❌ Serial hata: {e}")
        print("\nKontrol:")
        print("- COM11 açık mı? (Arduino IDE serial monitor kapalı olmalı)")
        print("- Slave ESP32 çalışıyor mu?")
    except Exception as e:
        print(f"❌ Hata: {e}")

if __name__ == "__main__":
    test_slave_assignment()
