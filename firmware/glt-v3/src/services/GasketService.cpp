#include "GasketService.h"
#include "core/Logger.h"

namespace GLT {

GasketService::GasketService() 
    : pin_(0), lastUpdate_(0), adcRaw_(0), contaPressure_(0), pressureSum_(0), pressureAvg_(0) {}

void GasketService::begin(uint8_t pin) {
    pin_ = pin;
    pinMode(pin_, INPUT); // Analog giriş
    // İlk değerleri ata
    adcRaw_ = analogRead(pin_);
    contaPressure_ = adcRaw_;
    pressureAvg_ = adcRaw_; // Başlangıçta ortalama anlık değere eşit olsun
    
    LOG_INFO(LogCategory::SENSOR, "Conta Basıncı Servisi Başlatıldı (Pin: %d)", pin_);
}

void GasketService::update() {
    // Okuma sıklığı: Her döngüde (Kullanıcı notu: "Okuma her döngüde yapılıyor")
    // Ancak çok sık olursa performansı etkileyebilir. 
    // Şimdilik her çağrıldığında okuyoruz.

    // 1. İki kez okuma (Stabilizasyon için)
    adcRaw_ = analogRead(pin_);
    adcRaw_ = analogRead(pin_); 
    
    // 2. Minimum eşik kontrolü
    // "if (ADC_Ma_In_2 < 450) ADC_Ma_In_2 = 200;"
    if (adcRaw_ < 450) {
        adcRaw_ = 200;
    }
    
    // 3. Ham değeri ata
    contaPressure_ = adcRaw_;
    
    // 4. Filtreleme (Weighted Moving Average)
    // "Conta_Pressure_Toplam = Conta_Pressure_Avarage * 4 + Conta_Pressure;"
    // "Conta_Pressure_Avarage = Conta_Pressure_Toplam / 5;"
    pressureSum_ = pressureAvg_ * 4 + contaPressure_;
    pressureAvg_ = pressureSum_ / 5;
    
    // 5. Sınır kontrolü (Opsiyonel ama kodda var)
    /*
    if (pressureAvg_ < 256) {
        pressureAvg_ = 256;
    }
    */
    // "Conta_Pressure_Avarage > 500000" kontrolü long için anlamsız (zaten 4095 max)
    // Ama eğer pressureAvg_ unsigned long ise ve taşma olursa?
    // 12-bit ADC max 4095. 4095*4 + 4095 = 20475. Taşma olmaz.
}

uint16_t GasketService::getRawValue() const {
    return (uint16_t)pressureAvg_; // Filtrelenmiş ham veri
}

float GasketService::getPressure() const {
    // Kalibrasyon: (Raw - Offset) * Multiplier
    // Config'deki değerleri kullan
    float val = (float)pressureAvg_;
    float offset = Config::app.calibration.seal_offset;
    float mult = Config::app.calibration.seal_multiplier;
    
    float result = (val - offset) * mult;
    if (result < 0) result = 0;
    
    return result;
}

} // namespace GLT
