#include "services/RFIDService.h"
#include "config.h"
#include "core/Logger.h"
#include "services/ESPNowSlave.h" // For ESP-NOW notifications
#include "services/BatteryService.h"
#include "services/PressureService.h"
#include "services/TestStorageService.h"
#ifdef ESP32
#include <LittleFS.h>
#include <esp_rom_crc.h>

#endif

// Global instance from main.cpp
extern GLT::PressureService *pressureService;

// External ESP-NOW instance (defined in main.cpp)
extern GLT::ESPNowSlave *espNowSlave;

namespace GLT {

RFIDService::RFIDService(RFIDReader &rfidReader, uint8_t maxTags)
    : rfidReader_(rfidReader), maxTags_(maxTags), lastDetectedTag_(0),
      lastDetectTime_(0) {
  // Allocate tag array
  tags_ = new RFIDTag[maxTags_];

  // Initialize all tags
  for (int i = 0; i < maxTags_; i++) {
    tags_[i].id = 0;
    tags_[i].isAdmin = false;
    tags_[i].isActive = false;
    tags_[i].name[0] = '\0';
    tags_[i].portNumber = 0; // Unassigned
    tags_[i].isNewRecord = false;
  }
}

bool RFIDService::begin() {
  LOG_INFO(LogCategory::RFID, "Servis LittleFS üzerinden başlatılıyor...");

  if (!LittleFS.begin(true)) {
    LOG_ERROR(LogCategory::RFID, "LittleFS başlatılamadı!");
    return false;
  }

  loadFromFlash();
  LOG_INFO(LogCategory::RFID, "Servis hazır (%d tag yüklendi)",
           getActiveTagCount());
  return true;
}

void RFIDService::update() {
  static unsigned long lastVerboseLog = 0;
  if (millis() - lastVerboseLog > 2000) {
    lastVerboseLog = millis();
    LOG_VERBOSE(LogCategory::RFID,
                "RFID Service Loop Active (Reader Polling...)");
  }

  uint32_t newTag = rfidReader_.getNewTag();
  bool isPresent =
      rfidReader_.isTagPresent(); // Check if tag is physically present

  // If a tag is physically present (new or existing), refresh the timer
  // We only refresh if rfidReader_.isTagPresent() is true
  // Note: reduced debounce from 1000ms to 350ms for instant feel
  if (isPresent) {
    lastDetectTime_ = millis();
  }

  if (newTag != 0) {
    // New tag detected (initial placement)
    if (newTag != lastDetectedTag_) {
      lastDetectedTag_ = newTag;
      onTagDetected(newTag);
    }
  } else {
    // No NEW tag seen, but check for removal of existing tag
    // If we had a tag, and it's NOT present anymore, wait for debounce
    if (lastDetectedTag_ != 0 && !isPresent &&
        (millis() - lastDetectTime_ > 350)) {
      LOG_DEBUG(LogCategory::RFID, "Tag uzaklastirildi: 0x%08X",
                lastDetectedTag_);

      // Notify master via ESP-NOW
      if (espNowSlave && espNowSlave->isConnected()) {
        char buffer[128];
        snprintf(buffer, sizeof(buffer),
                 "{\"cmd\":\"RFID_REMOVED\",\"rfid\":\"0x%08X\"}",
                 lastDetectedTag_);
        espNowSlave->sendToMaster(buffer);
      }

      lastDetectedTag_ = 0;
    }
  }

  // Fast stream artık main.cpp loop'unda bağımsız çağrılıyor (UART modundan bağımsız)
}

bool RFIDService::addTag(uint32_t tagId, bool isAdmin, const char *name,
                         uint16_t portNumber) {
  // Check if tag already exists
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].id == tagId) {
      LOG_WARN(LogCategory::RFID, "Tag zaten kayıtlı: 0x%08X (Port: %d)", tagId,
               tags_[i].portNumber);
      return false;
    }
  }

  // Find empty slot
  int slot = -1;
  for (int i = 0; i < maxTags_; i++) {
    if (!tags_[i].isActive) {
      slot = i;
      break;
    }
  }

  if (slot == -1) {
    LOG_ERROR(LogCategory::RFID, "Tag veritabanı dolu!");
    return false;
  }

  // Add tag
  tags_[slot].id = tagId;
  tags_[slot].isAdmin = isAdmin;
  tags_[slot].isActive = true;
  tags_[slot].isNewRecord = true;      // Mark as new for PC sync
  tags_[slot].portNumber = portNumber; // Set default port

  if (name && strlen(name) > 0) {
    strncpy(tags_[slot].name, name, sizeof(tags_[slot].name) - 1);
    tags_[slot].name[sizeof(tags_[slot].name) - 1] = '\0';
  } else {
    snprintf(tags_[slot].name, sizeof(tags_[slot].name), "Tag%02d", slot + 1);
  }

  saveToFlash();
  LOG_INFO(LogCategory::RFID, "Tag eklendi: 0x%08X (%s) Port: %d", tagId,
           tags_[slot].name, portNumber);
  return true;
}

