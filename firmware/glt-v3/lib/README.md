# I2cvoltaj - Proje Kütüphaneleri

## ✅ Dahil Edilen Kütüphaneler

Bu klasör, projenin kullandığı tüm Arduino kütüphanelerini içerir. **Ek kurulum gerekmez!**

### ESP32 Core Libraries (Dahili - ESP32 ile gelir)
- **WiFi** (v3.0.3) - ESP32 WiFi/ESP-NOW desteği
- **Preferences** (v3.0.3) - NVS (Non-Volatile Storage) yönetimi
- **LittleFS** (v3.0.3) - Dosya sistemi desteği
- **Wire** (v3.0.3) - I2C iletişimi

### Proje Kütüphaneleri (lib/ klasöründe hazır)
- **Adafruit_ADS1X15** (v2.6.1) - ADS1115 16-bit ADC desteği
  - Klasör: `lib/Adafruit_ADS1X15/`
  - Bağımlılık: Adafruit_BusIO
  
- **Adafruit_BusIO** (v1.17.4) - I2C/SPI/UART yardımcı kütüphane
  - Klasör: `lib/Adafruit_BusIO/`
  - Otomatik olarak Adafruit_ADS1X15 tarafından kullanılır

- **rdm6300** (latest) - RDM6300 RFID okuyucu kütüphanesi
  - Klasör: `lib/rdm6300/`
  - 125kHz RFID tag okuma desteği
  - GitHub: https://github.com/arduino12/rdm6300

## 🚀 Kurulum Gerekmez!

Python aracı (`esp32_flash_tool.py`) otomatik olarak lib/ klasöründeki kütüphaneleri kullanır:

```bash
# Python aracı arka planda şu komutu çalıştırır:
arduino-cli compile --fqbn "..." --libraries "lib" I2cvoltaj.ino
```

## 📦 Yeni Bilgisayarda Sadece ESP32 Core Gerekir

```bash
# 1. Arduino CLI kur (https://arduino.github.io/arduino-cli/)

# 2. ESP32 core'u yükle (tek seferlik)
arduino-cli core install esp32:esp32

# 3. Derle ve yükle - kütüphaneler zaten hazır!
python esp32_flash_tool.py --compile --upload --port COM3
```

## Proje Yapısı

```
I2cvoltaj/
├── I2cvoltaj.ino           # Ana dosya (setup ve loop)
├── config.h                # Pin tanımları ve sabitler
├── message_types.h         # ESP-NOW mesaj yapıları
├── espnow_handler.h/cpp    # ESP-NOW iletişim modülü
├── storage_handler.h/cpp   # FS ve NVS yönetimi
├── i2c_handler.h/cpp       # I2C, ADS1115, DS3231 yönetimi
├── worker_task.h/cpp       # Worker task (core 1)
└── lib/                    # Kütüphane klasörü (referans)
    └── README.md          # Bu dosya
```

## Board Ayarları (FQBN)

```
esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,CPUFreq=240,DebugLevel=none,DFUOnBoot=default,EventsCore=1,FlashMode=qio,FlashSize=4M,LoopCore=1,MSCOnBoot=default,PartitionScheme=no_fs,PSRAM=enabled,UploadMode=default,UploadSpeed=921600
```

## Derleme ve Yükleme

### Arduino CLI ile:
```bash
# Derleme
arduino-cli compile --fqbn "esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,CPUFreq=240,DebugLevel=none,DFUOnBoot=default,EventsCore=1,FlashMode=qio,FlashSize=4M,LoopCore=1,MSCOnBoot=default,PartitionScheme=no_fs,PSRAM=enabled,UploadMode=default,UploadSpeed=921600" I2cvoltaj.ino

# Yükleme
arduino-cli upload -p COM3 --fqbn "esp32:esp32:esp32s3:..." I2cvoltaj.ino
```

### Python GUI aracı ile:
```bash
python esp32_flash_tool.py
```

## Donanım Gereksinimleri

- ESP32-S3 (4MB Flash, PSRAM etkin)
- DS3231 RTC modülü (I2C: 0x68)
- ADS1115 ADC modülü (I2C: 0x48)
- I2C pinleri: SDA=GPIO8, SCL=GPIO9
- LED'ler: GPIO41, GPIO45

## Özellikler

- Dual-core FreeRTOS task yapısı
  - Core 0: ESP-NOW iletişimi
  - Core 1: Mesaj işleme, I2C, sensör okuma
- ESP-NOW kablosuz iletişim
- NVS ile kalıcı ayarlar
- LittleFS ile log kaydetme
- RTC zaman takibi
- ADC voltaj ölçümü (divider desteği)

## Lisans

Bu proje özel kullanım içindir.
