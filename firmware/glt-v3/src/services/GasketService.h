#ifndef GASKET_SERVICE_H
#define GASKET_SERVICE_H

#include <Arduino.h>
#include "config.h"

namespace GLT {

class GasketService {
public:
    GasketService();
    
    // Başlatma (Pin yapılandırması)
    void begin(uint8_t pin);
    
    // Ana döngüde çağrılacak (Okuma ve filtreleme)
    void update();
    
    // Ham veriyi döndür (0-4095)
    uint16_t getRawValue() const;
    
    // Kalibre edilmiş veriyi döndür (Bar veya belirlenen birim)
    float getPressure() const;

private:
    uint8_t pin_;
    unsigned long lastUpdate_;
    
    // Kullanıcı algoritması değişkenleri
    uint16_t adcRaw_;            // ADC_Ma_In_2
    long contaPressure_;         // Conta_Pressure
    unsigned long pressureSum_;  // Conta_Pressure_Toplam
    unsigned long pressureAvg_;  // Conta_Pressure_Avarage (Filtrelenmiş çıkış)
};

} // namespace GLT

#endif // GASKET_SERVICE_H
