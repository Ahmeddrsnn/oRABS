"""
COM3 Test Script - Cihaz Komutlarını Öğrenme
"""
import serial
import time

try:
    # COM3'e bağlan
    print("COM3'e bağlanılıyor...")
    ser = serial.Serial('COM3', 115200, timeout=2)
    time.sleep(2)  # ESP32'nin hazırlanması için bekle
    
    print("Bağlantı başarılı!")
    print("=" * 50)
    
    # Varsa bekleyen veriyi oku
    if ser.in_waiting > 0:
        welcome = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print("Hoş geldin mesajı:")
        print(welcome)
        print("=" * 50)
    
    # help komutunu gönder
    print("\n'help' komutu gönderiliyor...")
    ser.write(b'help\n')
    time.sleep(1)
    
    # Yanıtı oku
    if ser.in_waiting > 0:
        response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        print("\nCihazdan gelen komutlar:")
        print("=" * 50)
        print(response)
        print("=" * 50)
    else:
        print("Cihazdan yanıt gelmedi.")
        
        # Alternatif: Yeni satır karakteri olmadan dene
        print("\n'help' (yeni satır olmadan) deneniyor...")
        ser.write(b'help')
        time.sleep(1)
        
        if ser.in_waiting > 0:
            response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
            print("\nCihazdan gelen komutlar:")
            print("=" * 50)
            print(response)
            print("=" * 50)
    
    # Kapama
    ser.close()
    print("\nBağlantı kapatıldı.")
    
except serial.SerialException as e:
    print(f"HATA: {e}")
except Exception as e:
    print(f"Beklenmeyen hata: {e}")
