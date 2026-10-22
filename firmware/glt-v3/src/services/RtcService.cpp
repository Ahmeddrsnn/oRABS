#include "services/RtcService.h"
#include "core/Logger.h"
#include "services/DwinService.h" // For updating display
#include <Wire.h>

namespace GLT {

RtcService::RtcService() {
}

void RtcService::begin() {
  // I2C başlatma (Kullanıcı isteği: Wire.begin(9, 8), 100kHz)
  Wire.begin(9, 8);
  Wire.setClock(100000);

  // DS3231'i 24 saatlik moda zorla
  myRTC_.setClockMode(false);

  LOG_INFO(LogCategory::CORE, "RTC Servisi Başlatıldı (SDA:9, SCL:8, 24H mod)");

  // İlk okuma ve sync
  update();
}

void RtcService::update() {
  // Her döngüde okuma yapmak yerine belirli aralıklarla yapabiliriz
  // Ancak kullanıcı "RTC HAM OKUMA KODU"nu vermiş, bunu uygulayalım.
  // Bu kod bloklayıcı delay içeriyor (1ms). Bu yüzden her loop'ta çağırmak
  // sistemi yavaşlatabilir. Yine de kullanıcının verdiği mantığı uygulayalım
  // ama belki bir timer ile (örn: 1 saniyede bir).

  static unsigned long lastUpdate = 0;
  if (millis() - lastUpdate < 1000) {
    return;
  }
  lastUpdate = millis();

  // --- Kullanıcının Verdiği Okuma Mantığı ---
  delay(1);
  day_ = myRTC_.getDate(); // Gün okuma
  delay(1);
  day_ = myRTC_.getDate(); // İki kez okunuyor (stabilite için)
  delay(1);
  month_ = myRTC_.getMonth(century_); // Ay okuma
  delay(1);
  year_ = myRTC_.getYear(); // Yıl okuma
  delay(1);
  hour_ = myRTC_.getHour(h12Flag_, pmFlag_); // Saat okuma
  delay(1);
  minute_ = myRTC_.getMinute(); // Dakika okuma
  delay(1);

  // --- YIL ARALIĞI KONTROLÜ ---
  if (year_ > 45)
    year_ = 44; // RTC hatalı yıl döndürürse düzelt
  if (year_ < 23)
    year_ = 23;

  // --- DS3231 24H modda, dönüşüm gerekmez (0-23 direkt okunuyor) ---
  // Şimdilik sadece okunan değerleri DWIN'e gönderelim

  // DWIN Ekran Güncelleme
  // Adresler: Saat 0x6105, Dk 0x6016, Gün 0x6017, Ay 0x6018, Yıl 0x6019
  DwinService::getInstance().updateDateTime(hour_, minute_, day_, month_,
                                            year_);

  // Serial Debug (Opsiyonel)
  // LOG_INFO(LogCategory::CORE, "RTC: %02d:%02d %02d/%02d/20%02d", hour_,
  // minute_, day_, month_, year_);
}

void RtcService::setTime(uint16_t year, uint8_t month, uint8_t day,
                         uint8_t hour, uint8_t minute, uint8_t second) {
  // DS3231 expects 2-digit year (e.g. 24 for 2024)
  uint8_t y2 = (year > 2000) ? (year - 2000) : year;

  // Set DS3231 Time
  myRTC_.setYear(y2);
  myRTC_.setMonth(month);
  myRTC_.setDate(day);
  myRTC_.setHour(hour);
  myRTC_.setMinute(minute);
  myRTC_.setSecond(second);

  // Update internal members immediately to reflect changes without waiting for
  // next update()
  year_ = y2;
  month_ = month; // 1-12
  day_ = day;
  hour_ = hour;
  minute_ = minute;
  second_ = second;

  // Sync DWIN immediately
  DwinService::getInstance().updateDateTime(hour_, minute_, day_, month_,
                                            year_);

  LOG_INFO(LogCategory::CORE, "Saat Ayarlandı: 20%02d-%02d-%02d %02d:%02d:%02d",
           y2, month, day, hour, minute, second);
}

} // namespace GLT
