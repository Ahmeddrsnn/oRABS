#include "services/ESPNowSlave.h"
#include "config.h"
#include "core/Logger.h"
#include <LittleFS.h>
#include "services/BatteryService.h"
#include "services/DwinService.h"
#include "services/PressureService.h"
#include "services/RFIDService.h"
#include "services/RtcService.h"
#include "services/TestParametersService.h"
#include "services/TestStorageService.h"
#include <ArduinoJson.h>
#include <esp_rom_crc.h>

// Global definition from main.cpp
extern GLT::PressureService *pressureService;
extern bool shouldTriggerMount;     // Defined in main.cpp
extern bool shouldTriggerTestStart; // Defined in main.cpp
extern bool shouldTriggerAbort;     // Defined in main.cpp
extern bool shouldTriggerDismount;  // Defined in main.cpp
extern volatile bool suppressRemoteLog;      // Defined in main.cpp

namespace GLT {

// Static instance for callbacks
ESPNowSlave *ESPNowSlave::instance_ = nullptr;
bool ESPNowSlave::showErrorLog_ = false;

ESPNowSlave::ESPNowSlave()
    : connected_(false), initialized_(false), masterRegistered_(false),
      lastSeen_(0), recvCallback_(nullptr), consecutiveFailCount_(0) {
  instance_ = this;
  memset(deviceName_, 0, sizeof(deviceName_));
  memcpy(masterMAC_, MASTER_MAC, 6);
}

// ── PIN Kalıcı Hafıza ────────────────────────────────────────────────────────

void ESPNowSlave::saveUserPinCrcToFlash() {
  File f = LittleFS.open("/user_pin_crc.bin", "w");
  if (!f) {
    LOG_WARN(LogCategory::CORE, "saveUserPinCrc: /user_pin_crc.bin açılamadı!");
    return;
  }
  f.write((uint8_t *)&userPinPayloadCrc_, sizeof(userPinPayloadCrc_));
  f.close();
  LOG_INFO(LogCategory::CORE, "User PIN CRC flash'a kaydedildi: 0x%08X", userPinPayloadCrc_);
}

void ESPNowSlave::loadUserPinCrcFromFlash() {
  if (!LittleFS.exists("/user_pin_crc.bin")) {
    LOG_INFO(LogCategory::CORE, "user_pin_crc.bin yok, PIN CRC=0 başlıyor");
    userPinPayloadCrc_ = 0;
    return;
  }
  File f = LittleFS.open("/user_pin_crc.bin", "r");
  if (!f) {
    LOG_WARN(LogCategory::CORE, "loadUserPinCrc: /user_pin_crc.bin açılamadı!");
    userPinPayloadCrc_ = 0;
    return;
  }
  if (f.size() != sizeof(userPinPayloadCrc_)) {
    LOG_WARN(LogCategory::CORE, "loadUserPinCrc: Dosya boyutu uyuşmuyor");
    f.close();
    userPinPayloadCrc_ = 0;
    return;
  }
  f.read((uint8_t *)&userPinPayloadCrc_, sizeof(userPinPayloadCrc_));
  f.close();
  LOG_INFO(LogCategory::CORE, "User PIN CRC flash'tan yüklendi: 0x%08X", userPinPayloadCrc_);
}

uint32_t ESPNowSlave::calculateUserPinCRC() {
  // PC ile aynı format: name|pin sıralı (alfabetik), \n ayrımlı
  // Basit bubble sort (max 100 entry, performans sorun değil)
  int indices[MAX_USER_PINS];
  for (int i = 0; i < userPinCount_; i++) indices[i] = i;
  for (int i = 0; i < userPinCount_ - 1; i++) {
    for (int j = 0; j < userPinCount_ - i - 1; j++) {
      if (strcmp(userPinList_[indices[j]].name, userPinList_[indices[j+1]].name) > 0) {
        int tmp = indices[j];
        indices[j] = indices[j+1];
        indices[j+1] = tmp;
      }
    }
  }
  // Payload oluştur ve CRC hesapla
  uint32_t crc = 0;
  for (int k = 0; k < userPinCount_; k++) {
    int idx = indices[k];
    char line[48]; // name(31) + '|' + pin(7) + '\n' + null
    int len = snprintf(line, sizeof(line), "%s|%s\n",
                       userPinList_[idx].name, userPinList_[idx].pin);
    if (len > 0) {
#ifdef ESP32
      crc = esp_rom_crc32_le(crc, (const uint8_t *)line, len);
#endif
    }
  }
  return crc;
}

void ESPNowSlave::saveCrcToFlash() {
  File f = LittleFS.open("/rfid_crc.bin", "w");
  if (!f) {
    LOG_WARN(LogCategory::CORE, "saveCrc: /rfid_crc.bin açılamadı!");
    return;
  }
  f.write((uint8_t *)&rfidPayloadCrc_, sizeof(rfidPayloadCrc_));
  f.close();
  LOG_INFO(LogCategory::CORE, "RFID CRC flash'a kaydedildi: 0x%08X", rfidPayloadCrc_);
}

void ESPNowSlave::loadCrcFromFlash() {
  if (!LittleFS.exists("/rfid_crc.bin")) {
    LOG_INFO(LogCategory::CORE, "rfid_crc.bin yok, CRC=0 başlıyor");
    rfidPayloadCrc_ = 0;
    return;
  }
  File f = LittleFS.open("/rfid_crc.bin", "r");
  if (!f) {
    LOG_WARN(LogCategory::CORE, "loadCrc: /rfid_crc.bin açılamadı!");
    rfidPayloadCrc_ = 0;
    return;
  }
  if (f.size() != sizeof(rfidPayloadCrc_)) {
    LOG_WARN(LogCategory::CORE, "loadCrc: Dosya boyutu uyuşmuyor (%d != %d)", (int)f.size(), (int)sizeof(rfidPayloadCrc_));
    f.close();
    rfidPayloadCrc_ = 0;
    return;
  }
  f.read((uint8_t *)&rfidPayloadCrc_, sizeof(rfidPayloadCrc_));
  f.close();
  LOG_INFO(LogCategory::CORE, "RFID CRC flash'tan yüklendi: 0x%08X", rfidPayloadCrc_);
}

void ESPNowSlave::savePinsToStorage() {
  File f = LittleFS.open("/user_pins.bin", "w");
  if (!f) {
    LOG_WARN(LogCategory::CORE, "savePins: /user_pins.bin açılamadı!");
    return;
  }
  f.write((uint8_t *)&userPinCount_, sizeof(userPinCount_));
  f.write((uint8_t *)userPinList_, sizeof(UserPinEntry) * userPinCount_);
  f.close();
  LOG_INFO(LogCategory::CORE, "PIN listesi kaydedildi (%d kullanıcı)", userPinCount_);
}

void ESPNowSlave::loadPinsFromStorage() {
  if (!LittleFS.exists("/user_pins.bin")) {
    LOG_INFO(LogCategory::CORE, "user_pins.bin yok, PIN listesi boş başlıyor");
    return;
  }
  File f = LittleFS.open("/user_pins.bin", "r");
  if (!f) {
    LOG_WARN(LogCategory::CORE, "loadPins: /user_pins.bin açılamadı!");
    return;
  }
  int count = 0;
  f.read((uint8_t *)&count, sizeof(count));
  if (count < 0 || count > MAX_USER_PINS) {
    LOG_WARN(LogCategory::CORE, "loadPins: Geçersiz kayıt sayısı: %d", count);
    f.close();
    return;
  }
  f.read((uint8_t *)userPinList_, sizeof(UserPinEntry) * count);
  userPinCount_ = count;
  f.close();
  LOG_INFO(LogCategory::CORE, "PIN listesi yüklendi (%d kullanıcı)", userPinCount_);
}

// ─────────────────────────────────────────────────────────────────────────────

void ESPNowSlave::generateDeviceId() {
  // Get 6-byte MAC address
  uint8_t mac[6];
  WiFi.macAddress(mac);

  // Base64url encode (RFC4648 §5): no padding, URL-safe alphabet
  static const char b64url[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

  // 6 bytes → 8 base64url characters (no padding needed, 6 is multiple of 3)
  char encoded[9]; // 8 chars + null
  encoded[0] = b64url[(mac[0] >> 2) & 0x3F];
  encoded[1] = b64url[((mac[0] & 0x03) << 4) | ((mac[1] >> 4) & 0x0F)];
  encoded[2] = b64url[((mac[1] & 0x0F) << 2) | ((mac[2] >> 6) & 0x03)];
  encoded[3] = b64url[mac[2] & 0x3F];
  encoded[4] = b64url[(mac[3] >> 2) & 0x3F];
  encoded[5] = b64url[((mac[3] & 0x03) << 4) | ((mac[4] >> 4) & 0x0F)];
  encoded[6] = b64url[((mac[4] & 0x0F) << 2) | ((mac[5] >> 6) & 0x03)];
  encoded[7] = b64url[mac[5] & 0x3F];
  encoded[8] = '\0';

  // Prefix with "LCC_" → total 12 chars
  snprintf(deviceId_, sizeof(deviceId_), "LCC_%s", encoded);
}

// ─────────────────────────────────────────────────────────────────────────────

bool ESPNowSlave::begin(const char *deviceName) {
  // Store device name
  strncpy(deviceName_, deviceName, sizeof(deviceName_) - 1);

  // Set WiFi mode to STA
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  // Generate unique device ID from MAC address
  generateDeviceId();

  // Disable WiFi debug spam
  esp_log_level_set("wifi", ESP_LOG_ERROR);

  // Kaydedilmiş PIN listesini yükle (bilgisayar bağlanmadan önce de çalışsın)
  loadPinsFromStorage();

  // Kaydedilmiş RFID payload CRC'sini yükle (gereksiz sync önlenir)
  loadCrcFromFlash();

  // Kaydedilmiş User PIN CRC'sini yükle (gereksiz PIN sync önlenir)
  loadUserPinCrcFromFlash();

  LOG_INFO(LogCategory::CORE, "ESP-NOW Slave başlatılıyor...");
  LOG_INFO(LogCategory::CORE, "MAC: %s", WiFi.macAddress().c_str());
  LOG_INFO(LogCategory::CORE, "Cihaz adı: %s", deviceName_);
  LOG_INFO(LogCategory::CORE, "Cihaz ID: %s", deviceId_);

  // Initialize ESP-NOW
  if (esp_now_init() != ESP_OK) {
    LOG_ERROR(LogCategory::CORE, "ESP-NOW init hatası!");
    return false;
  }

  // Register callbacks
  esp_now_register_recv_cb(onDataRecv);
  esp_now_register_send_cb(onDataSent);

  // Add hardcoded Master as peer (no HELLO discovery needed)
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, MASTER_MAC, 6);
  peerInfo.channel = 1;
  peerInfo.encrypt = false;

  if (!esp_now_is_peer_exist(MASTER_MAC)) {
    if (esp_now_add_peer(&peerInfo) != ESP_OK) {
      LOG_ERROR(LogCategory::CORE, "Master peer eklenemedi!");
      return false;
    }
  }

  masterRegistered_ = true;
  connected_ = true;
  lastSeen_ = millis();
  consecutiveFailCount_ = 0;

  LOG_INFO(LogCategory::CORE, "Master MAC: %02X:%02X:%02X:%02X:%02X:%02X",
           MASTER_MAC[0], MASTER_MAC[1], MASTER_MAC[2],
           MASTER_MAC[3], MASTER_MAC[4], MASTER_MAC[5]);

  initialized_ = true;

  // ═══ FreeRTOS ESP-NOW Thread: Kuyruk ve Task oluştur ═══
  sendQueue_ = xQueueCreate(SEND_QUEUE_SIZE, sizeof(EspNowSendItem));
  recvQueue_ = xQueueCreate(RECV_QUEUE_SIZE, sizeof(EspNowRecvItem));
  if (sendQueue_ && recvQueue_) {
    xTaskCreatePinnedToCore(taskEntry, "espnow", TASK_STACK_SIZE, this,
                            TASK_PRIORITY, &taskHandle_, TASK_CORE);
    LOG_INFO(LogCategory::CORE, "ESP-NOW FreeRTOS task başlatıldı (Core %d, Stack %d)", TASK_CORE, TASK_STACK_SIZE);
  } else {
    LOG_ERROR(LogCategory::CORE, "ESP-NOW kuyruk oluşturulamadı!");
    return false;
  }

  LOG_INFO(LogCategory::CORE, "ESP-NOW Slave hazır (Hardcode MAC + Thread)");
  return true;
}

// registerMaster() removed — hardcode MAC used in begin()

bool ESPNowSlave::sendToMaster(const char *data) {
  if (!masterRegistered_) {
    // Throttle warning message to once per 5 seconds to prevent spam
    static unsigned long lastMasterWarningTime = 0;
    unsigned long now = millis();

    if (now - lastMasterWarningTime > 5000) {
      lastMasterWarningTime = now;
      LOG_WARN(LogCategory::CORE, "Master kayıtlı değil, mesaj gönderilemedi");
    }
    return false;
  }

  if (!data || strlen(data) == 0) {
    return false;
  }

  size_t dataLen = strlen(data);

  // ESP-NOW max payload: 250 bytes — reject oversized messages
  if (dataLen > 250) {
    LOG_ERROR(
        LogCategory::CORE,
        "ESP-NOW BOYUT ASILDI! %d > 250 byte. Mesaj gönderilemedi: %.40s...",
        (int)dataLen, data);
    return false;
  }

  return queueSend(masterMAC_, data, (uint8_t)dataLen);
}

void ESPNowSlave::setRecvCallback(void (*callback)(const char *data)) {
  recvCallback_ = callback;
}

// ═══════════════════════════════════════════════════════════════════
// FreeRTOS ESP-NOW Thread
// ═══════════════════════════════════════════════════════════════════

bool ESPNowSlave::queueSend(const uint8_t* mac, const char* data, uint8_t len) {
  if (!sendQueue_) return false;
  if (len > 250) len = 250;  // ESP-NOW max payload guard
  EspNowSendItem item;
  memcpy(item.mac, mac, 6);
  memcpy(item.data, data, len);
  item.data[len] = '\0';
  item.len = len;
  if (xQueueSend(sendQueue_, &item, 0) != pdTRUE) {
    LOG_WARN(LogCategory::CORE, "ESP-NOW send kuyruğu dolu! (%d byte mesaj düşürüldü)", len);
    return false;
  }
  return true;
}

void ESPNowSlave::taskEntry(void* param) {
  ESPNowSlave* self = static_cast<ESPNowSlave*>(param);
  self->taskLoop();
}

void ESPNowSlave::taskLoop() {
  LOG_INFO(LogCategory::CORE, "ESP-NOW task çalışıyor (Core %d)", xPortGetCoreID());
  while (true) {
    // ── 1. Gelen mesajları işle (recv queue → handleMessage) ──
    EspNowRecvItem recvItem;
    while (xQueueReceive(recvQueue_, &recvItem, 0) == pdTRUE) {
      if (recvCallback_) {
        recvCallback_(recvItem.data);
      }
    }

    // ── 2. Durum makineleri (RFID sync + THP chunking) ──
    update();

    // ── 3. Gönderilecek mesajları gönder (send queue → esp_now_send) ──
    EspNowSendItem sendItem;
    while (xQueueReceive(sendQueue_, &sendItem, 0) == pdTRUE) {
      esp_now_send(sendItem.mac, (uint8_t*)sendItem.data, sendItem.len);
      // STABİLİTE FIX: Peş peşe gelen paketlerin (örn: THP Chunk'ları) 
      // ESP32 MAC katmanını (ESP_ERR_ESPNOW_NO_MEM) boğmasını engellemek için 2ms nefes aldır.
      vTaskDelay(pdMS_TO_TICKS(2));
    }

    // ── 4. Throttle (10ms = 100Hz tick) ──
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

void ESPNowSlave::triggerHistorySync() {
  if (syncActive_ || historySyncActive_) return;
  LOG_INFO(LogCategory::CORE, "Test bitti, PC'ye otomatik Flash aktarimi baslatiliyor...");
  historySyncActive_ = true;
  historyTestIndex_ = 0;
  historyChunkIndex_ = 0;
  historyTotalChunks_ = 0;
  historyPhase_ = 0;
  lastHistorySyncTime_ = 0;
  historyPayloadLen_ = 0;
  historyTestCount_ = TestStorageService::getInstance().getTestCount();
}

void ESPNowSlave::handleMessage(const char *data) {
  if (!data)
    return;

  // @S: fast stream verisi JSON değil, yoksay
  if (data[0] == '@')
    return;

  LOG_DEBUG(LogCategory::CORE, "ESP-NOW RAW: %s", data);

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, data);

  if (error) {
    LOG_ERROR(LogCategory::CORE, "JSON Hata: %s", error.c_str());
    LOG_ERROR(LogCategory::CORE, "Hatali Veri: %s", data);
    return;
  }

  // Debug: Gelen komutu logla
  LOG_INFO(LogCategory::CORE, "CMD_RAW: %s", data);

  const char *cmd = doc["cmd"] | "";

  if (strcmp(cmd, "SET_TAG_CONFIG") == 0) {
    // Suppress remote RFID logs during tag config to prevent ESP-NOW flooding
    suppressRemoteLog = true;
    const char *rfidStr = doc["rfid"] | "";
    uint32_t rfid = strtoul(rfidStr, nullptr, 16);
    uint16_t port = doc["port"] | 0;
    const char *recipeStr = doc["recipe"] | "";
    const char *recipeName = doc["recipe_name"] | "Varsayilan";

    if (rfid == 0 || !rfidService_) {
      LOG_WARN(LogCategory::CORE, "Geçersiz RFID veya Servis yok");
      suppressRemoteLog = false;
      return;
    }

    LOG_INFO(LogCategory::CORE, "Reçete alındı: 0x%08X, Port: %d, İsim: %s",
             rfid, port, recipeName);

    // Sil-yeniden-ekle stratejisi: aynı hex code ile duplikasyon önlenir,
    // port/isim/reçete her zaman güncel kalır.
    if (rfidService_->isTagAuthorized(rfid)) {
      LOG_INFO(LogCategory::RFID,
               "Mevcut tag siliniyor (güncelleme): 0x%08X", rfid);
      rfidService_->removeTag(rfid);
    }
    LOG_INFO(LogCategory::RFID,
             "Tag ekleniyor: 0x%08X Port:%d", rfid, port);
    rfidService_->addTag(rfid, false, recipeName, port);

    // Parse Recipe (Format: "t1-p1-t2-p2-p6-p7-p8" = 7 fields)
    LOG_INFO(LogCategory::CORE, ">>> RECIPE_RAW alindi: [%s]", recipeStr);
    LOG_INFO(LogCategory::CORE, ">>> RECIPE_NAME: [%s]", recipeName);
    LOG_INFO(LogCategory::CORE, ">>> RFID: 0x%08X | Port: %d", rfid, port);

    TestRecipe recipe;
    strncpy(recipe.recipeName, recipeName, sizeof(recipe.recipeName) - 1);

    int p[7] = {0, 0, 0, 0, 0, 0, 0};
    int parsedCount = sscanf(recipeStr, "%d-%d-%d-%d-%d-%d-%d", &p[0], &p[1],
                             &p[2], &p[3], &p[4], &p[5], &p[6]);

    LOG_INFO(LogCategory::CORE,
             ">>> PARSE SONUCU: %d alan okundu (7 bekleniyor)", parsedCount);
    LOG_INFO(LogCategory::CORE, ">>> p[0]=t1_inflation  : %d", p[0]);
    LOG_INFO(LogCategory::CORE, ">>> p[1]=p1_pressure   : %d", p[1]);
    LOG_INFO(LogCategory::CORE, ">>> p[2]=t2_stab       : %d", p[2]);
    LOG_INFO(LogCategory::CORE, ">>> p[3]=reinflThres   : %d", p[3]);
    LOG_INFO(LogCategory::CORE, ">>> p[4]=failThreshold : %d  (P6)", p[4]);
    LOG_INFO(LogCategory::CORE, ">>> p[5]=testDuration  : %d  (P7)", p[5]);
    LOG_INFO(LogCategory::CORE, ">>> p[6]=succDrop      : %d  (P8) <-- KRITIK",
             p[6]);

    if (parsedCount == 7) {
      recipe.inflationMaxTime = p[0];
      recipe.inflationPascal = p[1];
      recipe.stabilizationTime = p[2];
      recipe.reinflateThreshold = p[3];
      recipe.failThreshold = p[4];
      recipe.testDuration = p[5];
      recipe.successDropPascal = p[6];

      LOG_INFO(LogCategory::CORE,
               ">>> KAYDEDILEN: failThreshold=%d successDropPascal=%d",
               recipe.failThreshold, recipe.successDropPascal);

      rfidService_->setTagRecipe(rfid, recipe);
      LOG_INFO(LogCategory::CORE,
               ">>> setTagRecipe CAGRILDI -> flash'a yazildi");

      // Tag değişti — CRC yeniden hesapla ve PC'ye bildir
      uint32_t newCrc = rfidService_->calculateCRC();
      int newCount = rfidService_->getActiveTagCount();
      rfidPayloadCrc_ = 0;  // Payload CRC sıfırla (chunk sync CRC'si)
      saveCrcToFlash();

      // Re-announce the tag status to PC so the UI updates (hides 'Register'
      // button)
      rfidService_->announceCurrentTag();

      // ACK gönder — CRC bilgisiyle birlikte
      char ackBuf[128];
      snprintf(ackBuf, sizeof(ackBuf),
               "{\"cmd\":\"ACK_TAG_CONFIG\",\"rfid\":\"%s\",\"crc\":\"0x%08X\",\"count\":%d}",
               rfidStr, newCrc, newCount);
      sendToMaster(ackBuf);
    } else {
      LOG_ERROR(LogCategory::CORE,
                ">>> HATA: Reçete ayrıştırılamadı! Beklenen 7, gelen %d alan. "
                "Raw=[%s]",
                parsedCount, recipeStr);
    }
    suppressRemoteLog = false;
  } else if (strcmp(cmd, "GET_ALL_RFIDS") == 0) {
    if (!rfidService_)
      return;

    // Reject if another sync is holding the system
    if (historySyncActive_)
      return;

    LOG_INFO(LogCategory::NETWORK, "RFID listesi isteniyor (Non-Blocking)...");
    suppressRemoteLog = true;  // Prevent RFID log flooding during sync
    syncActive_ = true;
    syncIndex_ = 0;
    syncTotal_ = 0;
    lastSyncPacketTime_ = 0;
  } else if (strcmp(cmd, "RESET_RFIDS_SYNC") == 0) {
    if (rfidService_)
      rfidService_->forceSyncAll();
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"cmd\":\"ACK_RESET_SYNC\"}");
    sendToMaster(buf);
  } else if (strcmp(cmd, "SET_CALIB") == 0) {
    const char *type = doc["type"] | "";
    if (strcmp(type, "PRESSURE") == 0) {
      float offset = doc["offset"] | 0.0f;
      float mult = doc["mult"] | 1.0f;  // 1.0 = nötr (%100.0)

      Config::app.calibration.pressure_zero_offset = (int32_t)offset;
      Config::app.calibration.pressure_multiplier = mult;
      Config::saveToNVS();

      LOG_INFO(LogCategory::SENSOR,
               "Kalibrasyon (Basınç) Güncellendi: Off=%d, Mult=%.3f (%%%0.1f)",
               Config::app.calibration.pressure_zero_offset, mult, mult * 100.0f);
      sendToMaster("{\"cmd\":\"ACK_SET_CALIB\"}");
    } else if (strcmp(type, "SEAL") == 0) {
      float offset = doc["offset"] | 0.0f;
      float mult = doc["mult"] | 1.0f;

      Config::app.calibration.seal_offset = offset;
      Config::app.calibration.seal_multiplier = mult;
      Config::saveToNVS();

      LOG_INFO(LogCategory::SENSOR,
               "Kalibrasyon (Conta) Güncellendi: Off=%.1f, Mult=%.2f", offset,
               mult);
      sendToMaster("{\"cmd\":\"ACK_SET_CALIB\"}");
    }
  } else if (strcmp(cmd, "SET_CONTA") == 0) {
    float val = doc["val"] | 0.0f;
    Config::app.conta.max_pressure_mbar =
        val; // Mapping "Set" to max_pressure for now
    Config::saveToNVS();
    LOG_INFO(LogCategory::CORE, "Conta Basınç Ayarı: %.1f", val);
    sendToMaster("{\"cmd\":\"ACK_SET_CONTA\"}");
  } else if (strcmp(cmd, "SET_NAME") == 0) {
    const char *newName = doc["name"];
    if (newName && strlen(newName) > 0) {
      strncpy(Config::app.rfid.device_name, newName, 31);
      Config::app.rfid.device_name[31] = '\0';
      Config::saveToNVS();

      // Update local runtime name
      strncpy(deviceName_, newName, sizeof(deviceName_) - 1);

      LOG_INFO(LogCategory::CORE, "Cihaz Adı Değiştirildi: %s", newName);
      sendToMaster("{\"cmd\":\"ACK_SET_NAME\"}");
    }
  } else if (strcmp(cmd, "ZERO") == 0) {
    const char *type = doc["type"] | "";
    if (strcmp(type, "PRESSURE") == 0) {
      if (pressureService && pressureService->isConnected()) {
        // Raw değer artık offsetsiz (saf sensör verisi)
        int32_t raw = pressureService->getRawValue();

        // Offset = O anki Raw Değer
        // Böylece (Raw - Offset) = 0 olur
        Config::app.calibration.pressure_zero_offset = raw;
        Config::saveToNVS();

        LOG_INFO(LogCategory::SENSOR, "Sıfırlama Yapıldı. Yeni Offset: %d",
                 raw);

        // Cevap artık doğrudan tam sayı olarak gönderiliyor
        char buf[128];
        snprintf(buf, sizeof(buf), "{\"cmd\":\"ACK_ZERO\",\"new_offset\":%d}",
                 raw);
        sendToMaster(buf);
      } else {
        LOG_WARN(LogCategory::SENSOR, "Sıfırlama Hatası: Sensör bağlı değil");
        sendToMaster("{\"cmd\":\"NAK_ZERO\",\"msg\":\"SensorDisconnected\"}");
      }
    }
  } else if (strcmp(cmd, "DELETE_TAG") == 0) {
    // {"cmd":"DELETE_TAG", "rfid":"0x12345678"}
    const char *rfidStr = doc["rfid"];
    if (rfidStr && rfidService_) {
      uint32_t rfid = strtoul(rfidStr, NULL, 16);
      if (rfidService_->removeTag(rfid)) {
        rfidPayloadCrc_ = 0;  // Tag silindi — CRC geçersiz
        saveCrcToFlash();
        uint32_t newCrc = rfidService_->calculateCRC();
        int newCount = rfidService_->getActiveTagCount();
        LOG_INFO(LogCategory::CORE, "Tag Silindi: 0x%08X (yeni CRC=0x%08X, count=%d)", rfid, newCrc, newCount);
        char buffer[160];
        snprintf(buffer, sizeof(buffer),
                 "{\"cmd\":\"RFID_REMOVED\",\"rfid\":\"0x%08X\",\"crc\":\"0x%08X\",\"count\":%d}",
                 rfid, newCrc, newCount);
        sendToMaster(buffer);
      } else {
        LOG_WARN(LogCategory::CORE, "Tag Silinemedi (Bulunamadı): 0x%08X",
                 rfid);
      }
    }
  } else if (strcmp(cmd, "DELETE_ALL_TAGS") == 0) {
    // Tüm tagları sil — CRC all-or-nothing retry mekanizması için
    if (rfidService_) {
      rfidService_->clearAllTags();
      rfidPayloadCrc_ = 0;  // Tüm taglar silindi — CRC geçersiz
      saveCrcToFlash();
      uint32_t newCrc = rfidService_->calculateCRC();
      LOG_INFO(LogCategory::CORE, "Tüm taglar silindi (DELETE_ALL_TAGS, CRC=0x%08X)", newCrc);
      char delBuf[96];
      snprintf(delBuf, sizeof(delBuf),
               "{\"cmd\":\"ACK_DELETE_ALL\",\"crc\":\"0x%08X\",\"count\":0}", newCrc);
      sendToMaster(delBuf);
    }
  } else if (strcmp(cmd, "GET_CRC") == 0) {
    if (rfidService_) {
      int count = rfidService_->getActiveTagCount();
      char buf[96];
      snprintf(buf, sizeof(buf),
               "{\"cmd\":\"CRC_REPLY\",\"crc\":\"0x%08X\",\"count\":%d}",
               rfidPayloadCrc_, count);
      sendToMaster(buf);
    }
  } else if (strcmp(cmd, "VERIFY_CRC") == 0) {
    // PC beklenen CRC ve count gönderir, ESP32 kendi hesaplayıp karşılaştırır
    if (rfidService_) {
      const char *expectedCrcStr = doc["crc"] | "0";
      int expectedCount = doc["count"] | 0;
      uint32_t expectedCrc = strtoul(expectedCrcStr, nullptr, 16);
      uint32_t actualCrc = rfidService_->calculateCRC();
      int actualCount = rfidService_->getActiveTagCount();

      if (actualCrc == expectedCrc && actualCount == expectedCount) {
        LOG_INFO(LogCategory::CORE, "VERIFY_CRC: ESLESME OK (count=%d, CRC=0x%08X)", actualCount, actualCrc);
        char buf[64];
        snprintf(buf, sizeof(buf), "{\"cmd\":\"CRC_OK\",\"count\":%d}", actualCount);
        sendToMaster(buf);
      } else {
        LOG_WARN(LogCategory::CORE, "VERIFY_CRC: UYUSMAZLIK! Beklenen[%d,0x%08X] vs Gerçek[%d,0x%08X] -> TUM TAGLAR SILINIYOR",
                 expectedCount, expectedCrc, actualCount, actualCrc);
        rfidService_->clearAllTags();
        char buf[128];
        snprintf(buf, sizeof(buf),
                 "{\"cmd\":\"CRC_FAIL\",\"expected\":\"0x%08X\",\"actual\":\"0x%08X\",\"exp_count\":%d,\"act_count\":%d}",
                 expectedCrc, actualCrc, expectedCount, actualCount);
        sendToMaster(buf);
      }
    }
  } else if (strcmp(cmd, "RFID_SYNC_START") == 0) {
    // Chunked RFID sync başlangıcı — buffer sıfırla, metadata kaydet
    rfidSyncExpectedCount_ = doc["n"] | 0;
    rfidSyncExpectedSize_ = doc["sz"] | 0;
    rfidSyncExpectedChunks_ = doc["cn"] | 0;
    const char *crcStr = doc["crc"] | "0";
    rfidSyncExpectedCrc_ = strtoul(crcStr, nullptr, 16);
    rfidSyncBufLen_ = 0;
    rfidSyncReceivedChunks_ = 0;
    rfidSyncActive_ = true;
    lastRfidSyncChunkTime_ = millis();
    memset(rfidSyncBuf_, 0, sizeof(rfidSyncBuf_));
    LOG_INFO(LogCategory::CORE, "RFID_SYNC_START: %d port, %d chunk, CRC=0x%08X",
             rfidSyncExpectedCount_, rfidSyncExpectedChunks_, rfidSyncExpectedCrc_);
    sendToMaster("{\"cmd\":\"ACK_SYNC_START\"}");

  } else if (strcmp(cmd, "RSC") == 0) {
    // RFID Sync Chunk
    if (!rfidSyncActive_) {
      LOG_WARN(LogCategory::CORE, "RSC geldi ama sync aktif değil, atlanıyor");
      return;
    }
    int chunkIdx = doc["i"] | -1;
    const char *chunkData = doc["d"] | "";
    int chunkLen = strlen(chunkData);

    if (chunkIdx != (int)rfidSyncReceivedChunks_) {
      LOG_WARN(LogCategory::CORE, "RSC sıra hatası: beklenen=%d, gelen=%d",
               rfidSyncReceivedChunks_, chunkIdx);
    }

    // Buffer taşma kontrolü
    if (rfidSyncBufLen_ + chunkLen >= sizeof(rfidSyncBuf_) - 1) {
      LOG_ERROR(LogCategory::CORE, "RFID sync buffer taşması! %d + %d > %d",
                rfidSyncBufLen_, chunkLen, (int)sizeof(rfidSyncBuf_));
      rfidSyncActive_ = false;
      sendToMaster("{\"cmd\":\"SYNC_FAIL\",\"reason\":\"buffer_overflow\"}");
      return;
    }

    memcpy(rfidSyncBuf_ + rfidSyncBufLen_, chunkData, chunkLen);
    rfidSyncBufLen_ += chunkLen;
    rfidSyncReceivedChunks_++;
    lastRfidSyncChunkTime_ = millis();

    // Son chunk mı?
    if (rfidSyncReceivedChunks_ >= rfidSyncExpectedChunks_) {
      rfidSyncBuf_[rfidSyncBufLen_] = '\0';
      rfidSyncActive_ = false;

      // CRC doğrula (payload üzerinden)
      uint32_t actualCrc = 0;
#ifdef ESP32
      actualCrc = esp_rom_crc32_le(0, (const uint8_t *)rfidSyncBuf_, rfidSyncBufLen_);
#endif

      if (actualCrc != rfidSyncExpectedCrc_) {
        LOG_ERROR(LogCategory::CORE, "RFID sync CRC FAIL: beklenen=0x%08X, hesaplanan=0x%08X",
                  rfidSyncExpectedCrc_, actualCrc);
        char failBuf[128];
        snprintf(failBuf, sizeof(failBuf),
                 "{\"cmd\":\"SYNC_FAIL\",\"reason\":\"crc_mismatch\",\"expected\":\"0x%08X\",\"actual\":\"0x%08X\"}",
                 rfidSyncExpectedCrc_, actualCrc);
        sendToMaster(failBuf);
        return;
      }

      LOG_INFO(LogCategory::CORE, "RFID sync CRC OK (0x%08X). Parse ediliyor...", actualCrc);

      // Log spam'inin send queue'yu taşırmasını engelle
      suppressRemoteLog = true;

      // Önce tüm eski tagları temizle (all-or-nothing)
      if (rfidService_) {
        rfidService_->setAutoSave(true);  // clearAllTags flash'a yazmasını sağla
        rfidService_->clearAllTags();
        rfidService_->setAutoSave(false); // Toplu ekleme sırasında flash kaydı devre dışı
      }

      // Parse: her satır = rfid|port|recipe_str|recipe_name
      int parsed = 0;
      int addOk = 0;
      char *lineStart = rfidSyncBuf_;
      while (lineStart && *lineStart && rfidService_) {
        char *lineEnd = strchr(lineStart, '\n');
        if (lineEnd) *lineEnd = '\0';

        // rfid|port|t1-p1-t2-p2-p3-t3-p8|recipe_name
        char rfidStr[16] = {0};
        int port = 0;
        char recipeStr[64] = {0};
        char recipeName[16] = {0};

        // Parse pipe-delimited fields
        char *field1 = lineStart;
        char *sep1 = strchr(field1, '|');
        if (!sep1) { lineStart = lineEnd ? lineEnd + 1 : nullptr; continue; }
        *sep1 = '\0';
        strncpy(rfidStr, field1, sizeof(rfidStr) - 1);

        char *field2 = sep1 + 1;
        char *sep2 = strchr(field2, '|');
        if (!sep2) { lineStart = lineEnd ? lineEnd + 1 : nullptr; continue; }
        *sep2 = '\0';
        port = atoi(field2);

        char *field3 = sep2 + 1;
        char *sep3 = strchr(field3, '|');
        if (!sep3) { lineStart = lineEnd ? lineEnd + 1 : nullptr; continue; }
        *sep3 = '\0';
        strncpy(recipeStr, field3, sizeof(recipeStr) - 1);

        char *field4 = sep3 + 1;
        strncpy(recipeName, field4, sizeof(recipeName) - 1);

        uint32_t rfid = strtoul(rfidStr, nullptr, 16);
        if (rfid == 0 || port == 0) {
          lineStart = lineEnd ? lineEnd + 1 : nullptr;
          continue;
        }

        // addTag (flash'a kaydetmeden — saveToFlash'ı en son çağıracağız)
        if (rfidService_->addTag(rfid, false, recipeName, port)) {
          addOk++;
        } else {
          LOG_WARN(LogCategory::CORE, "addTag FAIL: rfid=0x%08X port=%d", rfid, port);
        }

        // Parse recipe
        TestRecipe recipe;
        strncpy(recipe.recipeName, recipeName, sizeof(recipe.recipeName) - 1);
        int p[7] = {0};
        sscanf(recipeStr, "%d-%d-%d-%d-%d-%d-%d", &p[0], &p[1], &p[2], &p[3], &p[4], &p[5], &p[6]);
        recipe.inflationMaxTime = p[0];
        recipe.inflationPascal = p[1];
        recipe.stabilizationTime = p[2];
        recipe.reinflateThreshold = p[3];
        recipe.failThreshold = p[4];
        recipe.testDuration = p[5];
        recipe.successDropPascal = p[6];

        rfidService_->setTagRecipe(rfid, recipe);
        parsed++;

        lineStart = lineEnd ? lineEnd + 1 : nullptr;
      }

      LOG_INFO(LogCategory::CORE, "RFID sync tamamlandı: parsed=%d, addOk=%d", parsed, addOk);

      // Toplu ekleme bitti — tek seferde flash'a kaydet
      rfidService_->setAutoSave(true);
      rfidService_->forceSave();

      // CRC match kontrolü (yeni eklenen taglar ile ESP32 CRC hesapla)
      uint32_t verifyCrc = rfidService_ ? rfidService_->calculateCRC() : 0;
      int verifyCount = rfidService_ ? rfidService_->getActiveTagCount() : 0;
      int maxT = rfidService_ ? rfidService_->getMaxTags() : 0;

      // Başarılı sync — payload CRC'yi sakla (flash'a da yaz)
      rfidPayloadCrc_ = rfidSyncExpectedCrc_;
      saveCrcToFlash();

      char okBuf[160];
      snprintf(okBuf, sizeof(okBuf),
               "{\"cmd\":\"SYNC_OK\",\"count\":%d,\"parsed\":%d,\"ok\":%d,\"max\":%d,\"crc\":\"0x%08X\"}",
               verifyCount, parsed, addOk, maxT, verifyCrc);
      sendToMaster(okBuf);
      suppressRemoteLog = false;  // Remote log'u tekrar aç
    }
  } else if (strcmp(cmd, "STREAM") == 0) {
    if (pressureService) {
      bool state = !pressureService->isContinuous();
      pressureService->setContinuous(state);
      if (state)
        LOG_INFO(LogCategory::SENSOR, "Yayın Başlatıldı");
      else
        LOG_INFO(LogCategory::SENSOR, "Yayın Durduruldu");
    }
  } else if (strcmp(cmd, "SET_TIME") == 0) {
    // {"cmd":"SET_TIME", "datetime":"2026-02-19 08:30:00"}
    const char *datetimeStr = doc["datetime"] | "";

    // Log incoming time string
    LOG_INFO(LogCategory::CORE, "Zaman Güncelleme İsteği: %s", datetimeStr);

    if (strlen(datetimeStr) > 0) {
      int year, month, day, hour, minute, second;

      // Strict parsing
      if (sscanf(datetimeStr, "%d-%d-%d %d:%d:%d", &year, &month, &day, &hour,
                 &minute, &second) == 6) {

        // Update RTC
        RtcService::getInstance().setTime(year, month, day, hour, minute,
                                          second);

        // Log success
        LOG_INFO(LogCategory::CORE,
                 "Saat Başarıyla Ayarlandı: %04d-%02d-%02d %02d:%02d:%02d",
                 year, month, day, hour, minute, second);

        // Send ACK
        sendToMaster("{\"cmd\":\"ACK_SET_TIME\"}");
      } else {
        LOG_WARN(LogCategory::CORE,
                 "Saat formatı geçersiz! (Beklenen: YYYY-MM-DD HH:MM:SS)");
      }
    } else {
      LOG_WARN(LogCategory::CORE, "Saat bilgisi boş geldi!");
    }
  } else if (strcmp(cmd, "GET_CALIB") == 0) {
    char buf[256];
    snprintf(buf, sizeof(buf),
             "{\"cmd\":\"CALIB_DATA\",\"p_off\":%d,\"p_mul\":%.0f,\"s_off\":%"
             ".2f,\"s_mul\":%.2f,\"c_set\":%.1f}",
             Config::app.calibration.pressure_zero_offset,
             Config::app.calibration.pressure_multiplier,
             Config::app.calibration.seal_offset,
             Config::app.calibration.seal_multiplier,
             Config::app.conta.max_pressure_mbar);
    sendToMaster(buf);
  } else if (strcmp(cmd, "TEST_SEAL") == 0) {
    LOG_INFO(LogCategory::CORE,
             "Donanim Testi: Conta (Seal) test komutu alindi.");
    // Optional: Toggle Seal Solenoid if safe
    // digitalWrite(Config::hardware.relays.conta_solenoid,
    // !digitalRead(Config::hardware.relays.conta_solenoid));
    sendToMaster("{\"cmd\":\"ACK_TEST_SEAL\"}");
  } else if (strcmp(cmd, "TEST_GLOVE") == 0) {
    LOG_INFO(LogCategory::CORE,
             "Donanim Testi: Eldiven (Glove) test komutu alindi.");
    // Optional: Toggle Glove Solenoid
    // digitalWrite(Config::hardware.relays.glove_solenoid,
    // !digitalRead(Config::hardware.relays.glove_solenoid));
    sendToMaster("{\"cmd\":\"ACK_TEST_GLOVE\"}");
  } else if (strcmp(cmd, "TEST_RFID") == 0) {
    LOG_INFO(LogCategory::CORE, "Donanim Testi: RFID test komutu alindi.");
    if (rfidService_) {
      rfidService_->announceCurrentTag(); // Re-read and announce
    }
    sendToMaster("{\"cmd\":\"ACK_TEST_RFID\"}");
  } else if (strcmp(cmd, "MOUNT") == 0) {
    LOG_INFO(LogCategory::CORE, "Komut: MOUNT");
    shouldTriggerMount = true;
    sendToMaster("{\"cmd\":\"ACK_MOUNT\"}");
  } else if (strcmp(cmd, "START_TEST") == 0) {
    LOG_INFO(LogCategory::CORE, "Komut: START_TEST");
    shouldTriggerTestStart = true;
    sendToMaster("{\"cmd\":\"ACK_START_TEST\"}");
  } else if (strcmp(cmd, "ABORT") == 0) {
    LOG_INFO(LogCategory::CORE, "Komut: ABORT");
    shouldTriggerAbort = true;
    sendToMaster("{\"cmd\":\"ACK_ABORT\"}");
  } else if (strcmp(cmd, "DISMOUNT") == 0) {
    // FIX: shouldTriggerDismount flag kullan — VP write thread-safe değil
    // (ESP-NOW Core 0, main loop Core 1 aynı anda DwinService'e erişiyordu)
    shouldTriggerDismount = true;
    sendToMaster("{\"cmd\":\"ACK_DISMOUNT\"}");
    LOG_INFO(LogCategory::CORE,
             "PC'den DISMOUNT komutu alindi, flag tetiklendi.");
  } else if (strcmp(cmd, "GET_STATUS") == 0) {
    // Respond to immediate status request
    int battery = BatteryService::getInstance().getPercentage();
    // We can't easily access main.cpp variables here without extern,
    // but Heartbeat handles the detailed state.
    // Let's just return basic info available here or add extern if needed.
    // For now, Battery is the most important dynamic value.

    StaticJsonDocument<256> doc;
    doc["cmd"] = "STATUS_REPLY";
    doc["device"] = deviceName_;
    doc["did"] = deviceId_;
    doc["battery"] = battery;
    // You could add RSSI etc if needed

    String jsonStr;
    serializeJson(doc, jsonStr);
    sendToMaster(jsonStr.c_str());
  } else if (strcmp(cmd, "CLEAR_USER_PINS") == 0) {
    userPinCount_ = 0;
    memset(userPinList_, 0, sizeof(userPinList_));
    savePinsToStorage(); // Kalıcı hafızadan da sil
    userPinPayloadCrc_ = 0;
    saveUserPinCrcToFlash();
    LOG_INFO(LogCategory::CORE,
             "CLEAR_USER_PINS: Kullanici listesi temizlendi");
    sendToMaster("{\"cmd\":\"ACK_CLEAR_PINS\"}");
  } else if (strcmp(cmd, "ADD_USER_PINS") == 0) {
    // {"cmd":"ADD_USER_PINS","users":[{"name":"ali","pin":"1234"},...]})
    JsonArray users = doc["users"].as<JsonArray>();
    if (!users.isNull()) {
      for (JsonObject u : users) {
        if (userPinCount_ >= MAX_USER_PINS)
          break;
        const char *uname = u["name"] | "";
        const char *upin = u["pin"] | "";
        if (strlen(uname) > 0 && strlen(upin) > 0) {
          strncpy(userPinList_[userPinCount_].name, uname, 31);
          userPinList_[userPinCount_].name[31] = '\0';
          strncpy(userPinList_[userPinCount_].pin, upin, 7);
          userPinList_[userPinCount_].pin[7] = '\0';
          userPinCount_++;
        }
      }
      savePinsToStorage(); // Kalıcı hafızaya kaydet
      userPinPayloadCrc_ = calculateUserPinCRC();
      saveUserPinCrcToFlash();
      LOG_INFO(LogCategory::CORE, "ADD_USER_PINS: %d kullanici oldu (CRC=0x%08X)",
               userPinCount_, userPinPayloadCrc_);
      sendToMaster("{\"cmd\":\"ACK_ADD_USER_PINS\"}");
    } else {
      LOG_WARN(LogCategory::CORE, "ADD_USER_PINS: users dizisi bulunamadi");
    }
  } else if (strcmp(cmd, "GET_PIN_CRC") == 0) {
    char buf[96];
    snprintf(buf, sizeof(buf),
             "{\"cmd\":\"PIN_CRC_REPLY\",\"crc\":\"0x%08X\",\"count\":%d}",
             userPinPayloadCrc_, userPinCount_);
    sendToMaster(buf);
  } else if (strcmp(cmd, "GET_TEST_HISTORY") == 0) {
    // Non-blocking activation
    if (syncActive_ || historySyncActive_) {
      // Busy
      sendToMaster("{\"cmd\":\"NAK_TEST_HISTORY\",\"msg\":\"Busy\"}");
      return;
    }

    LOG_INFO(LogCategory::CORE, "GET_TEST_HISTORY: Çevrimdışı senkronizasyon "
                                "başlatılıyor (Non-blocking)...");

    // DYNAMIC THP CHUNKING STATE MACHINE
    historySyncActive_ = true;
    historyTestIndex_ = 0;
    historyChunkIndex_ = 0;
    historyTotalChunks_ = 0;
    historyPhase_ = 0; // 0=Info, 1=BuildPayload, 2=SendChunks
    lastHistorySyncTime_ = 0;
    historyPayloadLen_ = 0;

    // storage testCount'u bir kere al ve kaydet
    historyTestCount_ = TestStorageService::getInstance().getTestCount();

  } else if (strcmp(cmd, "CLEAR_TEST_HISTORY") == 0) {
    // PC testleri aldı, Flash temizlenebilir
    TestStorageService &storage = TestStorageService::getInstance();
    if (storage.clearAll()) {
      LOG_INFO(LogCategory::CORE, "CLEAR_TEST_HISTORY: Tüm testler silindi");
      sendToMaster("{\"cmd\":\"ACK_CLEAR_TEST_HISTORY\",\"success\":true}");
    } else {
      LOG_ERROR(LogCategory::CORE, "CLEAR_TEST_HISTORY: Silme hatası!");
      sendToMaster("{\"cmd\":\"ACK_CLEAR_TEST_HISTORY\",\"success\":false}");
    }

  } else if (strcmp(cmd, "GET_STORAGE_INFO") == 0) {
    // Storage durumu sorgula
    char infoBuf[200];
    TestStorageService::getInstance().getStorageInfoJson(infoBuf, sizeof(infoBuf));
    sendToMaster(infoBuf);
  }
}

void ESPNowSlave::update() {
  // Connection management is handled by onDataSent callback:
  // - 10 consecutive SEND_FAIL → connected_ = false
  // - Any SEND_SUCCESS → connected_ = true, consecutiveFailCount_ = 0
  // No HELLO, HEARTBEAT, or PING needed — stream runs at 200ms via esp_timer
  
  unsigned long now = millis();

  // ── Chunked RFID Sync Timeout ───────────────────────────────────
  if (rfidSyncActive_ && (now - lastRfidSyncChunkTime_ > 3000)) {
    LOG_WARN(LogCategory::CORE, "RFID sync chunk timeout: %d/%d chunk al\u0131nd\u0131",
             rfidSyncReceivedChunks_, rfidSyncExpectedChunks_);
    rfidSyncActive_ = false;
    char buf[128];
    snprintf(buf, sizeof(buf),
             "{\"cmd\":\"SYNC_FAIL\",\"reason\":\"chunk_timeout\",\"received\":%d,\"expected\":%d}",
             rfidSyncReceivedChunks_, rfidSyncExpectedChunks_);
    sendToMaster(buf);
  }

  // Non-Blocking Sync Logic
  if (syncActive_) {
    if (now - lastSyncPacketTime_ > 50) { // 50ms throttle
      if (rfidService_) {
        int maxTags = Config::app.rfid.max_tags;

        // Find next active tag starting from syncIndex_
        bool sent = false;
        while (syncIndex_ < maxTags) {
          RFIDTag tag = rfidService_->getTagByIndex(syncIndex_);
          syncIndex_++; // Move to next for next call

          if (tag.isActive) {
            char buffer[251]; // ESP-NOW max 250 + null
            TestRecipe r = tag.recipe;
            char recipeStr[64];
            snprintf(recipeStr, sizeof(recipeStr), "%d-%d-%d-%d-%d-%d-%d",
                     r.inflationMaxTime, r.inflationPascal, r.stabilizationTime,
                     r.reinflateThreshold, r.failThreshold, r.testDuration,
                     r.successDropPascal);

            snprintf(
                buffer, sizeof(buffer),
                "{\"cmd\":\"RFID_ITEM\",\"rfid\":\"0x%08X\",\"port\":%d,"
                "\"name\":\"%.15s\",\"recipe\":\"%s\",\"recipe_name\":\"%.15s\"}",
                tag.id, tag.portNumber, tag.name, recipeStr, r.recipeName);

            sendToMaster(buffer);
            syncTotal_++;
            lastSyncPacketTime_ = now;
            sent = true;
            break; // Send one only per time slot
          }
        }

        // Check if we reached the end
        if (!sent && syncIndex_ >= maxTags) {
          // Done
          char endMsg[64];
          snprintf(endMsg, sizeof(endMsg),
                   "{\"cmd\":\"SYNC_COMPLETE\",\"count\":%d}", syncTotal_);
          sendToMaster(endMsg);
          syncActive_ = false;
          suppressRemoteLog = false;  // Re-enable remote logging
          LOG_INFO(LogCategory::NETWORK, "Sync tamamlandı (Toplam: %d)",
                   syncTotal_);
        }
      } else {
        syncActive_ = false; // Abort if service missing
        suppressRemoteLog = false;
      }
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  // DYNAMIC THP CHUNKING — Tek Payload Mimarisi
  // Metadata + basınç verisi pipe-delimited string'e birleştirilir,
  // 180-byte chunk'lara bölünür ve sadece "THP" komutuyla gönderilir.
  // Payload format: tid|rfid|port|op|rc|rn|dur|sp|ep|td|wd|sc|ts|r|chk|p1,p2,...
  // Phase 0: Storage info gönder
  // Phase 1: Flash'tan test oku → payload string oluştur → chunk hesapla
  // Phase 2: Chunk'ları birer birer 50ms aralıkla gönder
  // ═══════════════════════════════════════════════════════════════════
  if (historySyncActive_) {
    if (now - lastHistorySyncTime_ > 50) { // 50ms throttle — Watchdog-safe
      TestStorageService &storage = TestStorageService::getInstance();

      if (historyTestCount_ == 0) {
        sendToMaster("{\"cmd\":\"TEST_HISTORY_DONE\"}");
        historySyncActive_ = false;
        historyPayloadLen_ = 0;
        return;
      }

      // ── Phase 0: Storage Info ────────────────────────────────────
      if (historyPhase_ == 0) {
        char infoBuf[200];
        storage.getStorageInfoJson(infoBuf, sizeof(infoBuf));
        sendToMaster(infoBuf);
        historyPhase_ = 1;
        lastHistorySyncTime_ = now;

      // ── Phase 1: Build Payload ───────────────────────────────────
      } else if (historyPhase_ == 1) {
        if (historyTestIndex_ >= historyTestCount_) {
          // Tüm testler gönderildi
          sendToMaster("{\"cmd\":\"TEST_HISTORY_DONE\"}");
          historySyncActive_ = false;
          historyPayloadLen_ = 0;
          return;
        }

        TestRecordHeader hdr;
        if (storage.readTest(historyTestIndex_, hdr, historySampleBuf_, 600)) {
          // ── Operator adı (pipe-safe, max 16 char) ──
          char opShort[17];
          memset(opShort, 0, sizeof(opShort));
          strncpy(opShort, hdr.operatorName, 16);
          for (int k = 0; k < 16 && opShort[k]; k++) {
            if (opShort[k] == '|' || opShort[k] == '"') opShort[k] = '_';
          }

          // ── Reçete adı (pipe-safe) ──
          char rnSafe[17];
          memset(rnSafe, 0, sizeof(rnSafe));
          strncpy(rnSafe, hdr.recipeName, 16);
          for (int k = 0; k < 16 && rnSafe[k]; k++) {
            if (rnSafe[k] == '|' || rnSafe[k] == '"') rnSafe[k] = '_';
          }

          // ── Compact recipe: p1-p2-p3-p4-p6-p7-p8 ──
          char rcBuf[48];
          snprintf(rcBuf, sizeof(rcBuf), "%d-%d-%d-%d-%d-%d-%d",
                   hdr.inflationMaxTime,    // p1
                   hdr.targetPressure,       // p2
                   hdr.stabilizationTime,    // p3
                   hdr.reinflateThreshold,   // p4 (v2 field — artık gerçek değer!)
                   hdr.acceptableDrop,       // p6
                   hdr.windowSize,           // p7
                   hdr.criticalDrop);        // p8

          // ── Timestamp ──
          char timeStr[24];
          snprintf(timeStr, sizeof(timeStr), "20%02d-%02d-%02dT%02d:%02d:%02d",
                   hdr.startYear, hdr.startMonth, hdr.startDay,
                   hdr.startHour, hdr.startMinute, hdr.startSecond);

          // ── Meta Checksum (eski formülle uyumlu) ──
          uint32_t metaChk = hdr.testId + hdr.rfidTag + hdr.portNumber +
                             hdr.startPressure + hdr.endPressure +
                             hdr.durationSec + hdr.totalDrop + hdr.windowDrop +
                             hdr.sampleCount;

          // ── Meta section (pipe-delimited, 15 field) ──
          // [0]tid|[1]rfid|[2]port|[3]op|[4]rc|[5]rn|[6]dur|[7]sp|[8]ep
          // |[9]td|[10]wd|[11]sc|[12]ts|[13]r|[14]chk
          char metaBuf[220];
          snprintf(metaBuf, sizeof(metaBuf),
                   "%u|%X|%d|%s|%s|%s|%d|%d|%d|%d|%d|%d|%s|%s|%u",
                   hdr.testId,                        // [0]  tid
                   hdr.rfidTag,                       // [1]  rfid (hex)
                   hdr.portNumber,                    // [2]  port
                   opShort,                           // [3]  operator
                   rcBuf,                             // [4]  rc (p1-p2-p3-p4-p6-p7-p8)
                   rnSafe,                            // [5]  recipe name
                   hdr.durationSec,                   // [6]  duration
                   hdr.startPressure,                 // [7]  start pressure
                   hdr.endPressure,                   // [8]  end pressure
                   hdr.totalDrop,                     // [9]  total drop
                   hdr.windowDrop,                    // [10] window drop
                   hdr.sampleCount,                   // [11] sample count
                   timeStr,                           // [12] timestamp
                   hdr.passed ? "PASS" : "FAIL",      // [13] result
                   metaChk);                          // [14] checksum

          // ── Build full payload: meta + "|" + pressure CSV ──
          uint16_t sc = hdr.sampleCount < 600 ? hdr.sampleCount : 600;
          int pos = snprintf(historyPayloadBuf_, sizeof(historyPayloadBuf_), "%s|", metaBuf);

          // Pressure CSV (int16 values, comma-separated)
          char numBuf[8];
          for (uint16_t s = 0; s < sc && pos < (int)sizeof(historyPayloadBuf_) - 8; s++) {
            if (s > 0) historyPayloadBuf_[pos++] = ',';
            pos += snprintf(historyPayloadBuf_ + pos, sizeof(historyPayloadBuf_) - pos, "%d", historySampleBuf_[s]);
          }
          historyPayloadLen_ = (uint16_t)pos;

          // ── Calculate chunks ──
          static const uint16_t MAX_CHUNK_DATA = 180;
          historyTotalChunks_ = (historyPayloadLen_ + MAX_CHUNK_DATA - 1) / MAX_CHUNK_DATA;
          if (historyTotalChunks_ == 0) historyTotalChunks_ = 1;
          historyChunkIndex_ = 0;
          historyPhase_ = 2;

          LOG_INFO(LogCategory::CORE, "THP payload: test %d/%d, %d bytes, %d chunks",
                   historyTestIndex_ + 1, historyTestCount_,
                   historyPayloadLen_, historyTotalChunks_);

          lastHistorySyncTime_ = now;
        } else {
          // Flash okuma hatası — bu testi atla
          LOG_WARN(LogCategory::CORE, "THP: test %d okunamadı, atlaniyor", historyTestIndex_);
          historyTestIndex_++;
          lastHistorySyncTime_ = now;
        }

      // ── Phase 2: Send Chunks ─────────────────────────────────────
      } else if (historyPhase_ == 2) {
        if (historyChunkIndex_ < historyTotalChunks_) {
          static const uint16_t MAX_CHUNK_DATA = 180;
          uint16_t startPos = (uint16_t)(historyChunkIndex_ * MAX_CHUNK_DATA);
          uint16_t endPos = startPos + MAX_CHUNK_DATA;
          if (endPos > historyPayloadLen_) endPos = historyPayloadLen_;

          // Chunk verisini buffer'dan kopyala (heap alloc yok)
          uint16_t chunkLen = endPos - startPos;
          char chunkBuf[MAX_CHUNK_DATA + 1];
          memcpy(chunkBuf, historyPayloadBuf_ + startPos, chunkLen);
          chunkBuf[chunkLen] = '\0';

          // JSON frame — snprintf ile oluştur (ArduinoJson heap alloc yerine)
          char frameBuf[384];
          int frameLen = snprintf(frameBuf, sizeof(frameBuf),
              "{\"cmd\":\"THP\",\"i\":%d,\"n\":%d,\"c\":%d,\"ct\":%d,\"d\":\"%s\"}",
              historyTestIndex_, historyTestCount_,
              historyChunkIndex_, historyTotalChunks_, chunkBuf);

          bool sent = sendToMaster(frameBuf);
          if (!sent) {
            LOG_WARN(LogCategory::CORE, "THP chunk %d/%d gonderilemedi (%d bytes), tekrar denenecek",
                     historyChunkIndex_, historyTotalChunks_, frameLen);
            lastHistorySyncTime_ = now;
            return; // Aynı chunk sonraki tick'te tekrar denenecek
          }

          historyChunkIndex_++;
          lastHistorySyncTime_ = now;
        } else {
          // Bu testin tüm chunk'ları gönderildi — sonraki teste geç
          historyTestIndex_++;
          historyPayloadLen_ = 0; // Buffer'ı sıfırla (heap alloc/free yok)
          historyPhase_ = 1;    // Sonraki test için Phase 1'e dön
          lastHistorySyncTime_ = now;
        }
      }
    }
  }
}

// sendBroadcast() removed — hardcode MAC, no HELLO needed

void ESPNowSlave::onDataRecv(const uint8_t *mac, const uint8_t *incomingData,
                             int len) {
  if (!instance_)
    return;

  // Ignore @S: fast stream data from other devices
  if (len > 2 && incomingData[0] == '@')
    return;

  // Any data from master confirms connection
  instance_->lastSeen_ = millis();
  instance_->connected_ = true;
  instance_->consecutiveFailCount_ = 0;

  // Push to receive queue — ESP-NOW task will process via handleMessage()
  if (instance_->recvQueue_) {
    EspNowRecvItem item;
    int copyLen = (len < 255) ? len : 255;
    memcpy(item.data, incomingData, copyLen);
    item.data[copyLen] = '\0';
    xQueueSend(instance_->recvQueue_, &item, 0);
  }
}

void ESPNowSlave::onDataSent(const uint8_t *mac, esp_now_send_status_t status) {
  if (!instance_)
    return;
  if (status == ESP_NOW_SEND_SUCCESS) {
    instance_->lastSeen_ = millis();
    instance_->consecutiveFailCount_ = 0;
    if (!instance_->connected_) {
      instance_->connected_ = true;
      LOG_INFO(LogCategory::CORE, "Master bağlantısı yeniden kuruldu.");
    }
  } else {
    instance_->consecutiveFailCount_++;
    if (instance_->connected_ &&
        instance_->consecutiveFailCount_ >= SEND_FAIL_DISCONNECT_THRESHOLD) {
      instance_->connected_ = false;
      LOG_WARN(LogCategory::CORE, "Master bağlantısı kesildi (%d ardışık SEND_FAIL)",
               instance_->consecutiveFailCount_);
    }
  }
}

void ESPNowSlave::broadcastTime(const char *datetimeStr) {
  uint8_t broadcastMac[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  char msg[128];

  // Create JSON command
  snprintf(msg, sizeof(msg), "{\"cmd\":\"SET_TIME\",\"datetime\":\"%s\"}",
           datetimeStr);

  // Send via queue (thread-safe)
  if (instance_ && instance_->queueSend(broadcastMac, msg, strlen(msg))) {
    LOG_INFO(LogCategory::NETWORK, "Zaman Yayını kuyruğa eklendi: %s", datetimeStr);
  } else {
    LOG_WARN(LogCategory::NETWORK, "Zaman Yayını kuyruğa eklenemedi!");
  }
}

bool ESPNowSlave::sendToDevice(const char *targetNameOrMac,
                               const char *message) {
  uint8_t targetMac[6];
  bool found = false;

  // 1. Try to parse MAC address directly (XX:XX:XX:XX:XX:XX)
  if (strlen(targetNameOrMac) == 17 && targetNameOrMac[2] == ':') {
    int values[6];
    if (sscanf(targetNameOrMac, "%x:%x:%x:%x:%x:%x", &values[0], &values[1],
               &values[2], &values[3], &values[4], &values[5]) == 6) {
      for (int i = 0; i < 6; i++)
        targetMac[i] = (uint8_t)values[i];
      found = true;
    }
  }

  // Fallback: If target is "ALL" or "BROADCAST", send to FF:FF...
  if (strcasecmp(targetNameOrMac, "ALL") == 0 ||
      strcasecmp(targetNameOrMac, "BROADCAST") == 0) {
    memset(targetMac, 0xFF, 6);
    found = true;
  }

  if (!found) {
    Serial.printf("❌ Hedef çözülemedi: %s (MAC formatı kullanın)\n",
                  targetNameOrMac);
    return false;
  }

  if (instance_ && instance_->queueSend(targetMac, message, strlen(message))) {
    Serial.printf("✅ Mesaj kuyruğa eklendi -> %s\n", targetNameOrMac);
    return true;
  } else {
    Serial.printf("❌ Kuyruk hatası\n");
    return false;
  }
}

// ── Operator PIN helpers ─────────────────────────────────────────────────────

bool ESPNowSlave::checkPin(const char *pin) {
  for (int i = 0; i < userPinCount_; i++) {
    if (strcmp(userPinList_[i].pin, pin) == 0) {
      strncpy(activeOperator_, userPinList_[i].name,
              sizeof(activeOperator_) - 1);
      activeOperator_[sizeof(activeOperator_) - 1] = '\0';
      LOG_INFO(LogCategory::CORE, "PIN dogrulandı: Operatör = %s",
               activeOperator_);
      return true;
    }
  }
  activeOperator_[0] = '\0';
  LOG_WARN(LogCategory::CORE, "PIN bulunamadı: %s", pin);
  return false;
}

void ESPNowSlave::setActiveOperator(const char *name) {
  strncpy(activeOperator_, name, sizeof(activeOperator_) - 1);
  activeOperator_[sizeof(activeOperator_) - 1] = '\0';
}

} // namespace GLT