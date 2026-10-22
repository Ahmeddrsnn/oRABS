# ESP32 Bağlantı Kılavuzu - Eldiven Test Sistemi

## İçindekiler
1. [Gereksinimler](#gereksinimler)
2. [ESP32 Donanım Bağlantısı](#esp32-donanım-bağlantısı)
3. [Firmware Yükleme](#firmware-yükleme)
4. [PC Uygulamasında Bağlantı](#pc-uygulamasında-bağlantı)
5. [Haberleşme Protokolü](#haberleşme-protokolü)
6. [Test Senaryoları](#test-senaryoları)
7. [Sorun Giderme](#sorun-giderme)

---

## Gereksinimler

### Donanım
- **ESP32 Development Board** (ESP32-DevKitC, ESP32-WROOM veya benzeri)
- **USB Kablosu** (Micro-USB veya USB-C, board'a göre)
- **Sensörler** (isteğe bağlı, gerçek test için):
  - Basınç sensörü (örn: MPX5700AP, 0-100 kPa)
  - Sıcaklık sensörü (örn: TMP36, LM35)
  - Kaçak algılama sensörü (dijital veya analog)
- **Pompa ve Valf** (isteğe bağlı, gerçek test için)

### Yazılım
- **Arduino IDE** (1.8.x veya 2.x) - [İndir](https://www.arduino.cc/en/software)
- **ESP32 Board Manager** (Arduino IDE'ye kurulacak)
- **ArduinoJson Library** (v6.x veya v7.x)
- **USB Driver** (CH340 veya CP2102, gerekirse)

---

## ESP32 Donanım Bağlantısı

### 1. Temel Bağlantı (Test Modu)

Sensör olmadan test için ESP32'yi doğrudan USB ile bilgisayara bağlayın:

```
[ESP32 Board] <--USB Kablosu--> [PC]
```

### 2. Tam Sistem Bağlantısı (Gerçek Test İçin)

**Pin Bağlantı Şeması:**

```
ESP32 Pin           Bağlantı
---------           ---------
GPIO 34 (ADC)   --> Basınç Sensörü Çıkışı
GPIO 35 (ADC)   --> Sıcaklık Sensörü Çıkışı
GPIO 32         --> Kaçak Sensörü Dijital Çıkışı
GPIO 25 (PWM)   --> Pompa Motor Kontrol (MOSFET üzerinden)
GPIO 26         --> Valf Kontrol (Röle veya MOSFET üzerinden)
GND             --> Tüm sensörlerin GND'si
3V3             --> Sensör besleme (3.3V toleranslı sensörler için)
```

**Örnek Bağlantı Diyagramı:**

```
                    ┌─────────────┐
                    │   ESP32     │
                    │             │
    Basınç ─────────┤ GPIO34      │
    Sensörü         │             │
                    │             │
    Sıcaklık ───────┤ GPIO35      │
    Sensörü         │             │
                    │             │
    Kaçak ──────────┤ GPIO32      │
    Dedektörü       │             │
                    │             │
                    │ GPIO25 ─────┼──MOSFET──► Pompa
                    │             │
                    │ GPIO26 ─────┼──Röle────► Valf
                    │             │
    USB Kablo ──────┤ USB Port    │
    PC'ye           │             │
                    └─────────────┘
```

### 3. Güç Besleme

**Opsiyonlar:**
- **USB Besleme:** Test ve geliştirme için yeterli (5V, ~500mA)
- **Harici Besleme:** Yüksek akım çeken pompa için gerekli olabilir (7-12V DC, düzenleyici ile)

---

## Firmware Yükleme

### Adım 1: Arduino IDE Kurulumu

1. **Arduino IDE'yi indirin ve kurun**
   - [arduino.cc/en/software](https://www.arduino.cc/en/software)

2. **ESP32 Board Desteğini Ekleyin**
   - Arduino IDE'yi açın
   - `File` → `Preferences` → `Additional Board Manager URLs`
   - Şu URL'yi ekleyin:
     ```
     https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
     ```
   - `Tools` → `Board` → `Boards Manager`
   - "ESP32" arayın ve "esp32 by Espressif Systems" kütüphanesini kurun

3. **ArduinoJson Kütüphanesini Kurun**
   - `Sketch` → `Include Library` → `Manage Libraries`
   - "ArduinoJson" arayın
   - "ArduinoJson by Benoit Blanchon" kütüphanesini kurun (v7.x önerilir)

### Adım 2: Firmware Kodunu Yükleme

1. **Örnek firmware'i açın:**
   ```
   C:\Users\ayasa\.gemini\antigravity\scratch\glove-test-system\esp32_example\glove_test_device.ino
   ```

2. **Board ayarlarını yapın:**
   - `Tools` → `Board` → `ESP32 Arduino` → `ESP32 Dev Module`
   - `Tools` → `Port` → COM portunu seçin (örn: COM3, COM4)
   - `Tools` → `Upload Speed` → `115200`

3. **Kodu düzenleyin (gerekirse):**
   ```cpp
   // Pin tanımlamalarını donanımınıza göre ayarlayın
   const int PRESSURE_SENSOR_PIN = 34;      // Basınç sensörü pini
   const int TEMPERATURE_SENSOR_PIN = 35;   // Sıcaklık sensörü pini
   const int LEAK_SENSOR_PIN = 32;          // Kaçak sensörü pini
   const int PUMP_CONTROL_PIN = 25;         // Pompa kontrol pini
   const int VALVE_CONTROL_PIN = 26;        // Valf kontrol pini
   ```

4. **Yükleyin:**
   - `Sketch` → `Upload` (veya Ctrl+U)
   - Upload tamamlanana kadar bekleyin
   - "Done uploading" mesajını görün

5. **Serial Monitor'u açın (test için):**
   - `Tools` → `Serial Monitor`
   - Baud rate: **115200**
   - "ESP32 Glove Test Device Ready" mesajını göreceksiniz

### Adım 3: Test Komutları (Serial Monitor'dan)

Serial Monitor'a şu komutları gönderebilirsiniz:

```json
{"cmd":"PING"}
```

Beklenen yanıt:
```json
{"status":"OK","message":"Pong"}
```

Test başlatma:
```json
{"cmd":"START_TEST","params":{"pressure":50.0,"temperature":25.0,"duration":60}}
```

---

## PC Uygulamasında Bağlantı

### Adım 1: COM Portunu Bulun

**Windows'ta:**
1. `Device Manager` açın (Aygıt Yöneticisi)
2. `Ports (COM & LPT)` bölümünü genişletin
3. ESP32'yi USB'ye takın
4. Yeni bir port görünecek (örn: "USB-SERIAL CH340 (COM3)")
5. COM numarasını not edin (örn: COM3)

**Alternatif (PowerShell):**
```powershell
[System.IO.Ports.SerialPort]::getportnames()
```

### Adım 2: Uygulamada Bağlan

1. **PC uygulamasını başlatın**
2. **Admin olarak giriş yapın** (admin/Admin123!)
3. **"Test Control" sekmesine gidin**
4. **ESP32 Connection bölümünde:**
   - COM Port dropdown'dan portunu seçin (örn: COM3)
   - **"Connect"** butonuna tıklayın

5. **Bağlantı durumu:**
   - ✅ Başarılı: "Status: Connected (COM3)" (yeşil)
   - ❌ Başarısız: Hata mesajı gösterilir

### Adım 3: Test Çalıştırma

Bağlandıktan sonra:

1. **Test Information:**
   - Glove Batch: Eldiven parti numarası girin
   - Glove Type: Tip seçin (Nitrile, Latex, vb.)

2. **Test Parameters:**
   - Target Pressure: Hedef basınç (kPa)
   - Target Temperature: Hedef sıcaklık (°C)
   - Test Duration: Test süresi (saniye)

3. **"Start Test"** butonuna tıklayın

4. **"Real-Time Monitoring" sekmesine** geçerek canlı verileri görün

---

## Haberleşme Protokolü

### JSON Tabanlı Protokol

**Baud Rate:** 115200  
**Format:** JSON (her mesaj yeni satır ile biter)  
**Encoding:** UTF-8

### PC'den ESP32'ye Komutlar

#### 1. PING (Bağlantı Testi)
```json
{"cmd": "PING", "timestamp": "2024-01-26T12:00:00"}
```
**Yanıt:**
```json
{"status": "OK", "message": "Pong"}
```

#### 2. START_TEST (Test Başlat)
```json
{
  "cmd": "START_TEST",
  "params": {
    "pressure": 50.0,
    "temperature": 25.0,
    "duration": 300
  },
  "timestamp": "2024-01-26T12:00:00"
}
```
**Yanıt:**
```json
{"status": "OK", "message": "Test started"}
```

#### 3. STOP_TEST (Test Durdur)
```json
{"cmd": "STOP_TEST", "timestamp": "2024-01-26T12:00:00"}
```
**Yanıt:**
```json
{"status": "OK", "message": "Test stopped"}
```

#### 4. GET_STATUS (Durum Sorgula)
```json
{"cmd": "GET_STATUS", "timestamp": "2024-01-26T12:00:00"}
```
**Yanıt:**
```json
{"type": "status", "status": "RUNNING", "timestamp": 12345}
```

### ESP32'den PC'ye Veri Akışı

#### Gerçek Zamanlı Sensör Verisi
```json
{
  "type": "data",
  "pressure": 50.5,
  "temperature": 25.3,
  "leak_detected": false,
  "timestamp": 12345
}
```

**Gönderim Sıklığı:** Her 100ms'de bir

#### Durum Güncellemeleri
```json
{
  "type": "status",
  "status": "IDLE",
  "timestamp": 12345
}
```

**Durum Değerleri:**
- `IDLE`: Boşta
- `RUNNING`: Test çalışıyor
- `ERROR`: Hata durumu

---

## Test Senaryoları

### Senaryo 1: Sensörsüz Test (Simülasyon)

Firmware'de sensör okumalarını simüle edin:

```cpp
float readPressure() {
  // Gerçek sensör yerine sabit değer + gürültü
  return targetPressure + random(-100, 100) / 100.0;
}

float readTemperature() {
  // Gerçek sensör yerine sabit değer
  return targetTemperature + random(-50, 50) / 100.0;
}
```

### Senaryo 2: Gerçek Sensörlerle Test

MPX5700AP basınç sensörü örneği:

```cpp
float readPressure() {
  int rawValue = analogRead(PRESSURE_SENSOR_PIN);
  float voltage = (rawValue / 4095.0) * 3.3;  // 12-bit ADC, 3.3V
  // MPX5700AP: 0.2V - 4.7V = 0-700 kPa
  float pressure = (voltage - 0.2) * (700.0 / 4.5);
  return pressure;
}
```

TMP36 sıcaklık sensörü örneği:

```cpp
float readTemperature() {
  int rawValue = analogRead(TEMPERATURE_SENSOR_PIN);
  float voltage = (rawValue / 4095.0) * 3.3;
  // TMP36: 10mV/°C, 0.5V = 0°C
  float temperature = (voltage - 0.5) * 100.0;
  return temperature;
}
```

### Senaryo 3: Kaçak Testi

```cpp
void runTest() {
  // ... sensör okuma ...
  
  // Basınç düşüşü kontrolü (kaçak tespiti)
  static float initialPressure = 0;
  if (millis() - testStartTime < 1000) {
    initialPressure = currentPressure;
  } else {
    float pressureDrop = initialPressure - currentPressure;
    if (pressureDrop > 5.0) {  // 5 kPa düşüş = kaçak
      leakDetected = true;
    }
  }
  
  sendData();
}
```

---

## Sorun Giderme

### Problem 1: COM Portu Görünmüyor

**Çözümler:**
1. **USB sürücüsünü kontrol edin:**
   - CH340 Driver: [sparks.gogo.co.nz/ch340.html](http://www.wch.cn/downloads/CH341SER_ZIP.html)
   - CP2102 Driver: [silabs.com](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers)

2. **Farklı USB portu deneyin**

3. **ESP32'yi resetleyin:**
   - Board üzerindeki BOOT butonuna basılı tutun
   - EN (Reset) butonuna basıp bırakın
   - BOOT butonunu bırakın

### Problem 2: Upload Hatası

**Hata:** "Failed to connect to ESP32"

**Çözüm:**
1. COM port seçimini kontrol edin
2. Upload speed'i düşürün (921600 → 115200)
3. USB kablosunu değiştirin (veri kablosu olduğundan emin olun)

### Problem 3: ESP32 Yanıt Vermiyor

**Kontroller:**
1. **Serial Monitor'u açın:**
   - Baud rate = 115200
   - "ESP32 Glove Test Device Ready" mesajını görün

2. **Manuel test gönderin:**
   ```json
   {"cmd":"PING"}
   ```
   
3. **Kodu tekrar yükleyin**

### Problem 4: PC Uygulaması Bağlanamıyor

**Çözümler:**
1. **COM portunu kontrol edin:**
   - Device Manager'da doğru port numarasını görün
   - Uygulamada aynı portu seçin

2. **ESP32'nin hazır olduğunu doğrulayın:**
   - Serial Monitor'da "Ready" mesajı
   - Yeşil LED yanıyor (varsa)

3. **Baud rate eşleştirmesi:**
   - ESP32 firmware: 115200
   - PC uygulama: 115200 (settings.json'da)

4. **Başka program kullanmadığından emin olun:**
   - Serial Monitor açık değil
   - Başka seri port yazılımı yok

### Problem 5: Veri Gelmiyor

**Debugging:**

ESP32 firmware'e debug ekleme:

```cpp
void sendData() {
  StaticJsonDocument<256> doc;
  
  doc["type"] = "data";
  doc["pressure"] = currentPressure;
  doc["temperature"] = currentTemperature;
  doc["leak_detected"] = leakDetected;
  doc["timestamp"] = millis();
  
  // Debug çıktısı
  Serial.print("DEBUG: Sending - ");
  serializeJson(doc, Serial);
  Serial.println();
}
```

PC uygulamasında ESP32 log görme:
- Test Control sekmesindeki "Test Log" alanını kontrol edin

---

## USB Sürücü Kurulumu

### Windows için CH340 Sürücü

1. Sürücüyü indirin: [CH340 Driver Download](http://www.wch.cn/downloads/CH341SER_ZIP.html)
2. ZIP dosyasını açın
3. `SETUP.EXE` çalıştırın
4. "Install" tıklayın
5. Bilgisayarı yeniden başlatın
6. ESP32'yi takın, Device Manager'da görmeli

### Windows 11 Güvenlik Uyarısı

Eğer "Windows protected your PC" uyarısı alırsanız:
1. "More info" tıklayın
2. "Run anyway" seçin

---

## Örnek Test Süreci

### Adım Adım Tam Test

1. **Donanım Hazırlığı:**
   - ESP32'yi USB ile PC'ye takın
   - COM portunun Device Manager'da göründüğünden emin olun

2. **Firmware Yükleme:**
   - Arduino IDE'de glove_test_device.ino açın
   - Board: ESP32 Dev Module, Port: COM3 (sizinki)
   - Upload edin

3. **Bağlantı Testi:**
   - Serial Monitor açın (115200 baud)
   - "ESP32 Glove Test Device Ready" görün
   - `{"cmd":"PING"}` gönderin → `{"status":"OK"...}` alın

4. **PC Uygulaması:**
   - start.bat ile uygulamayı başlatın
   - admin/Admin123! ile giriş yapın
   - Test Control → COM3 seçin → Connect

5. **Test Çalıştırma:**
   - Batch: "TEST-001"
   - Type: Nitrile
   - Pressure: 50 kPa
   - Temperature: 25°C
   - Duration: 60 saniye
   - Start Test

6. **Monitoring:**
   - Real-Time Monitoring sekmesine geçin
   - Grafiklerde veri akışını izleyin

7. **Rapor:**
   - Test bitince Reports & Data sekmesine gidin
   - TEST-001'i seçin → Generate PDF Report
   - Rapor otomatik açılır

---

## İleri Seviye: Kendi Sensörlerinizi Entegre Etme

### Sensör Ekleme Template

```cpp
// Yeni sensör tanımı
const int YOUR_SENSOR_PIN = 33;  // Kullanılmayan bir GPIO

void setup() {
  pinMode(YOUR_SENSOR_PIN, INPUT);
}

float readYourSensor() {
  int rawValue = analogRead(YOUR_SENSOR_PIN);
  // Kendi kalibrasyonunuzu yapın
  float calibratedValue = rawValue * YOUR_CALIBRATION_FACTOR;
  return calibratedValue;
}

void sendData() {
  StaticJsonDocument<256> doc;
  
  // Mevcut alanlar
  doc["type"] = "data";
  doc["pressure"] = currentPressure;
  doc["temperature"] = currentTemperature;
  
  // Yeni sensör verisi
  doc["your_sensor"] = readYourSensor();
  
  serializeJson(doc, Serial);
  Serial.println();
}
```

---

## Özet Kontrol Listesi

- [ ] Arduino IDE kurulu
- [ ] ESP32 board support eklendi
- [ ] ArduinoJson kütüphanesi kurulu
- [ ] USB sürücü yüklü (gerekirse)
- [ ] Firmware ESP32'ye yüklendi
- [ ] Serial Monitor'da "Ready" mesajı görüldü
- [ ] COM port numarası tespit edildi
- [ ] PC uygulaması başlatıldı
- [ ] ESP32 bağlantısı başarılı
- [ ] Test çalıştırıldı
- [ ] Veri akışı gözlemlendi
- [ ] PDF rapor oluşturuldu

---

**Sorular veya sorunlar için:**
- Serial Monitor çıktısını kontrol edin
- Test Log alanını inceleyin
- Audit Trail'de bağlantı kayıtlarına bakın

**Başarılar! 🎉**
