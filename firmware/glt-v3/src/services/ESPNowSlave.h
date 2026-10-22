#ifndef ESPNOW_SLAVE_H
#define ESPNOW_SLAVE_H

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>

namespace GLT {

class RFIDService; // Forward declaration

// ═══════════════════════════════════════════════════════════════════
// HARDCODED MASTER MAC (master firmware sets this via esp_wifi_set_mac)
// ═══════════════════════════════════════════════════════════════════
static constexpr uint8_t MASTER_MAC[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};
static constexpr int SEND_FAIL_DISCONNECT_THRESHOLD = 10;

// ═══ ESP-NOW Thread Queue Item Types ═══
struct EspNowSendItem {
    uint8_t mac[6];
    uint8_t len;
    char data[251];  // 250 payload + null terminator
};

struct EspNowRecvItem {
    char data[256];
};

// ═══════════════════════════════════════════════════════════════════
// ESP-NOW SLAVE SERVICE
// ═══════════════════════════════════════════════════════════════════

class ESPNowSlave {
public:
  ESPNowSlave();
  ~ESPNowSlave() = default;

  /**
   * Initialize ESP-NOW slave
   * @param deviceName Device name (will be sent to master)
   * @return true if successful
   */
  bool begin(const char *deviceName);

  /**
   * Inject RFID Service for CRC calculation
   */
  void setRFIDService(RFIDService *service) { rfidService_ = service; }

  /**
   * Send data to master
   * @param data Data string to send (max 250 bytes)
   * @return true if sent successfully
   */
  bool sendToMaster(const char *data);

  /**
   * Set callback for received data
   * @param callback Function to call when data received
   */
  void setRecvCallback(void (*callback)(const char *data));

  /**
   * Get connection status
   * @return true if connected to master
   */
  bool isConnected() { return connected_; }

  /**
   * Check if ESP-NOW initialized successfully
   */
  bool isInitialized() { return initialized_; }

  /**
   * Get device name
   */
  const char *getDeviceName() { return deviceName_; }

  /**
   * Get unique device ID (LCC_ + Base64url of MAC, 12 chars)
   */
  const char *getDeviceId() { return deviceId_; }

  /**
   * Handle incoming command from master (JSON)
   */
  void handleMessage(const char *data);

  /**
   * Update connection status (call in loop)
   */
  void update();

private:
  char deviceName_[32];
  char deviceId_[16];  // "LCC_" + 8 chars Base64url of MAC
  uint8_t masterMAC_[6];
  bool connected_;
  bool initialized_ = false;
  bool masterRegistered_;
  unsigned long lastSeen_;
  void (*recvCallback_)(const char *data);

  // Dependencies
  RFIDService *rfidService_ = nullptr;

  static void onDataRecv(const uint8_t *mac, const uint8_t *incomingData,
                         int len);
  static void onDataSent(const uint8_t *mac, esp_now_send_status_t status);

  static ESPNowSlave *instance_; // For callbacks

  void generateDeviceId();  // MAC -> Base64url -> "LCC_XXXXXXXX"

  // ─── FreeRTOS ESP-NOW Thread ─────────────────────────────────────
  static constexpr int SEND_QUEUE_SIZE = 20;
  static constexpr int RECV_QUEUE_SIZE = 10;
  static constexpr int TASK_STACK_SIZE = 8192;
  static constexpr int TASK_PRIORITY = 2;
  static constexpr int TASK_CORE = 0;

  TaskHandle_t taskHandle_ = nullptr;
  QueueHandle_t sendQueue_ = nullptr;
  QueueHandle_t recvQueue_ = nullptr;

  static void taskEntry(void* param);
  void taskLoop();
  bool queueSend(const uint8_t* mac, const char* data, uint8_t len);

  // 10x consecutive SEND_FAIL → disconnect
  int consecutiveFailCount_ = 0;

  // Non-blocking Sync State
  bool syncActive_ = false;
  int syncIndex_ = 0;
  unsigned long lastSyncPacketTime_ = 0;
  int syncTotal_ = 0;

