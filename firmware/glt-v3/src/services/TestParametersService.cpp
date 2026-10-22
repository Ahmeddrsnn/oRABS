#include "services/TestParametersService.h"
#include "config.h" // Added for Global Config Sync
#include "core/Logger.h"

namespace GLT {

TestParametersService *TestParametersService::instance_ = nullptr;

TestParametersService::TestParametersService() { instance_ = this; }

void TestParametersService::begin() {
  loadSettings();
  LOG_INFO(LogCategory::CORE, "TestParametersService baslatildi");
}

void TestParametersService::loadSettings() {
  if (!LittleFS.exists("/config.bin")) {
    LOG_WARN(LogCategory::CORE,
             "Config dosyası bulunamadı, NVS'den senkronize ediliyor");
    // CRITICAL FIX: Use Config::app (from NVS) as master source
    currentParams_.pressureOffset =
        Config::app.calibration.pressure_zero_offset;
    currentParams_.pressureMultiplier =
        Config::app.calibration.pressure_multiplier;
    currentParams_.sealOffset = Config::app.calibration.seal_offset;
    currentParams_.sealMultiplier = Config::app.calibration.seal_multiplier;

    // Save to config.bin for next boot
    saveSettings();
    return;
  }

  File file = LittleFS.open("/config.bin", "r");
  if (!file) {
    LOG_ERROR(LogCategory::CORE, "Config okuma hatası!");
    return;
  }

  if (file.size() == sizeof(TestParams)) {
    file.read((uint8_t *)&currentParams_, sizeof(TestParams));
    LOG_INFO(LogCategory::CORE, "Config LittleFS'den yüklendi");

    // CRITICAL FIX: REVERSE SYNC - Use Config::app as master source
    // PC tarafından gelen kalibrasyon değerleri Config::app'te saklanır (NVS)
    // Bu değerler currentParams_'a aktarılmalı (config.bin'i ezmek yerine)
    currentParams_.pressureOffset =
        Config::app.calibration.pressure_zero_offset;
    currentParams_.pressureMultiplier =
        Config::app.calibration.pressure_multiplier;
    currentParams_.sealOffset = Config::app.calibration.seal_offset;
    currentParams_.sealMultiplier = Config::app.calibration.seal_multiplier;

    // Save the synced values back to config.bin
    saveSettings();

    LOG_INFO(LogCategory::CORE,
             "Kalibrasyon NVS'den config.bin'e senkronize edildi");
  } else {
    LOG_WARN(LogCategory::CORE,
             "Config boyutu uyuşmuyor, varsayılanlar kullanılacak");
  }
  file.close();

  LOG_INFO(LogCategory::CORE, "Recipe Yuklendi: %s", getRecipeString().c_str());
}

void TestParametersService::saveSettings() {
  File file = LittleFS.open("/config.bin", "w");
  if (!file) {
    LOG_ERROR(LogCategory::CORE, "Config yazma hatası!");
    return;
  }

  file.write((uint8_t *)&currentParams_, sizeof(TestParams));
  file.close();
  LOG_INFO(LogCategory::CORE, "Recipe ve Kalibrasyon LittleFS'e Kaydedildi");
}

void TestParametersService::updateRecipe(const String &rawRecipe) {
  // Format: 10-3000-5-2800-3-2000-10
  int vals[7];
  int idx = 0;
  int strIdx = 0;

  // Parse logic matching demo code
  while (idx < 7 && strIdx < rawRecipe.length()) {
    int nextDiv = rawRecipe.indexOf('-', strIdx);
    if (nextDiv == -1)
      nextDiv = rawRecipe.length();

    String piece = rawRecipe.substring(strIdx, nextDiv);
    vals[idx++] = piece.toInt();
    strIdx = nextDiv + 1;
  }

  if (idx == 7) {
    currentParams_.inflationMaxTime = vals[0];
    currentParams_.inflationPascal = vals[1];
    currentParams_.stabilizationTime = vals[2];
    currentParams_.reinflateThreshold = vals[3];
    currentParams_.failThreshold = vals[4];
    currentParams_.testDuration = vals[5];
    currentParams_.successDropPascal = vals[6];

    saveSettings();
  } else {
    LOG_ERROR(LogCategory::CORE,
              "Recipe parse hatasi: 7 deger bekleniyor, %d bulundu. Raw: %s",
              idx, rawRecipe.c_str());
  }
}

void TestParametersService::setParam(const String &key, const String &value) {
  bool changed = false;

  if (key.equalsIgnoreCase("recipe")) {
    updateRecipe(value);
    return;
  }

  // Calibration Setters
  if (key.equalsIgnoreCase("PRESSURE_OFFSET")) {
    currentParams_.pressureOffset = value.toFloat();
    Config::app.calibration.pressure_zero_offset =
        (int32_t)currentParams_.pressureOffset; // Sync
    changed = true;
  } else if (key.equalsIgnoreCase("PRESSURE_MULT")) {
    currentParams_.pressureMultiplier = value.toFloat();
    Config::app.calibration.pressure_multiplier =
        currentParams_.pressureMultiplier; // Sync
    changed = true;
  } else if (key.equalsIgnoreCase("SEAL_OFFSET")) {
    currentParams_.sealOffset = value.toFloat();
    Config::app.calibration.seal_offset = currentParams_.sealOffset; // Sync
    changed = true;
  } else if (key.equalsIgnoreCase("SEAL_MULT")) {
    currentParams_.sealMultiplier = value.toFloat();
    Config::app.calibration.seal_multiplier =
        currentParams_.sealMultiplier; // Sync
    changed = true;
  }

  if (changed) {
    saveSettings();
    Config::saveToNVS(); // CRITICAL: Kalibrasyon değerlerini NVS'e kaydet!
    LOG_INFO(LogCategory::CORE, "Parametre guncellendi: %s = %s", key.c_str(),
             value.c_str());
  } else {
    LOG_WARN(LogCategory::CORE, "Bilinmeyen parametre: %s", key.c_str());
  }
}

String TestParametersService::getRecipeString() const {
  char buf[128];
  snprintf(buf, sizeof(buf), "%d-%d-%d-%d-%d-%d-%d",
           currentParams_.inflationMaxTime, currentParams_.inflationPascal,
           currentParams_.stabilizationTime, currentParams_.reinflateThreshold,
           currentParams_.failThreshold, currentParams_.testDuration,
           currentParams_.successDropPascal);
  return String(buf);
}

uint32_t TestParametersService::calculateCRC() const {
  const uint8_t *data = (const uint8_t *)&currentParams_;
  size_t len = sizeof(TestParams);

  uint32_t crc = 0xFFFFFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int j = 0; j < 8; j++) {
      if (crc & 1)
        crc = (crc >> 1) ^ 0xEDB88320;
      else
        crc >>= 1;
    }
  }
  return ~crc;
}

} // namespace GLT
