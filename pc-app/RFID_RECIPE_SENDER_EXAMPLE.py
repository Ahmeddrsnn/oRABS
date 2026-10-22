"""
ESP32 Test Cihazı - RFID Recipe Gönderme Örneği
================================================

Her RFID kartına özel test parametreleri göndermek için kullanılır.

Recipe Format (8 parametre - tire ile ayrılmış):
p1-p2-p3-p4-p5-p6-p7-p8

Parametreler:
-------------
p1: inflationMaxTime     - Şişirme max süresi (sn)          [Örnek: 10]
p2: inflationPascal      - Hedef basınç (Pa)                [Örnek: 3000]
p3: stabilizationTime    - Dengeleme süresi (sn)            [Örnek: 5]
p4: reinflateThreshold   - Yeniden şişirme eşiği (Pa)       [Örnek: 2800]
p5: maxReinflateCount    - (KULLANILMIYOR - sadece parse)   [Örnek: 3]
p6: failThreshold        - Ani düşüş limiti (Pa) - ÖNEMLI! [Örnek: 150]
p7: testDuration         - Test süresi (sn)                 [Örnek: 30]
p8: successDropPascal    - Test bitimi max düşüş (Pa)       [Örnek: 200]

p6 Açıklama:
-----------
Conditioning bitiminden sonra bu değer kadar düşüş olursa IMMEDIATE FAIL.
Örnek: Conditioning bitimi 3000 Pa, p6=150 ise → 2850 Pa'nın altına düşerse FAIL

p8 Açıklama:
-----------
Test süresi bittiğinde toplam düşüş bu değerden fazlaysa FAIL.
Örnek: Test başı 3000 Pa, test sonu 2850 Pa, düşüş 150 Pa, p8=200 ise → PASS

"""

import json
import serial
import time

# ============================================================================
# ESP-NOW Protokolü - RFID Recipe Gönderme
# ============================================================================

def send_rfid_recipe(ser, rfid_hex, port, recipe, recipe_name):
    """
    ESP32'ye RFID recipe gönderir
    
    Args:
        ser: Serial port objesi
        rfid_hex: RFID kartı hex formatında (string) - Örnek: "0x12345678"
        port: Port numarası (1-50)
        recipe: Recipe string - Örnek: "10-3000-5-2800-3-150-30-200"
        recipe_name: Recipe ismi - Örnek: "Eldiven Model A"
    """
    cmd = {
        "cmd": "SET_TAG_CONFIG",
        "rfid": rfid_hex,
        "port": port,
        "recipe": recipe,
        "recipe_name": recipe_name
    }
    
    json_cmd = json.dumps(cmd)
    ser.write((json_cmd + "\n").encode('utf-8'))
    print(f"✅ Gönderildi: {rfid_hex} → Port {port} | {recipe_name}")
    print(f"   Recipe: {recipe}")
    time.sleep(0.1)  # ESP32'nin işlemesi için bekle


# ============================================================================
# Örnek Kullanım
# ============================================================================

if __name__ == "__main__":
    # Serial Port Ayarları (ESP32 Master veya direkt ESP32 Test Cihazı)
    COM_PORT = "COM3"  # Kendi COM portunuzu yazın
    BAUD_RATE = 115200
    
    try:
        # Serial bağlantısı aç
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
        print(f"📡 Bağlantı kuruldu: {COM_PORT}")
        time.sleep(2)  # Bağlantı stabilizasyonu
        
        # ========================================================================
        # ÖRNEK 1: İnce Eldiven - Sıkı Test (Hızlı)
        # ========================================================================
        send_rfid_recipe(
            ser,
            rfid_hex="0x12345678",
            port=1,
            recipe="5-2000-3-1900-0-80-15-50",
            recipe_name="Ince_Eldiven_S"
        )
        # Açıklama:
        # - 5 sn max şişirme
        # - 2000 Pa hedef
        # - 3 sn dengeleme
        # - 80 Pa ani düşüş → FAIL (çok hassas)
        # - 15 sn test
        # - 50 Pa toplam düşüş → FAIL (çok sıkı)
        
        # ========================================================================
        # ÖRNEK 2: Standart Eldiven - Normal Test
        # ========================================================================
        send_rfid_recipe(
            ser,
            rfid_hex="0x87654321",
            port=2,
            recipe="10-3000-5-2800-0-150-30-200",
            recipe_name="Standart_M"
        )
        # Açıklama:
        # - 10 sn max şişirme
        # - 3000 Pa hedef (yüksek basınç)
        # - 5 sn dengeleme
        # - 150 Pa ani düşüş → FAIL (normal hassaslık)
        # - 30 sn test
        # - 200 Pa toplam düşüş → FAIL
        
        # ========================================================================
        # ÖRNEK 3: Kalın Eldiven - Toleranslı Test (Yavaş)
        # ========================================================================
        send_rfid_recipe(
            ser,
            rfid_hex="0xAABBCCDD",
            port=3,
            recipe="15-3500-10-3300-0-250-60-300",
            recipe_name="Kalin_Eldiven_L"
        )
        # Açıklama:
        # - 15 sn max şişirme
        # - 3500 Pa hedef (çok yüksek)
        # - 10 sn dengeleme (uzun)
        # - 250 Pa ani düşüş → FAIL (toleranslı)
        # - 60 sn test (uzun)
        # - 300 Pa toplam düşüş → FAIL (toleranslı)
        
        # ========================================================================
        # ÖRNEK 4: Quality Control - Çok Sıkı Test
        # ========================================================================
        send_rfid_recipe(
            ser,
            rfid_hex="0x11223344",
            port=4,
            recipe="10-2800-5-2700-0-50-30-30",
            recipe_name="QC_Strict"
        )
        # Açıklama:
        # - 50 Pa ani düşüş → FAIL (küçük delik bile yakalar)
        # - 30 Pa toplam düşüş → FAIL (çok sıkı - sıfır kaçak)
        
        # ========================================================================
        # ÖRNEK 5: Hızlı Test - Üretim Hattı
        # ========================================================================
        send_rfid_recipe(
            ser,
            rfid_hex="0x55667788",
            port=5,
            recipe="5-2500-2-2400-0-120-10-80",
            recipe_name="Hizli_Uretim"
        )
        # Açıklama:
        # - 5 sn max şişirme (hızlı)
        # - 2 sn dengeleme (çok hızlı)
        # - 10 sn test (çok hızlı)
        # - Toplam ~17 saniye (hızlı üretim için)
        
        print("\n✅ Tüm recipe'ler gönderildi!")
        print("\n💡 Test için:")
        print("   1. İlgili RFID kartını okutun")
        print("   2. Conta şişirin (Mount)")
        print("   3. Test Start'a basın")
        print("   4. Sistem o RFID'nin recipe'sine göre test yapacak")
        
        ser.close()
        
    except serial.SerialException as e:
        print(f"❌ Serial port hatası: {e}")
        print(f"   Kontrol edin: {COM_PORT} portu açık mı?")
    except Exception as e:
        print(f"❌ Hata: {e}")