  // History non-blocking Sync State (Dynamic THP Chunking)
  // Metadata + basınç verisi tek pipe-delimited payload'a birleştirilir,
  // 180-byte chunk'lara bölünüp sadece "THP" komutuyla gönderilir.
  bool historySyncActive_ = false;
  uint16_t historyTestCount_ = 0;
  uint16_t historyTestIndex_ = 0;
  uint16_t historyChunkIndex_ = 0;
  uint16_t historyTotalChunks_ = 0;
  int historyPhase_ = 0;
  unsigned long lastHistorySyncTime_ = 0;
  int16_t historySampleBuf_[600]; // buffer for pressure data (MAX_PRESSURE_SAMPLES)
  char historyPayloadBuf_[4200];   // Static buffer — heap fragmentation önlenir
  uint16_t historyPayloadLen_ = 0; // historyPayloadBuf_ içindeki geçerli veri uzunluğu

  // ── Chunked RFID Sync State (PC → Slave toplu port aktarımı) ────
  bool rfidSyncActive_ = false;
  char rfidSyncBuf_[4200];           // Static buffer — tüm pipe-delimited payload
  uint16_t rfidSyncBufLen_ = 0;      // Buffer'daki geçerli veri uzunluğu
  uint16_t rfidSyncExpectedChunks_ = 0;
  uint16_t rfidSyncReceivedChunks_ = 0;
  uint32_t rfidSyncExpectedCrc_ = 0;
  uint16_t rfidSyncExpectedSize_ = 0;
  int rfidSyncExpectedCount_ = 0;
  unsigned long lastRfidSyncChunkTime_ = 0; // Son chunk alım zamanı (timeout için)
  uint32_t rfidPayloadCrc_ = 0;  // Son başarılı sync'in payload CRC32'si (0 = sync gerekli)

  // ── User/PIN Store ───────────────────────────────────────────────
  static constexpr int MAX_USER_PINS = 100;
  struct UserPinEntry {
    char name[32];
    char pin[8];
  };
  UserPinEntry userPinList_[MAX_USER_PINS];
  int userPinCount_ = 0;
  uint32_t userPinPayloadCrc_ = 0;  // Son başarılı PIN sync'in CRC32'si (0 = sync gerekli)
  char activeOperator_[32] = "";

  // Debug
  static bool showErrorLog_;

public:
  static void toggleErrorLog(bool enable) { showErrorLog_ = enable; }
  static bool isErrorLogEnabled() { return showErrorLog_; }

  static void broadcastTime(const char *datetimeStr);
  static bool sendToDevice(const char *targetNameOrMac, const char *message);

  /** Trigger offline history sync (send stored tests to master) */
  void triggerHistorySync();

  // ── Operator PIN Management ──────────────────────────────────────
  /**
   * Try to authenticate an operator by 4-digit PIN.
   * If found, sets activeOperator_ and returns true.
   * If not found, clears activeOperator_ and returns false.
   */
  bool checkPin(const char *pin);

  /** Get current PIN count in memory */
  int getPinCount() const { return userPinCount_; }

  /** Manually set the active operator name (e.g. from DWIN keypad result) */
  void setActiveOperator(const char *name);

  /** Get current active operator name ("" if none) */
  const char *getActiveOperator() const { return activeOperator_; }

  /** Clear the active operator (logout) */
  void clearActiveOperator() { activeOperator_[0] = '\0'; }

private:
  // ── PIN Kalıcı Hafıza ────────────────────────────────────────────
  void savePinsToStorage();   // LittleFS'e kaydet
  void loadPinsFromStorage(); // LittleFS'den yükle

  // ── RFID Payload CRC Kalıcı Hafıza ─────────────────────────────
  void saveCrcToFlash();      // rfidPayloadCrc_ → LittleFS
  void loadCrcFromFlash();    // LittleFS → rfidPayloadCrc_

  // ── User PIN CRC Kalıcı Hafıza ─────────────────────────────────
  uint32_t calculateUserPinCRC();     // Mevcut PIN listesinden CRC32 hesapla
  void saveUserPinCrcToFlash();       // userPinPayloadCrc_ → LittleFS
  void loadUserPinCrcFromFlash();     // LittleFS → userPinPayloadCrc_
};

} // namespace GLT

#endif // ESPNOW_SLAVE_H