bool RFIDService::removeTag(uint32_t tagId) {
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].id == tagId) {
      tags_[i].isActive = false;
      tags_[i].recipe = TestRecipe(); // Clear recipe when tag is removed
      saveToFlash();
      LOG_INFO(LogCategory::RFID, "Tag silindi: 0x%08X", tagId);
      return true;
    }
  }
  LOG_WARN(LogCategory::RFID, "Tag bulunamadı: 0x%08X", tagId);
  return false;
}

bool RFIDService::isTagAuthorized(uint32_t tagId) {
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].id == tagId) {
      return true;
    }
  }
  return false;
}

bool RFIDService::isAdmin(uint32_t tagId) {
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].id == tagId) {
      return tags_[i].isAdmin;
    }
  }
  return false;
}

int RFIDService::getActiveTagCount() {
  int count = 0;
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive)
      count++;
  }
  return count;
}

void RFIDService::listTags() {
  Serial.println(
      "\n═══════════════════════════════════════════════════════════════");
  Serial.printf("  RFID Tag Veritabanı (%d/%d aktif)\n", getActiveTagCount(),
                maxTags_);
  Serial.println(
      "═══════════════════════════════════════════════════════════════");

  bool foundAny = false;
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive) {
      Serial.printf("  [%02d] 0x%08X  %s  %s  Port: %d/%d\n", i + 1, tags_[i].id,
                    tags_[i].isAdmin ? "ADMIN" : "USER ", tags_[i].name,
                    tags_[i].portNumber >> 8, tags_[i].portNumber & 0xFF);
      foundAny = true;
    }
  }

  if (!foundAny) {
    Serial.println("  (Hiç tag yok)");
  }

  Serial.println(
      "═══════════════════════════════════════════════════════════════\n");
}

uint32_t RFIDService::getLastDetectedTag() { return lastDetectedTag_; }

void RFIDService::clearAllTags() {
  for (int i = 0; i < maxTags_; i++) {
    tags_[i].isActive = false;
    tags_[i].recipe = TestRecipe(); // Clear recipe when tag is removed
  }
  saveToFlash();
  LOG_INFO(LogCategory::RFID, "Tüm taglar silindi");
}

bool RFIDService::assignPort(uint32_t tagId, uint16_t portNumber) {
  // Validate port number — encoded as (left<<8)|right, both 1-99
  uint8_t left = portNumber >> 8;
  uint8_t right = portNumber & 0xFF;
  if (portNumber == 0 || left > 99 || right > 99) {
    LOG_ERROR(LogCategory::RFID,
              "Geçersiz port numarası: %d (format: sol/sag, 1-99 arası)", portNumber);
    return false;
  }

  // Check if port already assigned to another tag
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].portNumber == portNumber &&
        tags_[i].id != tagId) {
      LOG_WARN(LogCategory::RFID, "Port %d zaten kullanımda (Tag 0x%08X)",
               portNumber, tags_[i].id);
      return false;
    }
  }

  // Find tag and assign port
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].id == tagId) {
      tags_[i].portNumber = portNumber;
      tags_[i].isNewRecord = true; // Mark as new for PC sync
      saveToFlash();
      LOG_INFO(LogCategory::RFID,
               "Port %d atandı -> Tag 0x%08X (isNewRecord=true)", portNumber,
               tagId);
      return true;
    }
  }

  LOG_WARN(LogCategory::RFID, "Tag bulunamadı: 0x%08X", tagId);
  return false;
}

uint16_t RFIDService::getTagPort(uint32_t tagId) {
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].id == tagId) {
      return tags_[i].portNumber;
    }
  }
  return 0; // Not found or not assigned
}

uint8_t RFIDService::getNextAvailablePort() {
  // Legacy: artık encode'lu port sistemi var, bu fonksiyon uyumluluk için kalıyor
  return 0; // Encode'lu sistemde otomatik atama yok
}

bool RFIDService::isPortAssigned(uint16_t portNumber) {
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].portNumber == portNumber) {
      return true;
    }
  }
  return false;
}

void RFIDService::announceCurrentTag() {
  if (lastDetectedTag_ != 0) {
    LOG_INFO(LogCategory::RFID, "Mevcut tag yeniden bildiriliyor: 0x%08X",
             lastDetectedTag_);
    onTagDetected(lastDetectedTag_);
  }
}