# ============================================================================
# GUI/Dashboard İçinden Kullanım (PyQt5)
# ============================================================================

def send_recipe_from_gui(serial_object, rfid, port, p1, p2, p3, p4, p6, p7, p8, name):
    """
    GUI'den her parametreyi ayrı input olarak alıp recipe oluşturur
    
    Args:
        p1: Şişirme max süresi (int)
        p2: Hedef basınç (int)
        p3: Dengeleme süresi (int)
        p4: Yeniden şişirme eşiği (int)
        p6: Ani düşüş limiti (int)
        p7: Test süresi (int)
        p8: Test bitimi max düşüş (int)
    """
    # p5 kullanılmıyor ama format uyumluluğu için 0 gönder
    recipe = f"{p1}-{p2}-{p3}-{p4}-0-{p6}-{p7}-{p8}"
    send_rfid_recipe(serial_object, rfid, port, recipe, name)


# ============================================================================
# Toplu RFID Kaydı (CSV'den Okuma)
# ============================================================================

def bulk_register_from_csv(ser, csv_file):
    """
    CSV dosyasından toplu RFID recipe yükler
    
    CSV Format:
    RFID,Port,Name,p1,p2,p3,p4,p6,p7,p8
    0x12345678,1,Ince_S,5,2000,3,1900,80,15,50
    0x87654321,2,Standart_M,10,3000,5,2800,150,30,200
    """
    import csv
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            recipe = f"{row['p1']}-{row['p2']}-{row['p3']}-{row['p4']}-0-{row['p6']}-{row['p7']}-{row['p8']}"
            send_rfid_recipe(
                ser,
                rfid_hex=row['RFID'],
                port=int(row['Port']),
                recipe=recipe,
                recipe_name=row['Name']
            )
            time.sleep(0.5)  # ESP32'nin işlemesi için bekleme


# ============================================================================
# Recipe Validasyonu
# ============================================================================

def validate_recipe_params(p1, p2, p3, p4, p6, p7, p8):
    """
    Recipe parametrelerinin mantıklı olup olmadığını kontrol eder
    """
    errors = []
    
    # p1: 0-60 sn arası
    if not (0 < p1 <= 60):
        errors.append(f"p1 (Şişirme süresi) mantıksız: {p1}")
    
    # p2: 100-5000 Pa arası
    if not (100 <= p2 <= 5000):
        errors.append(f"p2 (Hedef basınç) mantıksız: {p2}")
    
    # p3: 0-30 sn arası
    if not (0 < p3 <= 30):
        errors.append(f"p3 (Dengeleme süresi) mantıksız: {p3}")
    
    # p4: p2'den küçük olmalı
    if p4 >= p2:
        errors.append(f"p4 (Yeniden şişirme eşiği: {p4}) p2'den küçük olmalı ({p2})")
    
    # p6: Makul bir düşüş limiti (10-500 Pa)
    if not (10 <= p6 <= 500):
        errors.append(f"p6 (Ani düşüş limiti) mantıksız: {p6}")
    
    # p7: 5-120 sn arası
    if not (5 <= p7 <= 120):
        errors.append(f"p7 (Test süresi) mantıksız: {p7}")
    
    # p8: p6'dan büyük olmalı (toplam düşüş > ani düşüş)
    if p8 < p6:
        errors.append(f"p8 (Toplam düşüş: {p8}) p6'dan büyük olmalı ({p6})")
    
    return errors


# ============================================================================
# Test
# ============================================================================
if __name__ == "__main__":
    # Validasyon örneği
    errors = validate_recipe_params(
        p1=10, p2=3000, p3=5, p4=2800, p6=150, p7=30, p8=200
    )
    if errors:
        print("⚠️ Recipe hataları:")
        for err in errors:
            print(f"   - {err}")
    else:
        print("✅ Recipe parametreleri geçerli")
