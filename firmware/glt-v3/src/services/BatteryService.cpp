#include "services/BatteryService.h"
#include "core/Logger.h"
#include "services/DwinService.h"

namespace GLT {

// Statik Sabitler (Kalibrasyon - Yeni OpAmp Kazancı)
// 19.93V @ 2122 ADC
// 9.90V @ 1001 ADC
// m = (19.93 - 9.90) / (2122 - 1001) = 10.03 / 1121 = 0.00894737
// b = 9.90 - (0.00894737 * 1001) = 9.90 - 8.956 = 0.944
const float BatteryService::CAL_SLOPE = 0.0089474f;
const float BatteryService::CAL_OFFSET = 0.9437f;

// Voltaj Eşikleri (18.5V = %100 tam şarj olarak ayarlandı)
const float BatteryService::V_100 = 18.5f;
const float BatteryService::V_85 = 17.5f;
const float BatteryService::V_50 = 16.5f;
const float BatteryService::V_10 = 15.8f;
const float BatteryService::V_0  = 15.0f;

BatteryService::BatteryService()
    : readingIndex_(0), firstReadingsDone_(false), lastReadTime_(0),
      readInterval_(0), voltage_(0.0f), percentage_(0), rawADC_(0) {
  memset(readings_, 0, sizeof(readings_));
}

void BatteryService::begin() {
  // ADC Pin Setup (GPIO 5)
  pinMode(PIN_ADC, INPUT);
  analogReadResolution(12); // ESP32 Default but explicit is good (0-4095)

  LOG_INFO(LogCategory::CORE, "Pil Servisi Başlatıldı (Pin: %d)", PIN_ADC);
}

int BatteryService::readRawADC() {
  long sum = 0;
  // 30 örnek alıp ortalamasını hesapla (gürültü azaltma)
  for (int i = 0; i < 30; i++) {
    sum += analogRead(PIN_ADC);
  }
  return sum / 30;
}

void BatteryService::update() {
  unsigned long now = millis();

  if (now - lastReadTime_ >= (unsigned long)readInterval_) {
    lastReadTime_ = now;

    // Yeni ölçümü al ve filtreye ekle
    int raw = readRawADC();
    readings_[readingIndex_] = raw;
    readingIndex_ = (readingIndex_ + 1) % FILTER_WINDOW;

    // İlk 10 ölçüm döngüsü tamamlandı mı?
    if (readingIndex_ == 0 && !firstReadingsDone_) {
      firstReadingsDone_ = true;
      readInterval_ = 2000; // İlk dolumdan sonra 2 saniyede bir ölçüm yap
      LOG_INFO(LogCategory::CORE,
               "Pil filtresi doldu (10 örnek), yavaş ölçüm moduna geçildi.");
    }

    // Voltaj ve Yüzde Hesapla
    float avgADC = 0;
    if (firstReadingsDone_) {
      // 10 örneğin ortalamasını al
      long sum = 0;
      for (int i = 0; i < FILTER_WINDOW; i++) {
        sum += readings_[i];
      }
      avgADC = (float)sum / FILTER_WINDOW;
    } else {
      // Filtre dolana kadar anlık değeri kullan (Hızlı başlangıç)
      avgADC = raw;
    }

    // Kalibreli Voltaj Hesabı: y = mx + b
    float calibratedV = (avgADC * CAL_SLOPE) + CAL_OFFSET;

    // Negatif veya çok düşük değerleri sıfırla
    if (calibratedV < 0.0f)
      calibratedV = 0.0f;

    voltage_ = calibratedV;
    percentage_ = calculatePercentage(voltage_);
    rawADC_ = (int)avgADC;

    // DWIN Güncelleme (Değiştiyse veya periyodik)
    static int lastSentPct = -1;
    if (lastSentPct != percentage_) {
      lastSentPct = percentage_;
      // İkonu gönder
      DwinService::getInstance().updateBattery(getIconIndex());
    }

    // Raw değeri her zaman gönder (veya değiştiğinde) - Kullanıcı isteği 0x700a
    static int lastSentRaw = -1;
    if (abs(lastSentRaw - rawADC_) > 2) { // Ufak değişimleri filtrele
      lastSentRaw = rawADC_;
      DwinService::getInstance().updateBatteryRaw(rawADC_);

      // 0x700C: Calibrated Voltage (x100 for 2 decimal places)
      // 14.00V -> 1400
      uint16_t vCmd = (uint16_t)(voltage_ * 100);
      DwinService::getInstance().updateBatteryVoltage(vCmd);
    }
  }
}

int BatteryService::calculatePercentage(float v) {
  float p = 0;

  if (v >= V_100) {
    p = 100.0;
  } else if (v >= V_85) {
    p = 85.0 + (v - V_85) * (100.0 - 85.0) / (V_100 - V_85);
  } else if (v >= V_50) {
    p = 50.0 + (v - V_50) * (85.0 - 50.0) / (V_85 - V_50);
  } else if (v >= V_10) {
    p = 10.0 + (v - V_10) * (50.0 - 10.0) / (V_50 - V_10);
  } else if (v >= V_0) {
    p = 0.0 + (v - V_0) * (10.0 - 0.0) / (V_10 - V_0);
  } else {
    p = 0.0;
  }

  return (int)p;
}

uint16_t BatteryService::getIconIndex() const {
  /*
   0-10%   -> 20 (Low/Critical)
   11-50%  -> 21
   51-85%  -> 22
   86-100% -> 23 (Full)
  */
  if (percentage_ <= 10)
    return 20;
  if (percentage_ <= 50)
    return 21;
  if (percentage_ <= 85)
    return 22;
  return 23;
}

} // namespace GLT