// ═══════════════════════════════════════════════════════════════════
// PRIVATE METHODS
// ═══════════════════════════════════════════════════════════════════

void RFIDService::onTagDetected(uint32_t tagId) {
  bool authorized = isTagAuthorized(tagId);
  bool admin = isAdmin(tagId);

  LOG_DEBUG(LogCategory::RFID, "Tag 0x%08X tespit edildi - %s", tagId,
            authorized ? (admin ? "Admin" : "Kullanıcı") : "Tanımsız");

  // Notify master via ESP-NOW
  if (espNowSlave && espNowSlave->isConnected()) {
    char buffer[256];
    uint8_t port = 0;

    // Find port number if authorized
    if (authorized) {
      for (int i = 0; i < maxTags_; i++) {
        if (tags_[i].isActive && tags_[i].id == tagId) {
          port = tags_[i].portNumber;
          break;
        }
      }
    }

    // Simple JSON message
    snprintf(buffer, sizeof(buffer),
             "{\"cmd\":\"RFID_DETECTED\",\"rfid\":\"0x%08X\",\"port\":%d,"
             "\"auth\":%s}",
             tagId, port, authorized ? "true" : "false");

    espNowSlave->sendToMaster(buffer);
    LOG_DEBUG(LogCategory::RFID, "Master'a bildirim gönderildi");
  }
}

// IDLE periyodik basınç değeri (main.cpp'de güncellenir, stream'de fallback olarak kullanılır)
// Global scope'da tanımlı — namespace GLT dışında erişmemiz gerekiyor
} // namespace GLT — geçici kapat
extern uint16_t idlePressureValue;
namespace GLT { // — tekrar aç

void RFIDService::sendFastStream(uint32_t tagId, char phase, int testElapsedSec) {
  // isConnected() kontrolü kaldırıldı — stream HER ZAMAN gönderilir.
  // Master reset olsa bile slave göndermeye devam eder, master geri gelince
  // onDataSent SUCCESS → connected_=true olur ve bağlantı otomatik yenilenir.
  if (!espNowSlave || !espNowSlave->isInitialized())
    return;
  uint16_t port = (tagId != 0) ? getTagPort(tagId) : 0;
  bool auth = (tagId != 0) ? isTagAuthorized(tagId) : false;
  TestRecipe r = (tagId != 0) ? getTagRecipe(tagId) : TestRecipe();
  uint16_t pressure = 0;
  int32_t rawPressure = 0;
  if (pressureService) {
    pressure = pressureService->getPressure();
    rawPressure = pressureService->getRawValue();
  }
  // IDLE modda sensör kapalı (getPressure=0) — periyodik IDLE okumasını kullan
  if (pressure == 0 && idlePressureValue > 0) {
    pressure = idlePressureValue;
  }
  int battery = BatteryService::getInstance().getPercentage();
  uint16_t flashCount = TestStorageService::getInstance().getTestCount();
  char packet[256];
  // 21 pipe-delimited fields: RFID|port|auth|p1|p2|p3|p4|p6|p7|p8|recipe|pressure|raw|ms|name|did|bat|phase|tes|flashCount|CRC
  // İlk 20 alan yazılır, sonra XOR checksum (21. alan) eklenir.
  int len = snprintf(packet, sizeof(packet),
           "@S:0x%08X|%d|%d|%d|%d|%d|%d|%d|%d|%d|%s|%d|%ld|%lu|%s|%s|%d|%c|%d|%d",
           tagId, port, auth ? 1 : 0,
           r.inflationMaxTime, r.inflationPascal, r.stabilizationTime,
           r.reinflateThreshold, r.failThreshold, r.testDuration,
           r.successDropPascal, r.recipeName,
           pressure, rawPressure, millis(),
           espNowSlave->getDeviceName(), espNowSlave->getDeviceId(),
           battery, phase, testElapsedSec, flashCount);
  // XOR checksum: "@S:" den sonraki tüm byte'ların XOR'u
  uint8_t crc = 0;
  for (int i = 3; i < len; i++) {  // skip "@S:" prefix (3 chars)
    crc ^= (uint8_t)packet[i];
  }
  snprintf(packet + len, sizeof(packet) - len, "|%02X", crc);
  espNowSlave->sendToMaster(packet);
}

void RFIDService::saveToFlash() {
  if (!autoSave_) return;  // Toplu ekleme sırasında atla
  File file = LittleFS.open("/rfid_db.bin", "w");
  if (!file) {
    LOG_ERROR(LogCategory::RFID, "Flash yazma hatası: Dosya açılamadı!");
    return;
  }

  size_t dataSize = sizeof(RFIDTag) * maxTags_;
  size_t written = file.write((uint8_t *)tags_, dataSize);
  file.close();

  if (written == dataSize) {
    LOG_INFO(LogCategory::RFID,
             "Flash Kaydedildi: %d tag veritabanına yazıldı (%d bytes)",
             getActiveTagCount(), dataSize);
  } else {
    LOG_ERROR(LogCategory::RFID, "Flash Yazma Hatası: Yazılan %d, Beklenen %d",
              written, dataSize);
  }
}

void RFIDService::loadFromFlash() {
  if (!LittleFS.exists("/rfid_db.bin")) {
    LOG_WARN(LogCategory::RFID, "Kayıtlı veritabanı bulunamadı. İlk açılış.");
    return;
  }

  File file = LittleFS.open("/rfid_db.bin", "r");
  if (!file) {
    LOG_ERROR(LogCategory::RFID, "Flash okuma hatası!");
    return;
  }

  size_t dataSize = sizeof(RFIDTag) * maxTags_;
  if (file.size() == dataSize) {
    file.read((uint8_t *)tags_, dataSize);
    LOG_INFO(LogCategory::RFID,
             "Flash Yükleme Tamamlandı: %d aktif tag dosyadan okundu",
             getActiveTagCount());
  } else {
    LOG_WARN(LogCategory::RFID,
             "Veritabanı boyutu uyuşmuyor. Dosya siliniyor.");
    file.close();
    LittleFS.remove("/rfid_db.bin");
  }
  file.close();
}

String RFIDService::getRFIDsJSON(bool onlyNew, int maxItems) {
  // Build JSON array of RFIDs
  String json = "[";
  bool first = true;
  int count = 0;

  for (int i = 0; i < maxTags_; i++) {
    if (count >= maxItems)
      break;

    if (tags_[i].isActive) {
      // Filter if onlyNew is requested
      if (onlyNew && !tags_[i].isNewRecord) {
        continue;
      }

      if (!first)
        json += ",";

      char item[256]; // Increased buffer for potential extra data
      // Note: Not sending recipe in discovery to save bandwidth
      snprintf(item, sizeof(item),
               "{\"rfid\":\"0x%08X\",\"port\":%d,\"name\":\"%s\",\"admin\":%s}",
               tags_[i].id, tags_[i].portNumber, tags_[i].name,
               tags_[i].isAdmin ? "true" : "false");
      json += item;
      first = false;
      count++;
    }
  }

  json += "]";
  return json;
}

void RFIDService::forceSyncAll() {
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive) {
      tags_[i].isNewRecord = true;
    }
  }
  saveToFlash();
  LOG_INFO(LogCategory::RFID, "Tum taglar icin sync talep edildi");
}

