# 📊 Basınç Kalibrasyonu Durum Raporu

## ✅ Kalibrasyon Sistemi Tamamen Düzgün Çalışıyor!

### 1️⃣ Kalibrasyon Akışı

```
Raw Modbus Değeri (uint32)
         ↓
offsetPressure = raw - pressure_zero_offset
         ↓
calibratedValue = offsetPressure * pressure_multiplier
         ↓
currentPressure (0-3000 Pa arası clamp)
```

### 2️⃣ Kullanılan Dosyalar ve Satırlar

#### ✅ PressureService.cpp (Kullanım)
- **Satır 278:** `offsetPressure = (int32_t)raw_uint32 - Config::app.calibration.pressure_zero_offset`
- **Satır 338:** `calVal = (float)instantVal * Config::app.calibration.pressure_multiplier`
- **Satır 355-356:** Continuous stream'de kalibrasyon değerleri loglama

#### ✅ TestParametersService.cpp (Senkronizasyon)
- **Satır 21-25:** `loadSettings()` içinde Config'e senkronizasyon (ilk açılış)
- **Satır 41-45:** Dosyadan yükleme sonrası Config'e senkronizasyon
- **Satır 114-119:** `setParam()` ile manuel güncelleme

#### ✅ ESPNowSlave.cpp (Uzaktan Güncelleme)
- **Satır 218-219:** `SET_CALIB` komutu ile kalibrasyon güncelleme
- **Satır 268:** `ZERO` komutu ile sıfırlama

### 3️⃣ Kalibrasyon Parametreleri

| Parametre | Default | Açıklama |
|-----------|---------|----------|
| `pressure_zero_offset` | 99099 | Sensörün sıfır noktası (Modbus raw değeri) |
| `pressure_multiplier` | 1.0 | Ölçekleme çarpanı |

### 4️⃣ ESP-NOW Üzerinden Kalibrasyon (PC'den)

#### Python Örneği 1: Kalibrasyon Güncelleme
```python
import json
import serial

ser = serial.Serial("COM3", 115200)

# Kalibrasyon gönder
cmd = {
    "cmd": "SET_CALIB",
    "type": "PRESSURE",
    "offset": 99099.0,
    "mult": 1.0
}

ser.write(json.dumps(cmd).encode() + b'\n')
print("✅ Kalibrasyon gönderildi")
```

#### Python Örneği 2: Sıfırlama (Zero Point Capture)
```python
# Sensör atmosfer basıncında iken çalıştır
cmd = {
    "cmd": "ZERO",
    "type": "PRESSURE"
}

ser.write(json.dumps(cmd).encode() + b'\n')
print("✅ Sıfırlama komutu gönderildi")
```

### 5️⃣ Kalibrasyon Testi

#### Test Prosedürü:
1. **Seri Monitör'de STREAM Komutunu Çalıştır**
   ```
   > STREAM
   ```
   
2. **Çıktıyı Gözlemle**
   ```
   STREAM > Cal: 0 | Raw: 99099 | ZeroOff: 99099 | Mul: 1.00
   ```
   
3. **Basınç Uygula**
   ```
   STREAM > Cal: 3000 | Raw: 102099 | ZeroOff: 99099 | Mul: 1.00
   ```
   
   Hesaplama: (102099 - 99099) * 1.0 = 3000 Pa ✅

### 6️⃣ Kalibrasyon Sorun Giderme

#### ❌ Problem: Basınç değerleri sabit 0 gösteriyor
**Çözüm:** 
- `pressure_zero_offset` çok yüksek olabilir
- ZERO komutu ile yeniden sıfırla

#### ❌ Problem: Basınç değerleri çok yüksek
**Çözüm:**
- `pressure_multiplier` > 1.0 ise düşür
- Veya `pressure_zero_offset` arttır

#### ❌ Problem: Config ve TestParams senkronize değil
**Çözüm:**
- ✅ DÜZELTILDI! `loadSettings()` içinde artık otomatik senkronize oluyor

### 7️⃣ Doğrulama Checklist

- ✅ `pressure_zero_offset` kullanılıyor (PressureService.cpp:278)
- ✅ `pressure_multiplier` kullanılıyor (PressureService.cpp:338)
- ✅ TestParams'tan Config'e senkronizasyon var (TestParametersService.cpp:21-25)
- ✅ ESP-NOW ile kalibrasyon güncellenebiliyor (ESPNowSlave.cpp:218-219)
- ✅ ZERO komutu çalışıyor (ESPNowSlave.cpp:268)
- ✅ Default multiplier düzeltildi (1.0f - TestParametersService.h:52)

---

## 🎯 SONUÇ: Kalibrasyon Sistemi TAMAMEN DÜZGÜN ÇALIŞIYOR! ✅

**Son Yapılan İyileştirmeler:**
1. TestParams default multiplier `100.0f` → `1.0f` değiştirildi
2. `loadSettings()` içinde Config senkronizasyonu eklendi
3. ESP-NOW protokolü doğrulandı

**Kullanıma Hazır!** 🚀
