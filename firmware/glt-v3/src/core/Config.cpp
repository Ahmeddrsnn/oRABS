#include "config.h"
#include "Logger.h"
#include <LittleFS.h>

namespace GLT {

HardwareConfig Config::hardware;
AppConfig Config::app;

void Config::init() {
  // Hardware and app configs already have default values from struct
  // initialization
}

void Config::loadFromNVS() {
  if (!LittleFS.exists("/system.bin")) {
    LOG_WARN(LogCategory::CORE,
             "Sistem ayarları dosyası bulunamadı, varsayılanlar kullanılıyor");
    return;
  }

  File file = LittleFS.open("/system.bin", "r");
  if (!file) {
    LOG_ERROR(LogCategory::CORE, "Sistem ayarları okuma hatası!");
    return;
  }

  if (file.size() == sizeof(AppConfig)) {
    file.read((uint8_t *)&app, sizeof(AppConfig));
    LOG_INFO(LogCategory::CORE, "Sistem ayarları LittleFS üzerinden yüklendi");
  } else {
    LOG_WARN(LogCategory::CORE, "Sistem ayarları boyutu uyuşmuyor!");
  }
  file.close();

  // max_tags her zaman kod tarafından belirlenir — eski NVS değeri ezilmesin
  app.rfid.max_tags = 50;
}

void Config::saveToNVS() {
  File file = LittleFS.open("/system.bin", "w");
  if (!file) {
    LOG_ERROR(LogCategory::CORE,
              "Sistem ayarları kaydetme hatası: Dosya açılamadı!");
    return;
  }

  size_t written = file.write((uint8_t *)&app, sizeof(AppConfig));
  file.close();

  if (written == sizeof(AppConfig)) {
    LOG_INFO(LogCategory::CORE,
             "Sistem ayarları LittleFS'e başarıyla kaydedildi (%d bytes)",
             written);
  } else {
    LOG_ERROR(LogCategory::CORE,
              "Sistem ayarları yazma hatası! Yazılan: %d, Beklenen: %d",
              written, sizeof(AppConfig));
  }
}

} // namespace GLT