void RFIDService::clearNewFlag(uint32_t tagId) {
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].id == tagId) {
      tags_[i].isNewRecord = false;
      saveToFlash();
      LOG_DEBUG(LogCategory::RFID, "Tag 0x%08X 'new' flag cleared", tagId);
      return;
    }
  }
}

bool RFIDService::setTagRecipe(uint32_t tagId, const TestRecipe &recipe) {
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].id == tagId) {
      tags_[i].recipe = recipe;
      tags_[i].isNewRecord = true; // Mark as new for PC sync
      saveToFlash();               // Auto-save when recipe changes
      LOG_INFO(LogCategory::RFID, "Reçete kaydedildi: Tag 0x%08X", tagId);
      return true;
    }
  }
  return false;
}

TestRecipe RFIDService::getTagRecipe(uint32_t tagId) {
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive && tags_[i].id == tagId) {
      return tags_[i].recipe;
    }
  }
  return TestRecipe(); // Default
}

uint32_t RFIDService::calculateCRC() {
  uint32_t totalCRC = 0;
#ifdef ESP32
  for (int i = 0; i < maxTags_; i++) {
    if (tags_[i].isActive) {
      uint32_t tagCRC = 0;
      // Includes ID, Port, Recipe
      tagCRC = esp_rom_crc32_le(tagCRC, (uint8_t *)&tags_[i].id, 4);
      tagCRC = esp_rom_crc32_le(tagCRC, (uint8_t *)&tags_[i].portNumber, sizeof(tags_[i].portNumber));
      tagCRC = esp_rom_crc32_le(tagCRC, (uint8_t *)&tags_[i].recipe,
                                sizeof(TestRecipe));

      totalCRC ^= tagCRC; // XOR for order independence
    }
  }
#endif
  return totalCRC;
}

RFIDTag RFIDService::getTagByIndex(int index) {
  if (index >= 0 && index < maxTags_) {
    return tags_[index];
  }
  return RFIDTag(); // Return empty if out of bounds
}

} // namespace GLT
