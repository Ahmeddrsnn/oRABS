#include "application/SerialDebug.h"
#include "config.h"
#include "core/Logger.h"
#include "drivers/RFIDReader.h"
#include "services/BatteryService.h"
#include "services/DwinService.h"
#include "services/ESPNowSlave.h"
#include "services/GasketService.h" // YENİ
#include "services/PressureService.h"
#include "services/RFIDService.h"
#include "services/RtcService.h"
#include "services/TestParametersService.h"
#include "services/TestStorageService.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <esp_timer.h>
#include <LittleFS.h>
#include <SD_MMC.h>
#include <WiFi.h>
#include <esp_now.h>

using namespace GLT;

// Global instances
RFIDReader *rfidReader = nullptr;
RFIDService *rfidService = nullptr;
ESPNowSlave *espNowSlave = nullptr;
PressureService *pressureService = nullptr;
GasketService *gasketService = nullptr; // YENİ
SerialDebug *debugInterface = nullptr;

// ESP-NOW message callback declaration
void onESPNowReceived(const char *data);

// Global state for Gasket mount control
static bool isGasketMounted = false; // Initial state: not mounted
static bool mountSuccessWaitingForButton =
    false;                          // Wait 2s before showing test start button
unsigned long mountSuccessTime = 0; // Time when mount completed
static bool rfidReadingEnabled =
    true; // RFID reading lock - only disabled during mount operation

// ═══════════════════════════════════════════════════════════════════
// RFID LIVE / LATCHED SİSTEMİ
// ═══════════════════════════════════════════════════════════════════
// rfid_live   : IDLE modda anlık okunan tag bilgisi
// rfid_latched: Mount anında kilitlenen tag bilgisi (mount boyunca ASLA
// değişmez)
static uint32_t rfid_live = 0;      // IDLE'da RFID'den okunan tag UID
static uint16_t rfid_live_port = 0;  // rfid_live'ın port numarası
static TestRecipe rfid_live_recipe; // rfid_live'ın recipe'i

static uint32_t rfid_latched = 0;      // Mount anında kilitlenen UID
static uint16_t rfid_latched_port = 0;  // Kilitlenen port
static TestRecipe rfid_latched_recipe; // Kilitlenen recipe

// Port'u DWIN ekrana yaz: sol → 0x5300, sag → 0x5302
static inline void dwinWritePort(uint16_t encodedPort) {
  DwinService::getInstance().writeVP(0x5300, encodedPort >> 8);
  DwinService::getInstance().writeVP(0x5302, encodedPort & 0xFF);
}

// ═══════════════════════════════════════════════════════════════════
// UART MODE TRACKING
// ═══════════════════════════════════════════════════════════════════
// ── LOG Forwarding Suppression (IDLE pressure reads sırasında kapat) ──
volatile bool suppressRemoteLog = false;

enum class UartMode { RFID, MODBUS };
static UartMode currentUartMode = UartMode::RFID;

// ═══════════════════════════════════════════════════════════════════
// IDLE PERİYODİK BASINÇ PENCERESİ
// ═══════════════════════════════════════════════════════════════════
static unsigned long lastIdlePressureRead = 0;
static const unsigned long IDLE_PRESSURE_INTERVAL_MS = 10000; // 10 sn'de bir
uint16_t idlePressureValue = 0; // Son okunan IDLE basınç değeri (extern RFIDService.cpp)

// MOUNTING STATE
static bool isMounting = false;
static const uint16_t MOUNT_TARGET_PRESSURE = 1600;

// DISMOUNT REQUIRED: Test bittikten sonra dismount yapılana kadar mount/test start engellenir
static bool dismountRequired = false;

// MOUNT TIMEOUT & WARNINGS
static unsigned long mountStartTime = 0;
static uint16_t lastMountCountdown = 99;
static bool isWarning77Active = false;
static unsigned long warning77StartTime = 0;
static bool isWarning74Active = false;
static unsigned long warning74StartTime = 0;
static bool isWarning75Active = false; // Persistent until removal
static unsigned long lastBatteryFlashTime = 0;
static bool batteryFlashState = false;

// OTA MODE STATE (VP 0x5206 - Similar to Dismount Logic)
static bool isOTAModeActive = false;
static uint16_t lastOTAButtonValue = 0;
static unsigned long lastOTAButtonChangeTime = 0;
static bool otaZeroGlitchCounter = 0;

// ═══════════════════════════════════════════════════════════════════
// POWER LATCH INACTIVITY TIMEOUT
// ═══════════════════════════════════════════════════════════════════
// 5 dakika boyunca ekranda hiçbir tuşa basılmazsa güç kesilir.
// Test devam ederken (IDLE dışı) timeout devre dışıdır.
static unsigned long lastActivityTime = 0;
static const unsigned long INACTIVITY_TIMEOUT_MS = 5UL * 60UL * 1000UL; // 5 dakika

// ═══════════════════════════════════════════════════════════════════
// KAYAN PENCERE (ROLLING WINDOW) TEST ALGORITMASI
// ═══════════════════════════════════════════════════════════════════
// P7 = Kayan pencere boyutu (sn) — reçeteden gelir, sabit değildir.
// P6 = Kabul Edilebilir Basınç Düşümü (Pa) — pencerede bu kadardan az düşüş → PASS
// P8 = Kritik Basınç Sınırı (Pa) — toplam düşüş bunu aşarsa → anında FAIL
// Süre limiti YOK. Test PASS veya FAIL olana kadar devam eder.
#define ROLLING_WINDOW_MAX 600 // Maksimum pencere boyutu (saniye)
static uint16_t pressureHistory[ROLLING_WINDOW_MAX];
static int pressureHistoryIndex = 0;
static int pressureHistoryCount = 0;

// ═══════════════════════════════════════════════════════════════════
// BASINÇ ARTIŞI TESPİTİ (Pompa kapalıyken dış etken koruması)
// ═══════════════════════════════════════════════════════════════════
// Stabilizasyonun son 10 saniyesinden itibaren en düşük basıncı takip eder.
// Eğer basınç bu minimumun TOLERANCE üzerine çıkarsa → dış etken var demektir
// (ör. laminar flow fan). Rolling window sıfırlanır, minimum güncellenir.
static const int16_t PRESSURE_RISE_TOLERANCE = 5; // Kolay değiştirilebilir eşik (Pa)
static int16_t pumpOffMinPressure = 0;             // Pompa durduğundan beri en düşük basınç
static bool pumpOffTrackingActive = false;          // Takip aktif mi?

// ═══════════════════════════════════════════════════════════════════
// TEST KAYIT — Basınç Zaman Serisi Buffer (1Hz)
// ═══════════════════════════════════════════════════════════════════
static int16_t testRecordSamples[MAX_PRESSURE_SAMPLES]; // Basınç kayıt dizisi
static uint16_t testRecordSampleCount = 0;               // Kaydedilen örnek sayısı
static unsigned long lastRecordSampleTime = 0;           // Son kayıt zamanı
static int16_t testRecordMaxPressure = 0;                // Test sırasındaki maks basınç
static bool testRecordSaved = false;                     // FINISHED'da tekrar kaydetmeyi önle

// ═══════════════════════════════════════════════════════════════════
// UART SWITCHING (TEK FONKSİYON)
// ═══════════════════════════════════════════════════════════════════

void switchUart(UartMode target) {
  // Guard: Aynı moda geçiş yapma
  if (currentUartMode == target)
    return;

  if (target == UartMode::RFID) {
    LOG_INFO(LogCategory::CORE, "🔄 UART -> RFID");

    // 1. Stop Modbus — FreeRTOS task durdurulur, uartMutex_ ile senkronize
    //    edilir, modbusSerial_->end() (=Serial1.end()) çağrılır.
    if (pressureService)
      pressureService->end();

    // 2. Stabilizasyon — Serial1.end() pin'leri serbest bıraktı,
    //    donanım geçişi için kısa bekleme.
    delay(2);

    // 3. Start RFID — Serial1.begin(9600, GPIO19) + rdm_.begin(&Serial1)
    if (rfidReader) {
      rfidReader->begin(Config::hardware.rfid.rx,
                        Config::hardware.rfid.uart_num);
    }
    if (rfidService)
      rfidService->resetTimeout(); // Reset timeout to prevent false remove
    currentUartMode = UartMode::RFID;
    LOG_INFO(LogCategory::CORE, "✅ UART: RFID Aktif (Pin %d)",
             Config::hardware.rfid.rx);

  } else { // UartMode::MODBUS
    LOG_INFO(LogCategory::CORE, "🔄 UART -> Modbus");

    // 1. Stop RFID — Serial1.flush() + Serial1.end()
    if (rfidReader)
      rfidReader->end();

    // 2. Stabilizasyon
    delay(2);

    // 3. Start Modbus — Serial1.begin(9600, GPIO6, GPIO7) + FreeRTOS task aktif
    if (pressureService) {
      pressureService->begin(Config::hardware.modbus_pressure.rx,
                             Config::hardware.modbus_pressure.tx,
                             Config::hardware.modbus_pressure.baud,
                             Config::hardware.modbus_pressure.slave_id,
                             Config::hardware.modbus_pressure.start_reg,
                             Config::hardware.modbus_pressure.quantity);
    }
    currentUartMode = UartMode::MODBUS;
    LOG_INFO(LogCategory::CORE, "✅ UART: Modbus Aktif (RX:%d, TX:%d)",
             Config::hardware.modbus_pressure.rx,
             Config::hardware.modbus_pressure.tx);
  }
}

// Geriye dönük uyumluluk (eski çağrıları kırmamak için)
void switchSerialToRFID() { switchUart(UartMode::RFID); }
void switchSerialToModbus() { switchUart(UartMode::MODBUS); }

// ═══════════════════════════════════════════════════════════════════
// OTA MODE FUNCTIONS
// ═══════════════════════════════════════════════════════════════════
static esp_timer_handle_t fastStreamTimer = nullptr; // OTA'da durdurulur, setup()'ta oluşturulur

void startOTAMode() {
  LOG_INFO(LogCategory::CORE, "🔄 OTA MODU BAŞLATILIYOR...");

  // 0. Fast Stream Timer'ı DURDUR (Cache/WDT crash önleme)
  if (fastStreamTimer) {
    esp_timer_stop(fastStreamTimer);
    LOG_INFO(LogCategory::CORE, "Fast stream timer durduruldu (OTA güvenliği)");
  }

  // 1. Stop ESP-NOW
  esp_now_deinit();
  LOG_INFO(LogCategory::CORE, "ESP-NOW durduruldu (OTA için)");

  // 2. Stop RFID/Modbus (Serial1 serbest)
  if (rfidReader) {
    rfidReader->end();
  }
  if (pressureService) {
    pressureService->end();
  }

  // 3. Start WiFi
  LOG_INFO(LogCategory::CORE, "WiFi bağlanıyor: %s", Config::app.wifi.ssid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(Config::app.wifi.ssid, Config::app.wifi.password);

  unsigned long startTime = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - startTime > Config::app.wifi.connection_timeout_ms) {
      LOG_ERROR(LogCategory::CORE, "WiFi bağlantı zaman aşımı!");
      DwinService::getInstance().writeVP(0x601B, 79); // Warning 79 (WiFi Fail)
      return;
    }
    delay(500);
    LOG_INFO(LogCategory::CORE, "WiFi bağlanıyor...");
  }

  LOG_INFO(LogCategory::CORE, "✅ WiFi Bağlandı! IP: %s",
           WiFi.localIP().toString().c_str());

  // 4. Configure ArduinoOTA
  ArduinoOTA.setHostname(Config::app.wifi.hostname);
  ArduinoOTA.setPort(Config::app.wifi.ota_port);

  // Şifre yok (kullanıcı isteği)
  if (strlen(Config::app.wifi.ota_password) > 0) {
    ArduinoOTA.setPassword(Config::app.wifi.ota_password);
  }

  ArduinoOTA.onStart([]() {
    String type =
        (ArduinoOTA.getCommand() == U_FLASH) ? "sketch" : "filesystem";
    LOG_INFO(LogCategory::CORE, "OTA Başladı: %s", type.c_str());
    DwinService::getInstance().writeVP(0x601B, 80); // Warning 80 (OTA Active)

    // Draw "OTA UPLOAD" text in white
    DwinService::getInstance().drawString(10, 10, 0x34, 0xFFFF, 0x0000,
                                          "OTA UPLOAD");
  });

  ArduinoOTA.onEnd([]() {
    LOG_INFO(LogCategory::CORE, "✅ OTA Tamamlandı");
    DwinService::getInstance().writeVP(0x601B, 81); // Warning 81 (OTA Success)

    // Draw "OTA DONE" text in green
    DwinService::getInstance().drawString(10, 10, 0x34, 0x07E0, 0x0000,
                                          "OTA DONE");
  });

  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    uint8_t percent = (progress * 100) / total;
    static uint8_t lastPercent = 0;
    if (percent != lastPercent && percent % 10 == 0) {
      lastPercent = percent;
      LOG_INFO(LogCategory::CORE, "OTA İlerleme: %d%%", percent);
      // VP'ye progress yazılabilir (opsiyonel)
    }
  });

  ArduinoOTA.onError([](ota_error_t error) {
    LOG_ERROR(LogCategory::CORE, "OTA Hata[%u]: ", error);
    if (error == OTA_AUTH_ERROR)
      LOG_ERROR(LogCategory::CORE, "Auth Failed");
    else if (error == OTA_BEGIN_ERROR)
      LOG_ERROR(LogCategory::CORE, "Begin Failed");
    else if (error == OTA_CONNECT_ERROR)
      LOG_ERROR(LogCategory::CORE, "Connect Failed");
    else if (error == OTA_RECEIVE_ERROR)
      LOG_ERROR(LogCategory::CORE, "Receive Failed");
    else if (error == OTA_END_ERROR)
      LOG_ERROR(LogCategory::CORE, "End Failed");
    DwinService::getInstance().writeVP(0x601B, 82); // Warning 82 (OTA Error)
  });

  ArduinoOTA.begin();
  LOG_INFO(LogCategory::CORE, "✅ ArduinoOTA Başlatıldı (Port: %d)",
           Config::app.wifi.ota_port);

  isOTAModeActive = true;
  DwinService::getInstance().writeVP(0x601B, 80); // Warning 80 (OTA Waiting)
}

void stopOTAMode() {
  LOG_INFO(LogCategory::CORE, "OTA MODU DURDURULUYOR...");

  ArduinoOTA.end();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);

  isOTAModeActive = false;

  // Fast Stream Timer'ı tekrar başlat
  if (fastStreamTimer) {
    esp_timer_start_periodic(fastStreamTimer, 200000); // 200ms = 5Hz
    LOG_INFO(LogCategory::CORE, "Fast stream timer yeniden başlatıldı");
  }

  // Restart ESP-NOW
  esp_now_init();
  if (espNowSlave) {
    espNowSlave->begin(Config::app.rfid.device_name);
    LOG_INFO(LogCategory::CORE, "ESP-NOW yeniden başlatıldı");
  }

  // Restart RFID
  switchSerialToRFID();

  DwinService::getInstance().writeVP(0x601B, 0); // Clear warning
  LOG_INFO(LogCategory::CORE, "✅ Normal moda dönüldü");
}

// ---------------- TEST LOGIC ENUMS & VARS ----------------
enum class TestState {
  IDLE,
  MOUNTING_GASKET, // Inflate Gasket (Solenoid 1)
  PRE_INFLATION,   // Inflate Glove to Target (Solenoid 3)
  CONDITIONING,    // Stabilization (Maintain Target - 50Pa)
  TESTING,         // Leak Test (All Closed)
  FINISHED         // Result / Vent
};

TestState currentTestState = TestState::IDLE;

// Active Recipe (from RFID Tag)
TestRecipe
    activeTestRecipe; // Recipe for current test (loaded when test starts)

// State Variables
unsigned long stateStartTime = 0;
unsigned long lastReinflateTime = 0;

bool isReinflating = false;
int conditioningDuration = 0; // seconds
int32_t conditioningStartPressure = 0;
int32_t conditioningEndPressure = 0;
int32_t testStartPressure = 0;
bool testResult = false;

// Test karar anındaki değerler (FINISHED'da venting sonrası hesaplanmaması için)
int16_t testEndTotalDrop = 0;   // PASS/FAIL anındaki toplam düşüş
int16_t testEndWindowDrop = 0;  // PASS/FAIL anındaki pencere düşüşü
int16_t testEndPressure = 0;    // PASS/FAIL anındaki basınç

// Test timing tracking (for 0x5509 and 0x5508)
unsigned long testTotalStartTime =
    0; // PRE_INFLATION start (for total time 0x5509)
unsigned long testPhaseStartTime =
    0; // TESTING phase start (for test phase time 0x5508)
bool tamperingDetected = false;
unsigned long lastConditioningLogTime = 0;
bool shouldTriggerMount = false;     // Global flag for mount trigger
bool shouldTriggerTestStart = false; // Global flag for test start trigger
bool shouldTriggerAbort = false;     // Global flag for abort trigger
bool shouldTriggerDismount = false;  // Global flag for dismount trigger

// ═══════════════════════════════════════════════════════════════════
// KULLANICI PIN DOĞRULAMA SİSTEMİ
// ═══════════════════════════════════════════════════════════════════
static bool userPinVerified = false;         // Kullanıcı PIN doğrulandı mı?
static bool pinPageReady = false;            // PIN sayfasına geçildi mi?
static unsigned long lastPinCheckTime = 0;   // Son PIN kontrol zamanı
static const unsigned long PIN_CHECK_INTERVAL_MS = 300; // 300ms'de bir kontrol

#define DWIN_LOGO_ID 94 // LCC Logo ID (0x5E)

// Helper for CRC16 (Modbus) - Local to setup/startup
uint16_t calcStartupCRC(const uint8_t *data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int j = 0; j < 8; j++) {
      if (crc & 1)
        crc = (crc >> 1) ^ 0xA001;
      else
        crc >>= 1;
    }
  }
  return crc;
}

// broadcastTestData() removed — phase/testElapsed now in @S: stream

// ═══════════ Helper: get current test phase as single char ═══════════
static char getTestPhaseChar() {
  switch (currentTestState) {
    case TestState::IDLE:            return 'I';
    case TestState::MOUNTING_GASKET: return 'M';
    case TestState::PRE_INFLATION:   return 'P';
    case TestState::CONDITIONING:    return 'S';
    case TestState::TESTING:         return 'T';
    case TestState::FINISHED:        return 'F';
    default:                         return 'I';
  }
}

static int getTestElapsedSec() {
  if (testTotalStartTime > 0)
    return (int)((millis() - testTotalStartTime) / 1000);
  return 0;
}

// ═══ FAST STREAM TIMER (esp_timer — main loop'tan tamamen bağımsız) ═══
// fastStreamTimer tanımı OTA bölümünün üstünde yapıldı

static void fastStreamTimerCallback(void* arg) {
    if (rfidService && espNowSlave && espNowSlave->isInitialized()) {
        rfidService->sendFastStream(
            rfidService->getLastDetectedTag(),
            getTestPhaseChar(),
            getTestElapsedSec());
    }
}

void setup() {
  // Güç Kilidi (Power Latch) - Pin 21 HIGH tutarak cihaz açık kalır
  pinMode(21, OUTPUT);
  delay(2000); // Kazara basmaya karşı koruma
  digitalWrite(21, HIGH);

  // Inactivity timer başlat
  lastActivityTime = millis();

  // USB Serial başlat
  Serial.begin(115200);

  // Logger başlat
  Logger::getInstance().setLevel(LogLevel::DEBUG);
  Logger::getInstance().enableTimestamp(true);

  LOG_INFO(LogCategory::CORE, "ESP32-S3 GLT v3 başlatılıyor...");

  // ═══════════════════════════════════════════════════════════════════
  // BOOT-TIME OTA CHECK — 1 saniye içinde OTA ağına bağlanırsa
  // program çalışmaz, sadece OTA modu aktif kalır.
  // ═══════════════════════════════════════════════════════════════════
  {
    LOG_INFO(LogCategory::CORE, "Boot OTA kontrol: WiFi deneniyor...");
    WiFi.mode(WIFI_STA);
    WiFi.begin(Config::app.wifi.ssid, Config::app.wifi.password);

    unsigned long otaStart = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - otaStart < 1000) {
      delay(50);
    }

    if (WiFi.status() == WL_CONNECTED) {
      LOG_INFO(LogCategory::CORE,
               "Boot OTA: WiFi bağlandı! IP: %s — OTA moduna giriliyor",
               WiFi.localIP().toString().c_str());

      ArduinoOTA.setHostname(Config::app.wifi.hostname);
      ArduinoOTA.setPort(Config::app.wifi.ota_port);
      if (strlen(Config::app.wifi.ota_password) > 0) {
        ArduinoOTA.setPassword(Config::app.wifi.ota_password);
      }
      ArduinoOTA.onStart([]() {
        LOG_INFO(LogCategory::CORE, "Boot OTA: Upload başladı");
      });
      ArduinoOTA.onEnd([]() {
        LOG_INFO(LogCategory::CORE, "Boot OTA: Upload tamamlandı, yeniden başlatılıyor...");
      });
      ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        static uint8_t lastPct = 0;
        uint8_t pct = (progress * 100) / total;
        if (pct != lastPct && pct % 10 == 0) {
          lastPct = pct;
          LOG_INFO(LogCategory::CORE, "Boot OTA: %%%d", pct);
        }
      });
      ArduinoOTA.onError([](ota_error_t error) {
        LOG_ERROR(LogCategory::CORE, "Boot OTA Hata: %u", error);
      });
      ArduinoOTA.begin();

      // Sonsuz OTA döngüsü — program asla başlamaz
      while (true) {
        ArduinoOTA.handle();
        delay(10);
      }
      // Buraya asla ulaşılmaz
    } else {
      LOG_INFO(LogCategory::CORE,
               "Boot OTA: WiFi bağlanamadı, normal başlatma devam ediyor.");
      WiFi.disconnect(true);
      WiFi.mode(WIFI_OFF);
      delay(10);
    }
  }

  // 1. Dosya Sistemi (LittleFS - Internal Flash)
  if (!LittleFS.begin(true)) {
    LOG_ERROR(LogCategory::CORE,
              "LittleFS (Flash) başlatılamadı! Kalıcı hafıza devre dışı.");
  } else {
    LOG_INFO(LogCategory::CORE, "Dosya sistemi (LittleFS) bağlandı.");
  }

  // 2. SD Kart Başlatma
  SD_MMC.setPins(Config::hardware.sd.clk, Config::hardware.sd.cmd,
                 Config::hardware.sd.d0, Config::hardware.sd.d1,
                 Config::hardware.sd.d2, Config::hardware.sd.d3);

  esp_log_level_set("sdmmc_common", ESP_LOG_NONE);
  esp_log_level_set("vfs_fat_sdmmc", ESP_LOG_NONE);
  esp_log_level_set("SD_MMC", ESP_LOG_NONE);

  if (SD_MMC.begin("/sd", true)) {
    LOG_INFO(LogCategory::CORE, "SD Kart tespit edildi. Kapasite: %llu MB",
             SD_MMC.cardSize() / (1024 * 1024));
  } else {
    LOG_WARN(LogCategory::CORE, "SD Kart bulunamadı veya başlatılamadı.");
  }

  // 3. Config başlat
  Config::init();
  Config::loadFromNVS();

  // 4. Test Parametre Servisi
  LOG_INFO(LogCategory::CORE, "Test parametre servisi başlatılıyor...");
  TestParametersService::getInstance()->begin();

  // 5. RFID Reader + Service
  LOG_INFO(LogCategory::CORE, "RFID okuyucu başlatılıyor...");
  rfidReader = new RFIDReader();
  if (!rfidReader->begin(Config::hardware.rfid.rx,
                         Config::hardware.rfid.uart_num)) {
    LOG_ERROR(LogCategory::CORE, "RFID okuyucu başlatılamadı!");
  }

  LOG_INFO(LogCategory::CORE, "RFID servisi başlatılıyor...");
  rfidService = new RFIDService(*rfidReader, Config::app.rfid.max_tags);
  if (!rfidService->begin()) {
    LOG_ERROR(LogCategory::CORE, "RFID servisi başlatılamadı!");
  }

  // 6. Basınç Servisi (Modbus RTU)
  LOG_INFO(LogCategory::CORE, "Basınç servisi başlatılıyor (Modbus RTU)...");
  pressureService = new PressureService();
  if (!pressureService->begin(Config::hardware.modbus_pressure.rx,
                              Config::hardware.modbus_pressure.tx,
                              Config::hardware.modbus_pressure.baud,
                              Config::hardware.modbus_pressure.slave_id,
                              Config::hardware.modbus_pressure.start_reg,
                              Config::hardware.modbus_pressure.quantity)) {
    LOG_ERROR(LogCategory::SENSOR, "Basınç sensörü başlatılamadı!");
  } else {
    LOG_INFO(LogCategory::SENSOR, "Basınç sensörü başlatıldı.");
  }

  // pressureService->begin() Serial1'i Modbus pinlerine yeniden ayarladı.
  // currentUartMode'u gerçek durumla eşleştir, böylece switchUart(RFID) çalışır.
  currentUartMode = UartMode::MODBUS;

  // 7. Conta Basıncı Servisi (Gasket)
  LOG_INFO(LogCategory::SENSOR, "Conta basıncı servisi başlatılıyor...");
  gasketService = new GasketService();
  gasketService->begin(Config::hardware.analog.conta_pressure);

  // 8. İlk UART Modu: RFID (IDLE)
  switchUart(UartMode::RFID);

  // 9. Admin tag kontrolü
  bool adminExists = false;
  uint32_t adminId = Config::app.rfid.admin_tag_1;
  int adminSlot = -1;

  for (int i = 0; i < Config::app.rfid.max_tags; i++) {
    RFIDTag t = rfidService->getTagByIndex(i);
    if (t.isActive && t.id == adminId) {
      adminExists = true;
      adminSlot = i;
      break;
    }
  }

  if (!adminExists) {
    LOG_INFO(
        LogCategory::RFID,
        "Varsayılan admin tagı veritabanında yok. Ekleniyor: 0x%08X (Port: 1)",
        adminId);
    rfidService->addTag(adminId, true, "VarsayilanAdmin", 1);
  } else {
    LOG_INFO(LogCategory::RFID, "Admin tagı doğrulandı: 0x%08X (Slot: %d)",
             adminId, adminSlot);
  }

  // --- DWIN BAŞLANGIÇ SIFIRLAMA ---
  LOG_INFO(LogCategory::CORE, "DWIN Ekran Adresleri Temizleniyor...");
  // 5202 removed - screen controlled
  DwinService::getInstance().writeVP(0x5204, 0); // Mount Button
  DwinService::getInstance().writeVP(0x700D, 0); // Dismount Countdown
  DwinService::getInstance().writeVP(0x700E, 0); // Mount Countdown
  DwinService::getInstance().writeVP(0x601B, 0); // Warnings

  // 0x6200Initialize Debug Interface
  debugInterface = new SerialDebug(*rfidService);
  debugInterface->begin();

  // Initialize ESP-NOW Slave
  LOG_INFO(LogCategory::CORE, "ESP-NOW slave başlatılıyor...");
  espNowSlave = new ESPNowSlave();
  if (!espNowSlave->begin(Config::app.rfid.device_name)) {
    LOG_ERROR(LogCategory::CORE, "ESP-NOW başlatılamadı!");
  } else {
    espNowSlave->setRecvCallback(onESPNowReceived);
    espNowSlave->setRFIDService(rfidService);

    // Register Verify/Remote Logging Callback
    Logger::getInstance().setCallback([](LogLevel level, LogCategory category,
                                         const char *msg) {
      // Suppress during IDLE pressure reads to avoid ESP-NOW queue flooding
      if (suppressRemoteLog) return;

      // Only forward SENSOR and RFID logs to avoid spam/loops
      if ((category == LogCategory::SENSOR || category == LogCategory::RFID) &&
          espNowSlave && espNowSlave->isConnected()) {

        char cleanMsg[128];
        strncpy(cleanMsg, msg, sizeof(cleanMsg) - 1);
        cleanMsg[sizeof(cleanMsg) - 1] = '\0';

        // JSON-safe escaping: quotes and backslashes
        char escaped[128];
        int j = 0;
        for (int i = 0; cleanMsg[i] && j < (int)sizeof(escaped) - 2; i++) {
          if (cleanMsg[i] == '"') {
            escaped[j++] = '\'';
          } else if (cleanMsg[i] == '\\') {
            if (j < (int)sizeof(escaped) - 3) { escaped[j++] = '\\'; escaped[j++] = '\\'; }
          } else {
            escaped[j++] = cleanMsg[i];
          }
        }
        escaped[j] = '\0';

        char packet[256];
        snprintf(packet, sizeof(packet),
                 "{\"cmd\":\"LOG\",\"type\":\"%s\",\"msg\":\"%s\"}",
                 (level == LogLevel::ERROR ? "ERR" : "INF"), escaped);

        espNowSlave->sendToMaster(packet);
      }
    });
  }

  // Initialize DWIN Display
  LOG_INFO(LogCategory::CORE, "DWIN Ekran servisi başlatılıyor...");
  // Swapped RX/TX as per user request (RX=17, TX=18)
  DwinService::getInstance().begin(17, 18, 115200);


  DwinService::getInstance().setButtonCallback([](uint16_t buttons) {
    lastActivityTime = millis(); // Ekran butonuna basıldı → inactivity sıfırla
    LOG_INFO(LogCategory::CORE, "Ekran Buton Basıldı: 0x%04X", buttons);

    // Bit 0 - START / TEST BUTTON
    if (buttons & (1 << 0)) {
      LOG_INFO(
          LogCategory::CORE,
          "-> Buton 0 (Start) - Test Başlatılıyor, Sayfa 3'e Geçiliyor...");
      // Trigger Mount Logic
      shouldTriggerMount = true;
      // Switch to Page 3 (Test Screen)
      DwinService::getInstance().changePage(3);
    }
    // Bit 1
    if (buttons & (1 << 1)) {
      LOG_INFO(LogCategory::CORE, "-> Buton 1 (Stop?)");
    }
    // Bit 3
    if (buttons & (1 << 3)) {
      LOG_INFO(LogCategory::CORE, "-> Buton 3 (Reset?)");
    }
    // Bit 4
    if (buttons & (1 << 4)) {
      LOG_INFO(LogCategory::CORE, "-> Buton 4 (Save?)");
    }
  });

  // --- MAC ADRESİNİ DWIN REGISTERLARA YAZ ---
  // MAC (6 byte) → decimal → 15 hane → 3+4+4+4 böl → 0x6020-0x6026
  {
    uint8_t mac[6];
    WiFi.macAddress(mac);
    uint64_t macDecimal = 0;
    for (int i = 0; i < 6; i++) {
      macDecimal = (macDecimal << 8) | mac[i];
    }
    uint16_t r6026 = (uint16_t)(macDecimal % 10000); macDecimal /= 10000;
    uint16_t r6024 = (uint16_t)(macDecimal % 10000); macDecimal /= 10000;
    uint16_t r6022 = (uint16_t)(macDecimal % 10000); macDecimal /= 10000;
    uint16_t r6020 = (uint16_t)(macDecimal % 1000);  // 3 hane (max 281)

    DwinService::getInstance().writeVP(0x6020, r6020);
    DwinService::getInstance().writeVP(0x6022, r6022);
    DwinService::getInstance().writeVP(0x6024, r6024);
    DwinService::getInstance().writeVP(0x6026, r6026);

    LOG_INFO(LogCategory::CORE, "MAC → DWIN: %s → %03u.%04u.%04u.%04u",
             WiFi.macAddress().c_str(), r6020, r6022, r6024, r6026);
  }

    // 0x6200, 0x6201 → 100 değeri
  DwinService::getInstance().writeVP(0x6200, 100);
  DwinService::getInstance().writeVP(0x6201, 100);


  LOG_INFO(LogCategory::CORE, "✅ Sistem hazır");

  // Initialize RTC Service
  LOG_INFO(LogCategory::CORE, "RTC Servisi başlatılıyor...");
  RtcService::getInstance().begin();

  // Initialize Battery Service
  LOG_INFO(LogCategory::CORE, "Pil Servisi başlatılıyor...");
  BatteryService::getInstance().begin();

  // Initialize Test Storage Service (LittleFS)
  LOG_INFO(LogCategory::CORE, "Test Kayıt Servisi başlatılıyor...");
  TestStorageService::getInstance().init();

  // Start loading animation test (User requested: "loading animasyonu 36 frame
  // çevir")
  DwinService::getInstance().startLoadingAnimation();

  pinMode(41, OUTPUT);
  digitalWrite(41, LOW);

  // Status LED (Heartbeat) - GPIO 42
  pinMode(Config::hardware.indicators.status_led, OUTPUT);

  // --- GASKET CONTROL SETUP ---
  // Pin 1 (Solenoid), Pin 2 (Pump), Pin 3 (Glove), Pin 4 (Drain)
  pinMode(Config::hardware.relays.conta_solenoid, OUTPUT);
  pinMode(Config::hardware.relays.pump_motor, OUTPUT);
  pinMode(Config::hardware.relays.glove_solenoid, OUTPUT);
  pinMode(Config::hardware.relays.drain_solenoid, OUTPUT);

  digitalWrite(Config::hardware.relays.conta_solenoid, LOW);
  digitalWrite(Config::hardware.relays.pump_motor, LOW);
  digitalWrite(Config::hardware.relays.drain_solenoid, LOW);

  // Set Initial Status on DWIN (VP 0x601C = 10 -> MOUNT/Ready)
  isGasketMounted = false;
  DwinService::getInstance().writeVP(0x601C, 10); // Ready to Mount
  DwinService::getInstance().writeVP(0x5204, 0);  // Show Mount Button

  LOG_INFO(LogCategory::SENSOR,
           "Startup: Başlangıç durumu - Mount Butonu Gösteriliyor (0x5204=0).");

  // --- KULLANICI PIN DOĞRULAMA EKRANI ---
  // Önce 0x1194 adresini sıfırla (eski PIN verisini temizle)
  DwinService::getInstance().writeVP(0x1194, 0);
  // Kapatma sayacını sıfırla (açılışta kalıntı değer olmasın)
  DwinService::getInstance().writeVP(0x550A, 0);
  // Sayfa 14'e geç (bekleme sayfası - PIN listesi gelene kadar)
  DwinService::getInstance().changePage(14);
  userPinVerified = false;
  pinPageReady = false;
  LOG_INFO(LogCategory::CORE, "Bekleme sayfasına yönlendirildi (Sayfa 14, PIN listesi bekleniyor)");

  // ═══ FAST STREAM TIMER BAŞLAT (200ms / 5Hz — main loop'tan bağımsız) ═══
  {
    esp_timer_create_args_t timerArgs = {};
    timerArgs.callback = fastStreamTimerCallback;
    timerArgs.name = "fast_stream";
    esp_timer_create(&timerArgs, &fastStreamTimer);
    esp_timer_start_periodic(fastStreamTimer, 200000); // 200ms = 200000μs
    LOG_INFO(LogCategory::CORE, "Fast stream timer başlatıldı (200ms / 5Hz)");
  }
}

// DISMOUNT STATE
static bool isDismountInProgress = false;
static unsigned long dismountProcessStartTime = 0;
// Dismount Button (Inching)
static bool isDismountButtonPressed = false;
static unsigned long dismountButtonPressStartTime = 0;
static int dismountReleaseCounter = 0; // Tolerance counter for missed reads
static const unsigned long DISMOUNT_HOLD_TIME_MS = 5000;
static const unsigned long DISMOUNT_PROCESS_TIME_MS = 5000;

// Mount Button (Trigger)
static int mountTriggerCounter = 0;
static int mountWindowCounter = 0;
static bool isMountButtonPressed = false; // To prevent repeat triggers

static const unsigned long GASKET_MOUNT_DURATION_MS =
    5000; // 5 seconds for mounting (Unused variable kept for consistency)

// Global state for SD hot-swap
static bool isSdDetected = false;
static unsigned long lastSdCheck = 0;

void loop() {
  unsigned long now = millis();

  // ═══════════════════════════════════════════════════════════════════
  // OTA MODE - Priority High (Skip Normal Logic)
  // ═══════════════════════════════════════════════════════════════════
  if (isOTAModeActive) {
    // ── OTA MODE: Sistem donduruluyor ──
    // Flash yazımı sırasında UART/Timer kesmelerini minimize et
    ArduinoOTA.handle(); // OTA paketlerini işle

    // Ekranı ve butonları 250ms'de bir kontrol et (sayacı kaçırmamak için)
    static unsigned long lastOtaDwinCheck = 0;
    if (now - lastOtaDwinCheck > 250) {
      lastOtaDwinCheck = now;

      // ── KAPATMA TUŞU (VP 0x550A) — OTA'da da aktif ──
      // NOT: DwinService::update() çağırmadan SADECE readVP ile sayaç oku
      // Flash yazımı sırasında tam update() riskli, ama tek bir readVP güvenli
      uint16_t powerVal = DwinService::getInstance().readVP(0x550A);
      if (powerVal >= 8) {
        LOG_WARN(LogCategory::CORE, "OTA sırasında GÜÇ KESİLİYOR... (Sayaç: %d)", powerVal);
        DwinService::getInstance().writeVP(0x550A, 0);
        while (true) {
          digitalWrite(21, LOW); // Cut Power Latch
          delay(100);
        }
      } else if (powerVal > 0) {
        // Stagnation kontrolü yok — sadece threshold kontrol et
      }

      // TODO: OTA çıkış tuşu — şimdilik devre dışı, ileride eklenecek
      // uint16_t exitValue = DwinService::getInstance().readVP(0x5206);
      // if (exitValue >= 8) {
      //   LOG_INFO(LogCategory::CORE, "OTA modundan çıkılıyor...");
      //   stopOTAMode();
      //   DwinService::getInstance().writeVP(0x5206, 0);
      // }
    }

    // Heartbeat LED (show system is alive during OTA)
    static unsigned long lastOTAHeartbeat = 0;
    if (now - lastOTAHeartbeat > 200) {
      lastOTAHeartbeat = now;
      digitalWrite(Config::hardware.indicators.status_led,
                   !digitalRead(Config::hardware.indicators.status_led));
    }

    // FreeRTOS Watchdog'unu rahatlat
    vTaskDelay(pdMS_TO_TICKS(10));
    return; // Normal işlemleri atla
  }

  // ═══════════════════════════════════════════════════════════════════
  // NORMAL MODE - Standard Processing
  // ═══════════════════════════════════════════════════════════════════

  // ---------------- SERVICES UPDATE ----------------
  DwinService::getInstance().update(); // Enable polling & animation

  // ESP-NOW artık kendi FreeRTOS task'ında çalışıyor (update + send + recv dahil)

  // ═══ FAST STREAM artık esp_timer ile çalışıyor (main loop'tan bağımsız) ═══

  // ═══════════════════════════════════════════════════════════════════
  // KULLANICI PIN DOĞRULAMA (Sayfa 86 - PIN giriş ekranı)
  // ═══════════════════════════════════════════════════════════════════
  // PIN sayfasına geçiş: PIN listesi hazır olunca sayfa 91'e geç
  if (!userPinVerified && !pinPageReady) {
    if (espNowSlave && espNowSlave->getPinCount() > 0) {
      DwinService::getInstance().changePage(91);
      pinPageReady = true;
      LOG_INFO(LogCategory::CORE, "PIN listesi hazır (%d kullanıcı), sayfa 91'e geçildi",
               espNowSlave->getPinCount());
    }
    return; // PIN sayfası hazır değilse diğer işlemleri atla
  }

  if (now - lastPinCheckTime > PIN_CHECK_INTERVAL_MS) {
    lastPinCheckTime = now;
    uint16_t pinValue = DwinService::getInstance().readVP(0x1194);
    if (pinValue != 0) {
      lastActivityTime = now; // PIN girişi → inactivity sıfırla
      // PIN girilmiş, doğrulama yap
      char pinStr[8];
      snprintf(pinStr, sizeof(pinStr), "%d", pinValue);
      LOG_INFO(LogCategory::CORE, "PIN girişi algılandı: %s", pinStr);

      if (espNowSlave && espNowSlave->checkPin(pinStr)) {
        // PIN doğru - sayfa 2'ye geç
        userPinVerified = true;
        DwinService::getInstance().writeVP(0x1194, 0); // PIN alanını temizle
        DwinService::getInstance().changePage(2);
        LOG_INFO(LogCategory::CORE, "✅ PIN doğrulandı! Operatör: %s - Sayfa 2'ye geçiliyor",
                 espNowSlave->getActiveOperator());
      } else {
        // PIN yanlış - önce sayfa 14'e git (widget state temizle), sonra geri 91'e dön
        DwinService::getInstance().writeVP(0x1194, 0);
        DwinService::getInstance().changePage(14);
        delay(50);
        DwinService::getInstance().changePage(91);
        LOG_WARN(LogCategory::CORE, "❌ Yanlış PIN girişi: %s", pinStr);
      }
    }
    if (!userPinVerified) return; // PIN doğrulanana kadar diğer işlemleri atla
  }

  // ═══════════════════════════════════════════════════════════════════
  // POWER OFF LOGIC (VP 0x550A) — PIN doğrulamasından BAĞIMSIZ çalışır
  // ═══════════════════════════════════════════════════════════════════
  // - User presses button -> value incrementing (handled by display)
  // - If value >= 8 -> Power OFF
  // - If value stays same for > 2000ms (and != 0) -> Reset to 0
  {
    static unsigned long lastPowerCheck = 0;
    static uint16_t lastPowerValue = 0;
    static unsigned long lastValueChangeTime = 0;
    static int zeroGlitchCounter = 0;

    if (now - lastPowerCheck > 100) { // Check every 100ms
      lastPowerCheck = now;

      uint16_t rawValue = DwinService::getInstance().readVP(0x550A);
      uint16_t currentPowerValue = rawValue;

      // FILTER LOGIC: accept 0 only after 3 consecutive reads
      if (rawValue == 0 && lastPowerValue != 0) {
        zeroGlitchCounter++;
        if (zeroGlitchCounter < 3) {
          currentPowerValue = lastPowerValue;
        } else {
          currentPowerValue = 0;
          zeroGlitchCounter = 0;
        }
      } else {
        zeroGlitchCounter = 0;
        currentPowerValue = rawValue;
      }

      if (currentPowerValue != lastPowerValue) {
        lastPowerValue = currentPowerValue;
        lastValueChangeTime = now;
      }

      // 1. CHECK THRESHOLD (>= 8)
      if (currentPowerValue >= 8) {
        LOG_WARN(LogCategory::CORE, "GÜÇ KESİLİYOR... (Sayaç: %d)",
                 currentPowerValue);
        DwinService::getInstance().writeVP(0x550A, 0);
        while (true) {
          digitalWrite(21, LOW); // Cut Power Latch
          delay(100);
        }
      }
      // 2. CHECK STAGNATION (Timeout 2s)
      else if (currentPowerValue > 0) {
        lastActivityTime = now; // Kapanma butonuna dokunuldu → inactivity sıfırla
        if (now - lastValueChangeTime > 2000) {
          LOG_INFO(LogCategory::CORE,
                   "Kapanma Sayacı Zaman Aşımı. Sıfırlanıyor. (Değer: %d)",
                   currentPowerValue);
          DwinService::getInstance().writeVP(0x550A, 0);
          DwinService::getInstance().writeVP(0x550C, 0);
          lastPowerValue = 0;
        }
      }

      // 3. INACTIVITY AUTO-SHUTDOWN (5 dakika)
      // Sadece IDLE modda çalışır — test devam ederken kapanmaz
      // Test/mount/dismount sırasında sayaç sürekli sıfırlanır → uzun testler sonrası
      // IDLE'a dönüldüğünde anında kapanma yaşanmaz.
      if (currentTestState != TestState::IDLE || isMounting || isDismountInProgress) {
        lastActivityTime = now;
      }
      if (currentTestState == TestState::IDLE && !isMounting && !isDismountInProgress) {
        if (now - lastActivityTime > INACTIVITY_TIMEOUT_MS) {
          LOG_WARN(LogCategory::CORE, "⏰ 5 dakika hareketsizlik — GÜÇ KESİLİYOR...");
          DwinService::getInstance().writeVP(0x550A, 0);
          while (true) {
            digitalWrite(21, LOW); // Cut Power Latch
            delay(100);
          }
        }
      }
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  // DISMOUNT BUTTON READ & STAGNATION (VP 0x5202) — Power Off gibi bağımsız
  // ═══════════════════════════════════════════════════════════════════
  // - User holds button -> value incrementing (handled by display)
  // - If value >= 8 -> Set shouldTriggerDismount flag
  // - If value stays same for > 2000ms (and != 0) -> Reset to 0
  if (!isDismountInProgress) {
    static unsigned long lastDismountReadCheck = 0;
    static uint16_t lastDismountValue = 0;
    static unsigned long lastDismountChangeTime = 0;
    static int dismountZeroGlitchCounter = 0;

    if (now - lastDismountReadCheck > 100) { // Check every 100ms
      lastDismountReadCheck = now;

      uint16_t rawDismount = DwinService::getInstance().readVP(0x5202);
      uint16_t currentDismountValue = rawDismount;

      // FILTER LOGIC: accept 0 only after 3 consecutive reads
      if (rawDismount == 0 && lastDismountValue != 0) {
        dismountZeroGlitchCounter++;
        if (dismountZeroGlitchCounter < 3) {
          currentDismountValue = lastDismountValue; // Ignore glitch
        } else {
          currentDismountValue = 0; // Confirmed 0
          dismountZeroGlitchCounter = 0;
        }
      } else {
        dismountZeroGlitchCounter = 0;
        currentDismountValue = rawDismount;
      }

      if (currentDismountValue != lastDismountValue) {
        lastActivityTime = now; // Dismount butonuna dokunuldu → inactivity sıfırla
        lastDismountValue = currentDismountValue;
        lastDismountChangeTime = now;
      }

      // 1. CHECK THRESHOLD (>= 8)
      if (currentDismountValue >= 8) {
        LOG_INFO(LogCategory::SENSOR, "Dismount buton eşiğe ulaştı (Değer: %d)", currentDismountValue);
        shouldTriggerDismount = true;
        DwinService::getInstance().writeVP(0x5202, 0);
        lastDismountValue = 0;
      }
      // 2. CHECK STAGNATION (Timeout 2s)
      else if (currentDismountValue > 0) {
        if (now - lastDismountChangeTime > 2000) {
          LOG_INFO(LogCategory::SENSOR,
                   "Dismount Zaman Aşımı. Sıfırlanıyor. (Değer: %d)",
                   currentDismountValue);
          DwinService::getInstance().writeVP(0x5202, 0);
          lastDismountValue = 0;
          lastDismountChangeTime = now; // Prevent repeated timeout logs
        }
      }
    }
  }

  BatteryService::getInstance().update(); // PIN'den bağımsız — stream batarya verisi için

  if (!userPinVerified) return; // PIN doğrulanmadıysa loop'u atla

  if (rfidService && currentTestState == TestState::IDLE &&
      rfidReadingEnabled && currentUartMode == UartMode::RFID) {
    rfidService->update();

    uint32_t currentTag = rfidService->getLastDetectedTag();
    static uint32_t lastDwinTag =
        0xFFFFFFFF; // Initialize with value that won't match 0 or real tags

    // DWIN RFID ACTIONS (User Request: 5300 for Port, 601A for Status 53)
    // RFID tag değiştiğinde çok sayıda LOG mesajı ESP-NOW'a gider → main loop bloklanır
    // suppressRemoteLog ile engelliyoruz
    if (currentTag != lastDwinTag) {
      suppressRemoteLog = true;
      lastDwinTag = currentTag;
      if (currentTag != 0) {
        lastActivityTime = millis(); // RFID tag algılandı → inactivity sıfırla
        bool isAuthorized = rfidService->isTagAuthorized(currentTag);
        if (isAuthorized) {
          uint16_t port = rfidService->getTagPort(currentTag);
          // --- RFID LIVE GÜNCELLE ---
          rfid_live = currentTag;
          rfid_live_port = port;
          rfid_live_recipe = rfidService->getTagRecipe(currentTag);

          dwinWritePort(port);
          DwinService::getInstance().writeVP(0x601A, 53);

          // Clear 75 if authorized tag is placed
          isWarning75Active = false;

          // Draw "RFID OK" text in cyan
          DwinService::getInstance().drawString(10, 10, 0x34, 0x07FF, 0x0000,
                                                "RFID OK");

          // CRITICAL: Load recipe into activeTestRecipe so it's available when
          // test starts
          activeTestRecipe = rfid_live_recipe;

          LOG_INFO(LogCategory::RFID,
                   "Tanınan RFID: Port %d yazıldı. (0x601A=53)", port);
          LOG_INFO(LogCategory::RFID,
                   "═══════════════════════════════════════");
          LOG_INFO(LogCategory::RFID, "  RFID: 0x%08X | Port: %d", currentTag,
                   port);

          if (rfid_live_recipe.inflationPascal == 0) {
            LOG_WARN(LogCategory::RFID,
                     "───────────────────────────────────────");
            LOG_WARN(LogCategory::RFID, "  ❌ TEST PARAMETRELERİ BULUNAMADI!");
            LOG_WARN(LogCategory::RFID, "  Bu RFID için recipe tanımlanmamış.");
            LOG_WARN(LogCategory::RFID,
                     "  Test başlatılamaz - Python'dan recipe atayın.");
          } else {
            LOG_INFO(LogCategory::RFID,
                     "───────────────────────────────────────");
            LOG_INFO(LogCategory::RFID, "  ✅ Recipe: %s",
                     rfid_live_recipe.recipeName);
            LOG_INFO(LogCategory::RFID, "  P1 - Şişirme Max Süre    : %d sn",
                     rfid_live_recipe.inflationMaxTime);
            LOG_INFO(LogCategory::RFID, "  P2 - Hedef Basınç        : %d Pa",
                     rfid_live_recipe.inflationPascal);
            LOG_INFO(LogCategory::RFID, "  P3 - Dengeleme Süresi    : %d sn",
                     rfid_live_recipe.stabilizationTime);
            LOG_INFO(LogCategory::RFID, "  P4 - Yeniden Şişirme Eşik: %d Pa",
                     rfid_live_recipe.reinflateThreshold);
            LOG_INFO(LogCategory::RFID, "  P6 - Fail Threshold      : %d Pa",
                     rfid_live_recipe.failThreshold);
            LOG_INFO(LogCategory::RFID, "  P7 - Test Süresi         : %d sn",
                     rfid_live_recipe.testDuration);
            LOG_INFO(LogCategory::RFID, "  P8 - Başarı Düşüş Limiti : %d Pa",
                     rfid_live_recipe.successDropPascal);

            // Write ALL recipe parameters to DWIN screen (user can edit them
            // before test)
            DwinService::getInstance().writeVP(
                0x5501,
                rfid_live_recipe.inflationMaxTime); // P1 - Şişirme Max Süre
            DwinService::getInstance().writeVP(
                0x5503, rfid_live_recipe.inflationPascal); // P2 - Hedef Basınç
            DwinService::getInstance().writeVP(
                0x5504,
                rfid_live_recipe.stabilizationTime); // P3 - Dengeleme Süresi
            DwinService::getInstance().writeVP(
                0x5505, rfid_live_recipe.failThreshold); // P6 - Fail Threshold
            DwinService::getInstance().writeVP(
                0x5506,
                rfid_live_recipe.successDropPascal); // P8 - Başarı Düşüş Limiti
            DwinService::getInstance().writeVP(
                0x5507, rfid_live_recipe.testDuration); // P7 - Test Süresi
            DwinService::getInstance().writeVP(
                0x5512, rfid_live_recipe.failThreshold); // P6 - Kabul Edilebilir Basınç Düşümü
            DwinService::getInstance().writeVP(
                0x5510, rfid_live_recipe.successDropPascal); // P8 - Kritik Basınç Sınırı
            DwinService::getInstance().writeVP(
                0x5516, rfid_live_recipe.reinflateThreshold); // P4 - Yeniden Şişirme Eşiği
            LOG_INFO(
                LogCategory::RFID,
                "  DWIN'e yazıldı: Basınç=%d, Dengeleme=%d, Test Süresi=%d sn, KabulEsik=%d, KritikSinir=%d, ReinflEsik=%d",
                rfid_live_recipe.inflationPascal,
                rfid_live_recipe.stabilizationTime,
                rfid_live_recipe.testDuration,
                rfid_live_recipe.failThreshold,
                rfid_live_recipe.successDropPascal,
                rfid_live_recipe.reinflateThreshold);
          }
          LOG_INFO(LogCategory::RFID,
                   "═══════════════════════════════════════");
        } else {
          dwinWritePort(0);
          DwinService::getInstance().writeVP(0x601A, 53);

          // Draw "NO AUTH" text in red
          DwinService::getInstance().drawString(10, 10, 0x34, 0xF800, 0x0000,
                                                "NO AUTH");

          // TRIGGER WARNING 75 (Unauthorized Tag Present)
          isWarning75Active = true;
          LOG_WARN(
              LogCategory::RFID,
              "Tanınmayan RFID: 5300=0, 601A=53, 601B=75 (pending) yazıldı.");
        }
      } else {
        // Tag removed / Etiket yok - SADECE rfid_live temizle (rfid_latched'a
        // DOKUNMA!)
        rfid_live = 0;
        rfid_live_port = 0;
        DwinService::getInstance().writeVP(0x601A, 0); // Clear RFID icon
        dwinWritePort(0); // Clear port display
        isWarning75Active = false;
        LOG_INFO(LogCategory::RFID, "RFID Ayrıldı: rfid_live temizlendi.");
      }
      suppressRemoteLog = false;
    }

    // Visual feedback (LED 41 or LED 42 based on config)
    if (currentTag != 0) {
      bool isAuthorized = rfidService->isTagAuthorized(currentTag);
      digitalWrite(
          41, isAuthorized ? HIGH : (now % 500 < 250)); // Blink if unauthorized
    } else {
      digitalWrite(41, LOW);
    }
  }

  // ═══ BASINC SERVİSİ DWIN GÜNCELLEME (FreeRTOS task okur, biz sadece ekrana yazarız) ═══
  if (pressureService && currentUartMode == UartMode::MODBUS) {
    // update() artık FreeRTOS task tarafından çağrılıyor - burada çağırmayoruz
    // DWIN ekranına raw basınç verisi yaz - SADECE sensör bağlıysa
    static unsigned long lastDwinUpdate = 0;
    if (millis() - lastDwinUpdate > 50) {
      lastDwinUpdate = millis();
      if (pressureService->isConnected()) {
        DwinService::getInstance().updatePressure(
            pressureService->getRawValue(), pressureService->getPressure());
      }
    }
  }

  // ═══ IDLE PERİYODİK BASINÇ OKUMA (~35ms bloklayıcı, 10 sn'de bir) ═══
  // RFID kapatılır → Serial1 Modbus pinleriyle açılır → tek seferlik basınç
  // okunur → Serial1 kapatılır → RFID tekrar açılır.
  // PressureService FreeRTOS task'ı IDLE'da taskActive_==false olduğu için
  // Core 0'dan müdahale gelmez — sadece updateBlocking() ile tek okuma yapılır.
  // FIX: Sadece conta İNİK (Mount Edilmemiş) ise periyodik okumasını yap.
  // Conta şişikken Modbus zaten sürekli aktif — araya girip RFID'ye geçmek
  // currentUartMode'u bozar ve sonraki switchUart(MODBUS) çağrısı NOP olur.
  if (currentTestState == TestState::IDLE && !isGasketMounted && !isMounting &&
      !isDismountInProgress) {
    if (now - lastIdlePressureRead > IDLE_PRESSURE_INTERVAL_MS) {
      lastIdlePressureRead = now;
      suppressRemoteLog = true;

      // 1. RFID kapat — Serial1.flush() + Serial1.end()
      if (rfidReader) rfidReader->end();
      delay(2);

      // 2. Serial1'i Modbus pinleriyle aç
      Serial1.begin(Config::hardware.modbus_pressure.baud, SERIAL_8N1,
                    Config::hardware.modbus_pressure.rx,
                    Config::hardware.modbus_pressure.tx);
      delay(2);

      // 3. Hafif başlatma (task aktif edilmez, sadece pointer set)
      if (pressureService) {
        pressureService->beginQuick();
        pressureService->updateBlocking(); // uartMutex_ ile korunuyor
        idlePressureValue = pressureService->getPressure();
        pressureService->endQuick();
      }

      // 4. Serial1'i kapat, RFID'ye geri dön
      Serial1.flush();
      Serial1.end();
      delay(2);
      if (rfidReader) {
        rfidReader->begin(Config::hardware.rfid.rx,
                          Config::hardware.rfid.uart_num);
      }
      if (rfidService) rfidService->resetTimeout();
      suppressRemoteLog = false;

      // DWIN ekranında IDLE basınç değerini göster
      if (idlePressureValue > 0) {
        DwinService::getInstance().updatePressure(0, idlePressureValue);
      }
    }
  }

  if (gasketService) {
    gasketService->update();
    // DWIN ekran güncelleme (50ms throttled)
    // Main loop içinde zaten 50ms timer var (yukarıda PressureService için).
    // Onu buraya da uygulayalım veya gasket için ayrı timer yapalım?
    // Yukarıdaki timer sadece PressureService içindi ve local static variable.
    // Burada tekrar timer kullanalım.

    static unsigned long lastGasketDwin = 0;
    if (millis() - lastGasketDwin >
        100) { // Conta basıncı çok hızlı değişmez, 100ms yeterli
      lastGasketDwin = millis();
      // 0x7006 (Raw) ve 0x7008 (Calibrated)
      DwinService::getInstance().updateGasket(
          gasketService->getRawValue(), (uint16_t)gasketService->getPressure());
    }
  }

  // espNowSlave->update() artık ESP-NOW FreeRTOS task içinde çalışıyor
  DwinService::getInstance().update(); // Handles animation & button polling
  if (debugInterface)
    debugInterface->update();
  RtcService::getInstance().update();

  // ---------------- STATUS LED (HEARTBEAT) ----------------
  static unsigned long lastHeartbeat = 0;
  if (now - lastHeartbeat > 1000) { // 1 Hz (500ms ON, 500ms OFF) - Wait, user
                                    // asked for "Düzenli" (Regular)
    lastHeartbeat = now;
    digitalWrite(Config::hardware.indicators.status_led,
                 !digitalRead(Config::hardware.indicators.status_led));
  }

  // ---------------- STATUS & SD LOGIC ----------------
  // Check Status every 1 second
  static unsigned long lastStatusUpdate = 0;
  if (now - lastStatusUpdate > 1000) {
    lastStatusUpdate = now;

    // 1. RTC Time Update
    // 1. RTC Time Update (Handled by RtcService::update())
    // if (rtc) { ... } removed

    // 2. ESP-NOW Status Update
    // 24 (Connected), 25 (Off/Error), 26 (On but Disconnected)
    int espNowVal = 25; // Default: Off
    if (espNowSlave && espNowSlave->isInitialized()) {
      espNowVal = espNowSlave->isConnected() ? 24 : 26;
    }
    DwinService::getInstance().updateESPNowStatus(espNowVal);

    // 3. DWIN Connection Icon (0x6011)
    DwinService::getInstance().writeVP(0x6011, espNowVal);

    // 4. DWIN Storage Icon (0x6012)
    uint16_t testCount = TestStorageService::getInstance().getTestCount();
    uint16_t storageIcon = 0;
    if (testCount >= 10) storageIcon = 31;
    else if (testCount > 0) storageIcon = 30;
    DwinService::getInstance().writeVP(0x6012, storageIcon);
  }

  // 3. SD Card Hot-Swap Logic (every 2 seconds to avoid blocking too often if
  // missing)
  if (now - lastSdCheck > 2000) {
    lastSdCheck = now;

    if (isSdDetected) {
      // Check if still alive
      if (SD_MMC.cardType() == CARD_NONE) {
        LOG_WARN(LogCategory::CORE, "SD Kart Çıkarıldı (veya okuma hatası)");
        SD_MMC.end();
        isSdDetected = false;
        DwinService::getInstance().updateSDStatus(false); // Send 31
      } else {
        // Ensure "30" is shown (idempotent)
        DwinService::getInstance().updateSDStatus(true);
      }
    } else {
      // SD Kart periodic check devre dışı (log spam önleme)
      // Kullanıcı manuel olarak DWIN'den görebilir
      /*
      if (SD_MMC.begin("/sd", true)) {
          LOG_INFO(LogCategory::CORE, "SD Kart Takıldı/Algılandı. Size: %llu
      MB", SD_MMC.cardSize() / (1024*1024)); isSdDetected = true;
          DwinService::getInstance().updateSDStatus(true); // Send 30
      } else {
          // Update DWIN 31 (Removed)
          DwinService::getInstance().updateSDStatus(false);
      }
      */
    }
  }

  // ---------------- GASKET MOUNT LOGIC ----------------
  static unsigned long lastMountCheck = 0;

  // 1. HANDLE DISMOUNT PROCESS (Priority High)
  if (isDismountInProgress) {
    // Check if process finished (5s)
    if (now - dismountProcessStartTime > DISMOUNT_PROCESS_TIME_MS) {
      LOG_INFO(LogCategory::SENSOR,
               "Dismount İŞLEMİ TAMAMLANDI. Tüm Valfler KAPALI.");

      // Close All
      digitalWrite(Config::hardware.relays.conta_solenoid, LOW); // Pin 1
      digitalWrite(Config::hardware.relays.pump_motor, LOW); // Pin 2 (Safety)
      digitalWrite(Config::hardware.relays.drain_solenoid, LOW); // Pin 4

      // Return to MOUNT (Ready)
      DwinService::getInstance().writeVP(0x601C, 10);

      // PRESERVE RFID INFO after dismount (using latched values)
      if (rfid_latched_port > 0) {
        dwinWritePort(rfid_latched_port);
      }
      DwinService::getInstance().writeVP(0x601A, rfid_live != 0 ? 53 : 0);

      // CRITICAL: Clear any pending MOUNT command (VP 5204) that might have
      // occurred during dismount
      DwinService::getInstance().writeVP(0x5204, 0);

      isDismountInProgress = false;
      isMounting = false;      // Ensure mounting flag is cleared
      isGasketMounted = false; // Mark as unmounted
      dismountRequired = false; // Dismount yapıldı, mount/test start tekrar aktif

      // CLEAR LATCHED RFID (dismount = mount bitti, latched artık geçersiz)
      rfid_latched = 0;
      rfid_latched_port = 0;

      // UNLOCK RFID after dismount - ready for new mount
      rfidReadingEnabled = true;
      LOG_INFO(
          LogCategory::RFID,
          "Dismount tamamlandı - RFID kilidi açıldı, rfid_latched temizlendi");

      // NOTIFY PC: Unmount completed
      if (espNowSlave && espNowSlave->isInitialized()) {
        char unmountBuf[128];
        int unmountLen = snprintf(unmountBuf, sizeof(unmountBuf),
            "{\"cmd\":\"UNMOUNT\",\"device\":\"TestAparati\",\"battery\":%d,\"glove_pressure\":%d}",
            BatteryService::getInstance().getPercentage(),
            pressureService ? (int)pressureService->getPressure() : 0);
        (void)unmountLen;
        espNowSlave->sendToMaster(unmountBuf);
        LOG_INFO(LogCategory::CORE, "Unmount PC'ye bildirildi");
      }

      // Timer reset is automatic because if isDismountInProgress was true, we
      // didn't check button
    }
    // WHILE Active: Ignore Mount/Dismount buttons.
    // FORCE VP 0x5202 to 0 (USER REQUEST: "Dismount yapıldığı sürece 0'da tut")
    static unsigned long lastDismountForceTime = 0;
    if (now - lastDismountForceTime > 200) {
      lastDismountForceTime = now;
      DwinService::getInstance().writeVP(0x5202, 0);
    }
  } else {
    // 2. NORMAL OPERATION (Check Buttons every 50ms for high responsiveness &
    // debounce)
    if (now - lastMountCheck > 50) {
      lastMountCheck = now;

      // --- 0. CHECK WARNING PRIORITIES (0x601B) ---
      // 1. Warning 74 (Unauthorized Mount Press) - Highest Priority, 3s Timeout
      if (isWarning74Active) {
        if (now - warning74StartTime > 3000) {
          isWarning74Active = false;
        } else {
          DwinService::getInstance().writeVP(0x601B, 74);
        }
      }

      // 2. Warning 75 (Unauthorized Tag Present) - Persistent while tag is
      // there
      if (!isWarning74Active) {
        if (isWarning75Active) {
          DwinService::getInstance().writeVP(0x601B, 75);
        }
        // 3. Warning 77 (Mount Timeout) - 15s Timer
        else if (isWarning77Active) {
          // Timer logic already at line 636, let's just use the flag here
          DwinService::getInstance().writeVP(0x601B, 77);
        }
        // 4. Warning 78 (Battery Low) - Managed below but we check flag here
        else {
          // Low battery check is below, let it handle the write
        }
      }

      // v*100 <= 1300 (Low threshold for testing)
      bool isBatteryCurrentlyLow =
          (BatteryService::getInstance().getVoltage() * 100.0f <= 1300.0f);

      // Handle 77 Timer
      if (isWarning77Active) {
        if (now - warning77StartTime > 15000) {
          isWarning77Active = false;
        }
      }

      // Battery display logic
      if (!isWarning74Active && !isWarning75Active && !isWarning77Active) {
        if (isBatteryCurrentlyLow) {
          if (isMountButtonPressed) {
            if (now - lastBatteryFlashTime > 500) {
              lastBatteryFlashTime = now;
              batteryFlashState = !batteryFlashState;
              DwinService::getInstance().writeVP(0x601B,
                                                 batteryFlashState ? 78 : 0);
            }
          } else {
            DwinService::getInstance().writeVP(0x601B, 78);
          }
        } else {
          DwinService::getInstance().writeVP(0x601B, 0);
        }
      }

      // --- A. CHECK DISMOUNT TRIGGER (VP 5202 artık üst blokta okunuyor) ---
      if (shouldTriggerDismount) {
        shouldTriggerDismount = false; // Reset remote flag
        LOG_INFO(LogCategory::SENSOR, "Dismount BAŞLATILIYOR");

        // ACTION:
        // 1. Stop Pump
        digitalWrite(Config::hardware.relays.pump_motor, LOW);
        // 1.1 Close Glove Solenoid
        digitalWrite(Config::hardware.relays.glove_solenoid, LOW);

        // 2. Open Drain (Pin 4) & Gasket (Pin 1)
        digitalWrite(Config::hardware.relays.conta_solenoid, HIGH);
        digitalWrite(Config::hardware.relays.drain_solenoid, HIGH);

        // 3. Screen WAIT (9)
        DwinService::getInstance().writeVP(0x601C, 9);

        // 4. Start Process Timer
        isDismountInProgress = true;
        dismountProcessStartTime = now;

        // RFID RESUME: Switch back to RFID mode
        switchUart(UartMode::RFID);
        currentTestState = TestState::IDLE;

        // CLEAR LATCHED RFID (dismount = mount bitti, latched artık geçersiz)
        rfid_latched = 0;
        rfid_latched_port = 0;
        activeTestRecipe = TestRecipe(); // Clear recipe on dismount
        // FIX: Reset timing variables so next mount starts clean
        mountStartTime = 0;
        testTotalStartTime = 0;

        // UNLOCK RFID after dismount - ready for new mount
        rfidReadingEnabled = true;
        LOG_INFO(LogCategory::RFID, "Dismount tamamlandı - RFID kilidi açıldı, "
                                    "rfid_latched temizlendi");

        // 5. Reset & Cleanup
        DwinService::getInstance().writeVP(0x5202, 0); // Reset Button
        DwinService::getInstance().writeVP(0x5204, 0); // Clear Mount
        DwinService::getInstance().writeVP(0x700D,
                                           0); // Clear Countdown (if used)
        isDismountButtonPressed = false;
        dismountRequired = false; // Dismount yapıldı, mount/test start tekrar aktif
      }

      // --- B. CHECK OTA BUTTON (VP 0x5206) ---
      // Similar Logic to Dismount: Increment Based
      // - User holds button -> Value increments
      // - If value >= 8 -> Start OTA Mode
      // - If value stays same for > 2000ms -> Reset to 0

      // Skip OTA check if already in OTA mode (handle separately below)
      if (!isOTAModeActive) {
        // 1. Read & Filter
        uint16_t rawOTA = DwinService::getInstance().readVP(0x5206);
        uint16_t currentOTAValue = rawOTA;

        if (rawOTA == 0 && lastOTAButtonValue != 0) {
          otaZeroGlitchCounter++;
          if (otaZeroGlitchCounter < 3) {
            currentOTAValue = lastOTAButtonValue; // Ignore glitch
          } else {
            currentOTAValue = 0; // Confirmed 0
            otaZeroGlitchCounter = 0;
          }
        } else {
          otaZeroGlitchCounter = 0;
          currentOTAValue = rawOTA;
        }

        // 2. Track Changes (Stagnation Timer)
        if (currentOTAValue != lastOTAButtonValue) {
          lastActivityTime = now; // OTA butonuna dokunuldu → inactivity sıfırla
          lastOTAButtonValue = currentOTAValue;
          lastOTAButtonChangeTime = now;
        }

        // 3. Logic
        if (currentOTAValue >= 8) {
          LOG_INFO(LogCategory::CORE, "OTA MODU TETIKLENDI! (Sayaç: %d)",
                   currentOTAValue);

          // Start OTA Mode
          startOTAMode();

          // Reset Button VP
          DwinService::getInstance().writeVP(0x5206, 0);
          lastOTAButtonValue = 0;

        } else if (currentOTAValue > 0) {
          // Check Stagnation (2s Timeout)
          if (now - lastOTAButtonChangeTime > 2000) {
            LOG_INFO(LogCategory::CORE,
                     "OTA tuşu zaman aşımı. Sıfırlanıyor. (Değer: %d)",
                     currentOTAValue);
            DwinService::getInstance().writeVP(0x5206, 0);
            lastOTAButtonValue = 0;
            lastOTAButtonChangeTime = now; // Prevent repeated timeout logs
          }
        }
      }

      // --- MOUNT SUCCESS: Wait 2s before showing Test Start button ---
      if (mountSuccessWaitingForButton) {
        if (millis() - mountSuccessTime >= 2000) {
          // 2 seconds passed, show test start button
          DwinService::getInstance().writeVP(0x5204, 2);

          // PRESERVE RFID INFO when showing test start button (latched)
          if (rfid_latched_port > 0) {
            dwinWritePort(rfid_latched_port);
          }
          DwinService::getInstance().writeVP(0x601A,
                                             rfid_latched != 0 ? 53 : 0);

          mountSuccessWaitingForButton = false;
          LOG_INFO(LogCategory::SENSOR,
                   "Test Start Butonu Hazır (2s delay sonrası).");
        }
      }

      // --- TEST ABORT BUTTON (VP 0x7006) ---
      // Similar to dismount: When value >= 8, abort test and return to page 2
      // as FAIL
      // - If value stays same for > 2000ms -> Reset to 0
      // DEBUG: Check loop frequency
      static unsigned long lastAbortCheckTime = 0;
      static unsigned long abortCheckCount = 0;
      static unsigned long lastAbortFreqLog = 0;

      // IDLE state: Simple page navigation on abort (no test interruption
      // needed)
      if (currentTestState == TestState::IDLE) {
        uint16_t rawAbort = DwinService::getInstance().readVP(0x7006);
        if (rawAbort >= 8 || shouldTriggerAbort) {
          lastActivityTime = now; // Abort butonuna basıldı → inactivity sıfırla
          shouldTriggerAbort = false; // Reset flag
          LOG_INFO(LogCategory::CORE,
                   "Abort tuşu (IDLE): Ana ekrana dönülüyor...");
          DwinService::getInstance().changePage(2);
          DwinService::getInstance().writeVP(0x7006, 0); // Reset button

          // Preserve RFID info (live - IDLE modundayız, latched olmayabilir)
          if (rfid_live_port > 0) {
            dwinWritePort(rfid_live_port);
          }
          DwinService::getInstance().writeVP(0x601A, rfid_live != 0 ? 53 : 0);
        }
      }
      // Active test states: Full abort procedure (FINISHED hariç — basınç düşene kadar abort engelli)
      else if (currentTestState != TestState::MOUNTING_GASKET && currentTestState != TestState::FINISHED) {
        static uint16_t lastAbortValue = 0;
        static unsigned long lastAbortChangeTime = 0;
        static int abortZeroGlitchCounter = 0;

        // DEBUG: Log check frequency every 5 seconds
        abortCheckCount++;
        if (now - lastAbortFreqLog > 5000) {
          unsigned long freq = abortCheckCount / 5;
          LOG_INFO(LogCategory::CORE, "⏱️ Abort kontrol frekansı: %lu/sn", freq);
          abortCheckCount = 0;
          lastAbortFreqLog = now;
        }

        // 1. Read & Filter
        uint16_t rawAbort = DwinService::getInstance().readVP(0x7006);
        uint16_t currentAbortValue = rawAbort;

        // DEBUG: Log if abort button is pressed
        if (rawAbort > 0) {
          LOG_INFO(LogCategory::CORE, "🔴 ABORT VP okuması: %d (State: %d)",
                   rawAbort, (int)currentTestState);
        }

        if (rawAbort == 0 && lastAbortValue != 0) {
          abortZeroGlitchCounter++;
          if (abortZeroGlitchCounter < 3) {
            currentAbortValue = lastAbortValue; // Ignore glitch
          } else {
            currentAbortValue = 0; // Confirmed 0
            abortZeroGlitchCounter = 0;
          }
        } else {
          abortZeroGlitchCounter = 0;
          currentAbortValue = rawAbort;
        }

        // 2. Track Changes (Stagnation Timer)
        if (currentAbortValue != lastAbortValue) {
          lastAbortValue = currentAbortValue;
          lastAbortChangeTime = now;
        }

        // 3. Logic
        if (currentAbortValue >= 8 || shouldTriggerAbort) {
          shouldTriggerAbort = false; // Reset flag
          LOG_WARN(LogCategory::CORE, "TEST ABORT! (VP 0x7006 = %d)",
                   currentAbortValue);

          // 1. Stop all hardware
          digitalWrite(Config::hardware.relays.pump_motor, LOW);
          digitalWrite(Config::hardware.relays.glove_solenoid, LOW);
          // Dismount yapılMIYOR: conta ve drain solenoidleri açılmıyor
          // digitalWrite(Config::hardware.relays.conta_solenoid, HIGH);
          // digitalWrite(Config::hardware.relays.drain_solenoid, HIGH);

          // 2. Reset state
          currentTestState = TestState::IDLE;
          isMounting = false;
          // isGasketMounted korunuyor — conta hâlâ takılı
          // isGasketMounted = false;

          // Write ABORT result code (0x8018 = 11)
          DwinService::getInstance().writeVP(0x8018, 11);
          LOG_INFO(LogCategory::CORE, "═══ TEST ABORT (0x8018=11) ═══");

          // UNLOCK RFID after abort - ready for new mount
          rfidReadingEnabled = true;
          LOG_INFO(LogCategory::RFID, "Test abort - RFID kilidi açıldı");

          // ═══════════════════════════════════════════════════════════
          // ABORT KAYIT: Flash'a kaydet (tüm testler ESP tarafında saklanır)
          // ═══════════════════════════════════════════════════════════
          uint32_t abortSavedTestId = 0;
          {
            uint16_t abortDurationSec = (testTotalStartTime > 0)
                                        ? (uint16_t)((millis() - testTotalStartTime) / 1000)
                                        : 0;
            int16_t abortEndPressure = pressureService ? (int16_t)pressureService->getPressure() : 0;
            int16_t abortTotalDrop = (int16_t)((int32_t)testStartPressure - (int32_t)abortEndPressure);

            TestRecordHeader rec;
            memset(&rec, 0, sizeof(rec));
            rec.rfidTag = rfid_latched;
            rec.portNumber = rfid_latched_port;

            if (espNowSlave) {
              strncpy(rec.operatorName, espNowSlave->getActiveOperator(), sizeof(rec.operatorName) - 1);
            }
            strncpy(rec.recipeName, activeTestRecipe.recipeName, sizeof(rec.recipeName) - 1);

            RtcService& rtcAbort = RtcService::getInstance();
            rec.startYear   = (uint8_t)rtcAbort.getYear();
            rec.startMonth  = (uint8_t)rtcAbort.getMonth();
            rec.startDay    = (uint8_t)rtcAbort.getDay();
            rec.startHour   = (uint8_t)rtcAbort.getHour();
            rec.startMinute = (uint8_t)rtcAbort.getMinute();
            rec.startSecond = (uint8_t)rtcAbort.getSecond();

            rec.durationSec      = abortDurationSec;
            rec.startPressure    = (int16_t)testStartPressure;
            rec.endPressure      = abortEndPressure;
            rec.maxPressure      = testRecordMaxPressure;
            rec.totalDrop        = abortTotalDrop;
            rec.windowDrop       = 0; // Abort sırasında pencere düşüşü anlamlı değil
            rec.targetPressure   = (int16_t)activeTestRecipe.inflationPascal;
            rec.acceptableDrop   = (int16_t)activeTestRecipe.failThreshold;
            rec.criticalDrop     = (int16_t)activeTestRecipe.successDropPascal;
            rec.windowSize       = (int16_t)(activeTestRecipe.testDuration > 0 ? activeTestRecipe.testDuration : 30);
            rec.inflationMaxTime = (int16_t)activeTestRecipe.inflationMaxTime;
            rec.stabilizationTime = (int16_t)activeTestRecipe.stabilizationTime;
            rec.reinflateThreshold = (int16_t)activeTestRecipe.reinflateThreshold;
            rec.passed      = 0; // FAIL
            rec.failReason  = (uint8_t)TestFailReason::ABORTED;

            abortSavedTestId = TestStorageService::getInstance().saveTest(
                rec, testRecordSamples, testRecordSampleCount);

            if (abortSavedTestId > 0) {
              LOG_INFO(LogCategory::CORE, "ABORT Test #%lu Flash'a kaydedildi [%d/%d]",
                       abortSavedTestId, TestStorageService::getInstance().getTestCount(),
                       MAX_STORED_TESTS);
            } else {
              LOG_WARN(LogCategory::CORE, "ABORT Test Flash'a kaydedilemedi!");
            }
          }

          // NOTIFY PC: Test aborted
          if (espNowSlave && espNowSlave->isInitialized()) {
            char abortBuf[160];
            snprintf(abortBuf, sizeof(abortBuf),
                "{\"cmd\":\"TEST_ABORTED\",\"device\":\"TestAparati\",\"battery\":%d,\"glove_pressure\":%d,\"tid\":%lu}",
                BatteryService::getInstance().getPercentage(),
                pressureService ? (int)pressureService->getPressure() : 0,
                abortSavedTestId);
            espNowSlave->sendToMaster(abortBuf);
          }

          // 3. Return to page 2 (test screen) as FAIL
          DwinService::getInstance().changePage(2);
          DwinService::getInstance().writeVP(0x601C, 10); // Ready status
          DwinService::getInstance().writeVP(0x5204, 0);  // Show mount button

          // PRESERVE RFID INFO after abort (latched)
          if (rfid_latched_port > 0) {
            dwinWritePort(rfid_latched_port);
          }
          DwinService::getInstance().writeVP(0x601A,
                                             rfid_latched != 0 ? 53 : 0);

          // CLEAR LATCHED RFID
          rfid_latched = 0;
          rfid_latched_port = 0;

          // 4. Switch back to RFID
          switchUart(UartMode::RFID);

          // 5. Reset button VP
          DwinService::getInstance().writeVP(0x7006, 0);
          lastAbortValue = 0;

          LOG_INFO(LogCategory::CORE,
                   "Test iptal edildi. Sayfa 2'ye dönüldü (FAIL).");
        } else if (currentAbortValue > 0) {
          // Check Stagnation (2s Timeout)
          if (now - lastAbortChangeTime > 2000) {
            LOG_INFO(LogCategory::CORE,
                     "Abort tuşu zaman aşımı. Sıfırlanıyor. (Değer: %d)",
                     currentAbortValue);
            DwinService::getInstance().writeVP(0x7006, 0);
            lastAbortValue = 0;
            lastAbortChangeTime = now; // Prevent repeated timeout logs
          }
        }
      }

      // --- B. CHECK BUTTON VP 0x5204 (Context-aware: MOUNT or TEST START) ---
      uint16_t buttonCmd = DwinService::getInstance().readVP(0x5204);
      if (buttonCmd != 0) lastActivityTime = now; // Herhangi bir buton komutu → inactivity sıfırla

      // DISMOUNT REQUIRED GUARD: Test bittiyse dismount yapılana kadar mount/test start engelle
      if (dismountRequired && buttonCmd != 0) {
        DwinService::getInstance().writeVP(0x5204, 0); // Butonu sıfırla
        LOG_INFO(LogCategory::CORE, "Mount/Test Start engellendi — önce Dismount yapılmalı");
        buttonCmd = 0; // İşleme alma
      }

      // PRIORITY 1: If gasket is mounted and IDLE → Check for TEST START (value
      // == 3)
      if (isGasketMounted && currentTestState == TestState::IDLE) {
        // Log ready status every 3 seconds (only when waiting)
        static unsigned long lastReadyLogTime = 0;
        if (now - lastReadyLogTime > 3000) {
          lastReadyLogTime = now;
          LOG_INFO(LogCategory::CORE,
                   "BEKLEMEDE: Test Başlat (0x5204=3) komutu bekleniyor... (Şu "
                   "an: %d)",
                   buttonCmd);
        }

        if (buttonCmd == 3 || shouldTriggerTestStart) {
          shouldTriggerTestStart = false; // Reset flag
          LOG_INFO(LogCategory::CORE, "🚀 TEST START TETIKLENDI! (0x5204 = 3)");
          DwinService::getInstance().writeVP(0x5204, 0); // Reset button

          // CRITICAL: Switch to Test Screen (Page 3)
          LOG_INFO(LogCategory::CORE, "📄 Sayfa 3'e geçiliyor...");
          DwinService::getInstance().changePage(3);

          // PRESERVE RFID PORT and STATUS after page change (latched)
          if (rfid_latched_port > 0) {
            dwinWritePort(rfid_latched_port);
            LOG_INFO(LogCategory::CORE, "✅ RFID Port %d korundu (Sayfa 3)",
                     rfid_latched_port);
          }
          DwinService::getInstance().writeVP(0x601A,
                                             rfid_latched != 0 ? 53 : 0);

          LOG_INFO(LogCategory::CORE,
                   "✅ Sayfa değiştirildi - Test başlatılıyor");

          // Use activeTestRecipe (already loaded when RFID was read and written
          // to DWIN) Recipe values are already in DWIN registers, no need to
          // re-fetch

          // Validate recipe (MANDATORY - No fallback to defaults)
          if (activeTestRecipe.inflationPascal == 0) {
            LOG_ERROR(LogCategory::CORE, "╔════════════════════════════════════"
                                         "═══════════════════════════╗");
            LOG_ERROR(LogCategory::CORE, "║               ❌ TEST BAŞLATMA "
                                         "HATASI ❌                      ║");
            LOG_ERROR(LogCategory::CORE, "╠════════════════════════════════════"
                                         "═══════════════════════════╣");
            LOG_ERROR(LogCategory::CORE,
                      "║ RFID Port: %-5d                                       "
                      "       ║",
                      rfid_latched_port);
            LOG_ERROR(LogCategory::CORE, "║ Recipe: %-49s║",
                      activeTestRecipe.recipeName);
            LOG_ERROR(LogCategory::CORE, "║                                    "
                                         "                           ║");
            LOG_ERROR(LogCategory::CORE, "║ ⚠️ TEST PARAMETRELERİ BULUNAMADI!   "
                                         "                          ║");
            LOG_ERROR(LogCategory::CORE, "║                                    "
                                         "                           ║");
            LOG_ERROR(LogCategory::CORE, "║ Bu RFID için recipe tanımlanmamış. "
                                         "Test başlatılamaz.         ║");
            LOG_ERROR(LogCategory::CORE, "║ Lütfen Python uygulamasından bu "
                                         "RFID'ye recipe atayın.        ║");
            LOG_ERROR(LogCategory::CORE, "╚════════════════════════════════════"
                                         "═══════════════════════════╝");

            // Send error to PC
            if (espNowSlave && espNowSlave->isInitialized()) {
              StaticJsonDocument<256> doc;
              doc["cmd"] = "TEST_START_FAILED";
              doc["device"] = "TestAparati";
              doc["error"] = "RECIPE_NOT_DEFINED";
              doc["rfid_port"] = rfid_latched_port;
              doc["message"] = "Bu RFID için test parametreleri tanımlanmamış. "
                               "Lütfen recipe atayın.";
              String jsonStr;
              serializeJson(doc, jsonStr);
              espNowSlave->sendToMaster(jsonStr.c_str());
            }

            // Show warning on Dwin screen (use warning code 75)
            DwinService::getInstance().writeVP(0x601B, 75);
            isWarning74Active = true;
            warning74StartTime = millis();

            // Reset button state - Stay in IDLE
            DwinService::getInstance().writeVP(0x5204, 0);

          } else {
            // 1. ÖNCE UART'ı Modbus'a çevir ki sensör connection durumu
            // güncellensin
            switchSerialToModbus();

            // 2. Sensör bağlantısını bekle — FreeRTOS Modbus Task zaten okuyor.
            //    directModbusRead ile Task'a müdahale etmek yerine, Task'ın
            //    sensörü bulmasını (isConnected) vTaskDelay ile bekliyoruz.
            if (pressureService && !pressureService->isConnected()) {
              LOG_INFO(LogCategory::SENSOR, "Sensör bağlantısı bekleniyor (Task okuyor)...");
              unsigned long sensorWaitStart = millis();
              const unsigned long SENSOR_WAIT_TIMEOUT_MS = 3000; // 3 saniye max
              while (!pressureService->isConnected() && (millis() - sensorWaitStart < SENSOR_WAIT_TIMEOUT_MS)) {
                vTaskDelay(pdMS_TO_TICKS(100)); // Task'a CPU ver, 100ms bekle
              }
              if (pressureService->isConnected()) {
                LOG_INFO(LogCategory::SENSOR, "Sensör bağlantısı kuruldu (%lu ms)", millis() - sensorWaitStart);
              }
            }

            // 3. 15 retry sonrası hâlâ bağlantı yoksa testi başlatma
            if (pressureService && !pressureService->isConnected()) {
              LOG_ERROR(LogCategory::SENSOR, "Sensör 15 retry sonrası hâlâ bağlantısız — test başlatılamıyor!");
              
              // PC'ye hata bildir
              StaticJsonDocument<256> errDoc;
              errDoc["status"] = "TEST_START_FAILED";
              errDoc["error"] = "SENSOR_DISCONNECTED";
              errDoc["message"] = "Basinc sensoru 15 retry sonrasi cevap vermedi";
              String errJson;
              serializeJson(errDoc, errJson);
              Serial.println(errJson);

              // Dwin ekranına uyarı göster (sayfa 76)  
              DwinService::getInstance().writeVP(0x601B, 76);
              
              // IDLE'a geri dön
              currentTestState = TestState::IDLE;
              DwinService::getInstance().writeVP(0x5204, 0);
              switchSerialToRFID();
            } else {
              // Recipe is valid AND Sensor Connected - START TEST
              LOG_INFO(LogCategory::CORE, "╔═══════════════════════════════════"
                                          "════════════════════════════╗");
              LOG_INFO(LogCategory::CORE, "║                      🚀 TEST "
                                          "BAŞLADI 🚀                       ║");
              LOG_INFO(LogCategory::CORE, "╠═══════════════════════════════════"
                                          "════════════════════════════╣");
              LOG_INFO(LogCategory::CORE, "║ RFID Port: %-3d | Recipe: %-33s ║",
                       rfid_latched_port, activeTestRecipe.recipeName);
              LOG_INFO(LogCategory::CORE, "║───────────────────────────────────"
                                          "────────────────────────────║");
              LOG_INFO(LogCategory::CORE,
                       "║ Hedef Basınç  : %-5d Pa                              "
                       "         ║",
                       activeTestRecipe.inflationPascal);
              LOG_INFO(LogCategory::CORE,
                       "║ Test Süresi   : %-5d sn                              "
                       "         ║",
                       activeTestRecipe.testDuration);
              LOG_INFO(LogCategory::CORE,
                       "║ Dengeleme     : %-5d sn                              "
                       "         ║",
                       activeTestRecipe.stabilizationTime);
              LOG_INFO(LogCategory::CORE,
                       "║ Fail Threshold: %-5d Pa                              "
                       "         ║",
                       activeTestRecipe.failThreshold);
              LOG_INFO(LogCategory::CORE, "╚═══════════════════════════════════"
                                          "════════════════════════════╝");

              // Draw "TEST RUN" text in yellow
              DwinService::getInstance().drawString(10, 10, 0x34, 0xFFE0,
                                                    0x0000, "TEST RUN");

              // STATE TRANSITION: IDLE -> PRE_INFLATION
              currentTestState = TestState::PRE_INFLATION;
              stateStartTime = millis();
              testTotalStartTime =
                  millis(); // Track total test time from PRE_INFLATION start

              // Reset test recording buffer for new test
              testRecordSampleCount = 0;
              testRecordMaxPressure = 0;
              testRecordSaved = false;
              testEndTotalDrop = 0;
              testEndWindowDrop = 0;
              testEndPressure = 0;
              lastRecordSampleTime = millis(); // Start 1Hz recording timer
              memset(testRecordSamples, 0, sizeof(testRecordSamples));

              // Initialize test result status (0x8018 = 0: Not finished)
              DwinService::getInstance().writeVP(0x8018, 0);

              // NOTIFY PC: Test Started with FULL RECIPE SYNC
              if (espNowSlave && espNowSlave->isInitialized()) {
                StaticJsonDocument<512> doc; // Increased size for extra params
                doc["cmd"] = "TEST_STARTED";
                doc["device"] = "TestAparati";
                doc["did"] = espNowSlave->getDeviceId();
                doc["recipe"] = activeTestRecipe.recipeName;
                doc["target_pressure"] = activeTestRecipe.inflationPascal;
                doc["test_duration"] = activeTestRecipe.testDuration;

                // Full Recipe Sync (p1-p8)
                doc["p1"] = activeTestRecipe.inflationMaxTime;
                doc["p2"] = activeTestRecipe.inflationPascal;
                doc["p3"] = activeTestRecipe.stabilizationTime;
                doc["p4"] =
                    activeTestRecipe.reinflateThreshold; // Usually calculated
                doc["p6"] = activeTestRecipe.failThreshold;
                doc["p7"] = activeTestRecipe.testDuration;
                doc["p8"] = activeTestRecipe.successDropPascal;

                String jsonStr;
                serializeJson(doc, jsonStr);
                espNowSlave->sendToMaster(jsonStr.c_str());
                LOG_INFO(LogCategory::CORE, "Test başlatıldı, PC'ye bildirildi "
                                            "(Reçete Senkronize Edildi).");
                DwinService::getInstance().writeVP(0x8010, 0);
                DwinService::getInstance().writeVP(0x8012, 0);
                DwinService::getInstance().writeVP(0x8014, 0);
              }

              // Configure Hardware for Pre-Inflation
              digitalWrite(Config::hardware.relays.glove_solenoid,
                           HIGH); // Open Glove
              digitalWrite(Config::hardware.relays.pump_motor,
                           HIGH); // Start Pump

              // Display Target on Screen (from RFID recipe)
              DwinService::getInstance().writeVP(
                  0x5503, activeTestRecipe.inflationPascal);
              DwinService::getInstance().writeVP(
                  0x5504, activeTestRecipe.stabilizationTime);
              DwinService::getInstance().writeVP(
                  0x5506, activeTestRecipe.inflationMaxTime);
              DwinService::getInstance().writeVP(0x5507,
                                                 activeTestRecipe.testDuration);
              // P6 (Fail Threshold) — refresh from recipe
              DwinService::getInstance().writeVP(
                  0x5505, activeTestRecipe.failThreshold);
            }
          }
        }
      }
      // PRIORITY 2: If NOT mounted yet → This is MOUNT button
      else if (buttonCmd == 1 && !isGasketMounted) {
        // SECURITY CHECK: Read RFID tag directly before mount
        uint32_t currentTag = rfidService->getLastDetectedTag();

        if (currentTag == 0) {
          // NO TAG DETECTED - Clear RFID icon and reject mount
          LOG_WARN(LogCategory::CORE, "MOUNT REDDEDILDI! RFID TAG YOK!");
          rfid_live = 0;
          rfid_live_port = 0;
          DwinService::getInstance().writeVP(0x601A, 0);  // Clear RFID icon
          dwinWritePort(0);  // Clear port
          DwinService::getInstance().writeVP(0x5204, 0);  // Reset button
          DwinService::getInstance().writeVP(0x601B, 74); // Show warning
          isWarning74Active = true;
          warning74StartTime = millis();
        } else if (!rfidService->isTagAuthorized(currentTag)) {
          // TAG EXISTS BUT NOT AUTHORIZED
          LOG_WARN(LogCategory::CORE, "YETKISIZ RFID! Tag: 0x%08X", currentTag);
          isWarning74Active = true;
          warning74StartTime = millis();
          DwinService::getInstance().writeVP(0x5204, 0);  // Reset button
          DwinService::getInstance().writeVP(0x601B, 74); // Show warning
        } else if (!isMountButtonPressed) {
          // TAG IS AUTHORIZED - Allow mount
          LOG_INFO(LogCategory::CORE, "Mount Triggered - RFID OK: 0x%08X",
                   currentTag);
          shouldTriggerMount = true;
          isMountButtonPressed = true; // Stay active until released

          // Clear VP immediately so screen doesn't stay at 1
          DwinService::getInstance().writeVP(0x5204, 0);
        }
      } else if (buttonCmd == 0) {
        // Reset latch when button is released (read as 0)
        isMountButtonPressed = false;
      }

      // Clear legacy counters
      mountTriggerCounter = 0;
      mountWindowCounter = 0;

      // --- C. BATTERY TOGGLE LOGIC - DEPRECATED (Moved to 0.1) ---
      // (Removed to prevent conflicting writes with Priority logic)

      // 1. PRESSURE & TIMEOUT MONITORING (If Mounting)
      if (isMounting) {
        // A. Update 10s Countdown (VP 0x700E)
        unsigned long elapsedS = (now - mountStartTime) / 1000;
        uint16_t countdown = (elapsedS >= 10) ? 0 : (10 - elapsedS);
        if (countdown != lastMountCountdown) {
          lastMountCountdown = countdown;
          DwinService::getInstance().writeVP(0x700E, countdown);

          // PRESERVE RFID INFO during countdown update (latched)
          if (rfid_latched_port > 0) {
            dwinWritePort(rfid_latched_port);
          }
          DwinService::getInstance().writeVP(0x601A,
                                             rfid_latched != 0 ? 53 : 0);
        }

        // B. Check Timeout (10s)
        if (elapsedS >= 10) {
          LOG_WARN(LogCategory::SENSOR,
                   "Mount ZAMAN AŞIMI (10sn). Conta Şişemedi.");
          // Stop Hardware
          digitalWrite(Config::hardware.relays.conta_solenoid, LOW);
          digitalWrite(Config::hardware.relays.pump_motor, LOW);
          // Revert State
          isMounting = false;
          isGasketMounted = false;
          DwinService::getInstance().writeVP(0x601C, 10); // Ready
          DwinService::getInstance().writeVP(0x5204, 0);  // Show Mount Button

          // NOTIFY PC: Mount timeout (unmount)
          if (espNowSlave && espNowSlave->isInitialized()) {
            StaticJsonDocument<256> doc;
            doc["cmd"] = "MOUNT_TIMEOUT";
            doc["device"] = "TestAparati";
            doc["battery"] = BatteryService::getInstance().getPercentage();
            if (pressureService) {
              doc["glove_pressure"] = pressureService->getPressure();
            }
            String jsonStr;
            serializeJson(doc, jsonStr);
            espNowSlave->sendToMaster(jsonStr.c_str());
          }

          // PRESERVE RFID INFO after timeout (latched)
          if (rfid_latched_port > 0) {
            dwinWritePort(rfid_latched_port);
          }
          DwinService::getInstance().writeVP(0x601A,
                                             rfid_latched != 0 ? 53 : 0);

          // CLEAR LATCHED RFID (timeout = mount başarısız)
          rfid_latched = 0;
          rfid_latched_port = 0;

          // Set Warning 77
          DwinService::getInstance().writeVP(0x601B, 77);
          isWarning77Active = true;
          warning77StartTime = now;
          DwinService::getInstance().writeVP(0x700E, 0);
          lastMountCountdown = 0;

          // TIMEOUT (BAŞARISIZ) -> RFID okumaya dön (tekrar deneme için)
          switchUart(UartMode::RFID);
          rfidReadingEnabled = true; // UNLOCK RFID - failed mount, allow retry

          // CRITICAL BUG FIX: Reset State Machine to IDLE
          currentTestState = TestState::IDLE;

          LOG_INFO(LogCategory::CORE, "Mount başarısız - RFID kilidi açıldı, "
                                      "okumaya dönüldü, State -> IDLE");

          return; // Skip pressure check this cycle
        }

        // C. Normal Pressure Check
        uint16_t currentRaw = gasketService->getRawValue();

        if (currentRaw >= MOUNT_TARGET_PRESSURE) {
          LOG_INFO(
              LogCategory::SENSOR,
              "Hedef Basınca Ulaşıldı (%d / Hedef: %d). Montaj Tamamlandı.",
              currentRaw, MOUNT_TARGET_PRESSURE);

          // STOP SEQUENCE
          digitalWrite(Config::hardware.relays.conta_solenoid,
                       LOW); // Seal (Pin 1)
          digitalWrite(Config::hardware.relays.pump_motor,
                       LOW); // Stop Pump (Pin 2)

          // 4. Update State
          isMounting = false;
          isGasketMounted = true;

          currentTestState = TestState::IDLE;

          // Update Status (12: Ready for Test)
          DwinService::getInstance().writeVP(0x601C, 12);

          // RFID stays LOCKED after successful mount - will unlock only on
          // dismount or fail
          LOG_INFO(LogCategory::RFID, "Mount başarılı - RFID kilidi devam "
                                      "ediyor (rfidReadingEnabled=false)");

          // Test 3 fonts after mount complete
          DwinService::getInstance().drawString(450, 50, 0x00, 0x07E0, 0x0000,
                                                "OK FONT 0");
          DwinService::getInstance().drawString(450, 120, 0x01, 0x07E0, 0x0000,
                                                "OK FONT 1");
          DwinService::getInstance().drawString(450, 190, 0x02, 0x07E0, 0x0000,
                                                "OK FONT 2");

          // PRESERVE RFID INFO after mount (latched)
          if (rfid_latched_port > 0) {
            dwinWritePort(rfid_latched_port);
          }
          DwinService::getInstance().writeVP(0x601A,
                                             rfid_latched != 0 ? 53 : 0);

          // START 2-SECOND DELAY before showing Test Start button
          mountSuccessWaitingForButton = true;
          mountSuccessTime = millis();

          LOG_INFO(
              LogCategory::SENSOR,
              "Mount Tamamlandı. 2 saniye sonra Test Start Butonu görünecek.");
        }
      }

      // 2. MOUNT START LOGIC (IDLE -> MOUNTING)
      if (shouldTriggerMount) {
        // HAFIZA DOLU KONTROLÜ - 10 test varsa mount engelle
        if (TestStorageService::getInstance().getTestCount() >= 10) {
          LOG_WARN(LogCategory::CORE, "MOUNT İPTAL! Hafıza dolu (10 test).");
          shouldTriggerMount = false;
          DwinService::getInstance().writeVP(0x5204, 0); // Reset button
        } else {
        // DOUBLE-CHECK: Read RFID tag again before starting mount hardware
        uint32_t currentTag = rfidService->getLastDetectedTag();

        if (currentTag == 0) {
          // NO TAG - Clear RFID info and abort
          LOG_ERROR(LogCategory::CORE, "MOUNT İPTAL! RFID TAG YOK!");
          shouldTriggerMount = false;
          rfid_live = 0;
          rfid_live_port = 0;
          DwinService::getInstance().writeVP(0x601A, 0); // Clear RFID icon
          dwinWritePort(0); // Clear port
          DwinService::getInstance().writeVP(0x601B,
                                             74); // Show unauthorized warning
          DwinService::getInstance().writeVP(0x5204, 0); // Reset button
          // PC'ye bildir — kullanıcı neden etkisiz görsün
          if (espNowSlave && espNowSlave->isInitialized()) {
            espNowSlave->sendToMaster("{\"cmd\":\"MOUNT_FAILED\",\"reason\":\"NO_RFID\"}");
          }
        } else if (!rfidService->isTagAuthorized(currentTag)) {
          // TAG EXISTS BUT NOT AUTHORIZED
          LOG_ERROR(LogCategory::CORE, "MOUNT İPTAL! YETKISIZ TAG: 0x%08X",
                    currentTag);
          shouldTriggerMount = false;
          DwinService::getInstance().writeVP(0x601B,
                                             74); // Show unauthorized warning
          DwinService::getInstance().writeVP(0x5204, 0); // Reset button
        } else if (currentTestState == TestState::IDLE) {
          // USER SUGGESTION: Skip if already > 1200
          uint16_t currentRaw =
              gasketService ? gasketService->getRawValue() : 0;
          if (currentRaw > 1200) {
            LOG_INFO(LogCategory::SENSOR, "Mount Atlanıyor (Zaten Sıkı: %d)",
                     currentRaw);
            isGasketMounted = true;
            switchSerialToModbus(); // Direct to Modbus (already tight)
            currentTestState = TestState::IDLE;
            mountStartTime = now;         // FIX: set timer even for skip-mount path
            testTotalStartTime = 0;       // FIX: clear test timer until test actually starts
            // Reset rolling-window history buffer (skip-mount path)
            pressureHistoryIndex = 0;
            pressureHistoryCount = 0;
            memset(pressureHistory, 0, sizeof(pressureHistory));
            DwinService::getInstance().writeVP(0x601C, 12); // Ready for Test

            // Test 3 fonts for "already tight" scenario
            DwinService::getInstance().drawString(450, 260, 0x00, 0xFFFF,
                                                  0x0000, "TIGHT F0");
            DwinService::getInstance().drawString(450, 330, 0x01, 0xFFFF,
                                                  0x0000, "TIGHT F1");
            DwinService::getInstance().drawString(450, 400, 0x02, 0xFFFF,
                                                  0x0000, "TIGHT F2");

            // FIX: Latch RFID in skip-mount path (previously missing → RFID=0 bug)
            rfid_latched = rfid_live;
            rfid_latched_port = rfid_live_port;
            rfid_latched_recipe = rfid_live_recipe;
            activeTestRecipe = rfid_latched_recipe;
            LOG_INFO(LogCategory::RFID, "RFID LATCHED (skip-mount)! UID=0x%08X, Port=%d",
                     rfid_latched, rfid_latched_port);

            // PRESERVE RFID INFO after mount skip (latched)
            if (rfid_latched_port > 0) {
              dwinWritePort(rfid_latched_port);
            }
            DwinService::getInstance().writeVP(0x601A,
                                               rfid_latched != 0 ? 53 : 0);

            // START 2-SECOND DELAY before showing Test Start button
            mountSuccessWaitingForButton = true;
            mountSuccessTime = millis();
            LOG_INFO(
                LogCategory::SENSOR,
                "Mount Atlandı. 2 saniye sonra Test Start Butonu görünecek.");

            shouldTriggerMount = false;
          } else {
            LOG_INFO(LogCategory::SENSOR,
                     "Mount BAŞLATILIYOR... (State: IDLE)");

            // ACTION:
            // 1. Close Drain (Pin 4) & Glove (Pin 3)
            digitalWrite(Config::hardware.relays.drain_solenoid, LOW);
            digitalWrite(Config::hardware.relays.glove_solenoid, LOW);

            // 2. Open Gasket Solenoid (Pin 1) - Let Air In
            digitalWrite(Config::hardware.relays.conta_solenoid, HIGH);

            // 3. Start Pump (Pin 2)
            digitalWrite(Config::hardware.relays.pump_motor, HIGH);

            // 4. Update Screen (11: Mounting)
            DwinService::getInstance().writeVP(0x601C, 11);

            // Test 3 different fonts during mount (Page 2, 854x480 screen)
            DwinService::getInstance().drawString(100, 260, 0x00, 0xFFE0,
                                                  0x0000, "MOUNT FONT 0");
            DwinService::getInstance().drawString(100, 330, 0x01, 0xFFE0,
                                                  0x0000, "MOUNT FONT 1");
            DwinService::getInstance().drawString(100, 400, 0x02, 0xFFE0,
                                                  0x0000, "MOUNT FONT 2");

            // 4.1 RFID LATCHING: Mount anında rfid_live'dan kilitle
            rfid_latched = rfid_live;
            rfid_latched_port = rfid_live_port;
            rfid_latched_recipe = rfid_live_recipe;
            activeTestRecipe = rfid_latched_recipe; // FIX: Sync activeTestRecipe at mount so same-tag re-mount works
            LOG_INFO(LogCategory::RFID, "RFID LATCHED! UID=0x%08X, Port=%d",
                     rfid_latched, rfid_latched_port);

            // ── CLEAR PREVIOUS TEST DATA FROM DWIN GRAPH (yeni mount = eski veriyi sil) ──
            DwinService::getInstance().writeVP(0x5500, 0); // PRE_INFLATION displayed pressure
            DwinService::getInstance().writeVP(0x5501, 0); // CONDITIONING displayed pressure
            DwinService::getInstance().writeVP(0x5502, 0); // TESTING displayed pressure
            DwinService::getInstance().writeVP(0x5508, 0); // Window sample counter
            DwinService::getInstance().writeVP(0x5509, 0); // Elapsed time
            DwinService::getInstance().writeVP(0x550B, 0); // Pressure drop display
            // Reset rolling-window history buffer
            pressureHistoryIndex = 0;
            pressureHistoryCount = 0;
            memset(pressureHistory, 0, sizeof(pressureHistory));
            LOG_INFO(LogCategory::CORE, "Mount: DWIN graf/süre sıfırlandı");

            // 4.2 PRESERVE RFID INFO during mount (latched)
            if (rfid_latched_port > 0) {
              dwinWritePort(rfid_latched_port);
            }
            DwinService::getInstance().writeVP(0x601A, 53);

            // 4.3 Switch to MODBUS immediately (for pressure monitoring)
            switchUart(UartMode::MODBUS);
            LOG_INFO(LogCategory::CORE, "Mount başladı - Modbus'a geçildi");

            // 4.4 LOCK RFID READING during mount process
            rfidReadingEnabled = false;
            LOG_INFO(LogCategory::RFID,
                     "RFID okuma kilitledi - mount işlemi aktif");

            // Reset Trigger Flag
            shouldTriggerMount = false;

            // 5. Set State
            isMounting = true;
            currentTestState = TestState::MOUNTING_GASKET; // Sync Enum
            mountStartTime = now;
            pumpOffTrackingActive = false; // Yeni test başlıyor, tracking sıfırla

            // Reset warnings
            isWarning77Active = false;
            DwinService::getInstance().writeVP(0x601B, 0);
          }
        } else {
          LOG_WARN(LogCategory::SENSOR,
                   "Mount REDDEDILDI! State IDLE değil: %d",
                   (int)currentTestState);
          shouldTriggerMount = false; // Reset if rejected
        }
        } // else (hafıza dolu değil)
      }
    }
  }

  // ---------------- MULTI-STAGE TEST LOGIC (STATE MACHINE) ----------------
  if (currentTestState != TestState::IDLE &&
      currentTestState != TestState::MOUNTING_GASKET && pressureService) {
    int32_t currentPressure = pressureService->getPressure();
    // Use activeTestRecipe (loaded from RFID tag at test start)
    unsigned long elapsed = millis() - stateStartTime;

    switch (currentTestState) {
    case TestState::PRE_INFLATION: {
      DwinService::getInstance().writeVP(
          0x5500, currentPressure); // Anlık Değer? User said captured value.
                                    // Let's update live until capture.

      // Update total test time (0x5509)
      int totalElapsedSec = (millis() - testTotalStartTime) / 1000;
      DwinService::getInstance().writeVP(0x5509, totalElapsedSec);

      // --- Test Kayıt: PRE_INFLATION basınç örneği kaydet (1Hz) ---
      if (millis() - lastRecordSampleTime >= 1000) {
        lastRecordSampleTime += 1000; // drift-free: += instead of = millis()
        if (testRecordSampleCount < MAX_PRESSURE_SAMPLES) {
          testRecordSamples[testRecordSampleCount] = (int16_t)currentPressure;
          testRecordSampleCount++;
        }
      }

      // TIMEOUT CHECK: Inflation taking too long?
      if (totalElapsedSec >= activeTestRecipe.inflationMaxTime) {
        LOG_WARN(LogCategory::SENSOR,
                 "TEST FAIL: Şişirme zaman aşımı! (%d sn > %d sn)",
                 totalElapsedSec, activeTestRecipe.inflationMaxTime);
        DwinService::getInstance().writeVP(0x8010, 36);
        digitalWrite(Config::hardware.relays.pump_motor, LOW);
        digitalWrite(Config::hardware.relays.glove_solenoid, LOW);
        // Şişirme timeout'unda karar anı değerlerini kaydet
        testEndTotalDrop = 0;
        testEndWindowDrop = 0;
        testEndPressure = (int16_t)currentPressure;
        testResult = false;
        currentTestState = TestState::FINISHED;
        break;
      }

      // SLOW INFLATION CONTROL: When approaching target (200 Pa threshold)
      int distanceToTarget = activeTestRecipe.inflationPascal - currentPressure;

      if (distanceToTarget <= 400 && distanceToTarget > 0) {
        // Slow inflation: 500ms wait + 200ms inflate (PWM-like control)
        static unsigned long lastInflateCycle = 0;
        unsigned long cycleTime = millis() - lastInflateCycle;

        if (cycleTime < 500) {
          // Wait phase - pump OFF
          digitalWrite(Config::hardware.relays.pump_motor, LOW);
        } else if (cycleTime < 700) {
          // Inflate phase - pump ON (200ms)
          digitalWrite(Config::hardware.relays.pump_motor, HIGH);
        } else {
          // Reset cycle
          lastInflateCycle = millis();
        }
      } else if (distanceToTarget > 200) {
        // Far from target - normal continuous inflation
        digitalWrite(Config::hardware.relays.pump_motor, HIGH);
      }

      if (currentPressure >= activeTestRecipe.inflationPascal) {
        // TARGET REACHED
        digitalWrite(Config::hardware.relays.pump_motor, LOW);
        digitalWrite(Config::hardware.relays.glove_solenoid, LOW);

        // Capture Value
        conditioningStartPressure = currentPressure;
        DwinService::getInstance().writeVP(0x5500, conditioningStartPressure);

        // PRE_INFLATION süresi → 0x5514
        int inflationSec = (millis() - testTotalStartTime) / 1000;
        DwinService::getInstance().writeVP(0x5514, inflationSec);

        DwinService::getInstance().writeVP(0x8010, 37);

        // --- T1 MARKER: PRE_INFLATION sonu ---
        if (testRecordSampleCount < MAX_PRESSURE_SAMPLES) {
          testRecordSamples[testRecordSampleCount++] = -1; // T1 faz geçiş marker
        }

        // TRANSITION -> CONDITIONING
        currentTestState = TestState::CONDITIONING;
        stateStartTime = millis();
        conditioningDuration = activeTestRecipe.stabilizationTime;
        DwinService::getInstance().writeVP(0x5504, conditioningDuration);

        LOG_INFO(LogCategory::SENSOR,
                 "Ön Şişirme Tamam (%d Pa). Conditioning Başlıyor...",
                 currentPressure);
      }
      break;
    }

    case TestState::CONDITIONING: {
      // Timer Logic
      int elapsedSec = elapsed / 1000;
      DwinService::getInstance().writeVP(0x5007, elapsedSec);
      DwinService::getInstance().writeVP(0x5516, elapsedSec); // Stabilizasyon süresi
      int totalElapsedSec = (millis() - testTotalStartTime) / 1000;
      DwinService::getInstance().writeVP(0x5509, totalElapsedSec); // Toplam süre
      DwinService::getInstance().writeVP(0x5501, currentPressure);

      // ÖNCE geçiş kontrolü — ekstra sample kaydedilmesini önler
      if (elapsedSec >= conditioningDuration) {
        DwinService::getInstance().writeVP(0x8012, 37);
        // TRANSITION -> TESTING
        // Capture End Pressure
        conditioningEndPressure = currentPressure;
        testStartPressure = conditioningEndPressure; // Reference

        // --- T2 MARKER: CONDITIONING sonu ---
        if (testRecordSampleCount < MAX_PRESSURE_SAMPLES) {
          testRecordSamples[testRecordSampleCount++] = -2; // T2 faz geçiş marker
        }

        currentTestState = TestState::TESTING;
        stateStartTime = millis();
        testPhaseStartTime = millis(); // Track TESTING phase time for 0x5508

        // Reset Rolling Window
        pressureHistoryIndex = 0;
        pressureHistoryCount = 0;
        memset(pressureHistory, 0, sizeof(pressureHistory));

        // Basınç artışı takibi: CONDITIONING'den devam (zaten aktif)
        // pumpOffMinPressure son 10 saniyeden beri güncelleniyor
        if (!pumpOffTrackingActive) {
          pumpOffMinPressure = (int16_t)currentPressure;
          pumpOffTrackingActive = true;
        }
        LOG_INFO(LogCategory::SENSOR, "Test başlangıç min basınç: %d Pa", pumpOffMinPressure);

        // Set Limits — Kritik Basınç Sınırı (P8) ekrana yaz
        DwinService::getInstance().writeVP(0x5505,
                                           testStartPressure - activeTestRecipe.successDropPascal);

        // P6: Kabul Edilebilir Basınç Düşümü → 0x5512
        DwinService::getInstance().writeVP(0x5512, activeTestRecipe.failThreshold);
        // P8: Kritik Basınç Sınırı → 0x5510
        DwinService::getInstance().writeVP(0x5510, activeTestRecipe.successDropPascal);

        LOG_INFO(LogCategory::SENSOR,
                 "Conditioning Tamam (%d Pa). Test Başlıyor... P6(KabulDusus)=%d P8(KritikSinir)=%d",
                 conditioningEndPressure, activeTestRecipe.failThreshold,
                 activeTestRecipe.successDropPascal);
        break;
      }

      // --- Test Kayıt: CONDITIONING basınç örneği kaydet (1Hz) ---
      // (geçiş kontrolünden SONRA — 121. sample önlenir)
      if (millis() - lastRecordSampleTime >= 1000) {
        lastRecordSampleTime += 1000; // drift-free: += instead of = millis()
        if (testRecordSampleCount < MAX_PRESSURE_SAMPLES) {
          testRecordSamples[testRecordSampleCount] = (int16_t)currentPressure;
          testRecordSampleCount++;
        }
      }

      // Hysteresis Logic (P4 - reinflateThreshold from recipe)
      int hysteresis = activeTestRecipe.reinflateThreshold > 0
                           ? activeTestRecipe.reinflateThreshold
                           : 50;

      int remainingSec = conditioningDuration - elapsedSec;

      // Son 10 saniyeye girildiğinde (pompa zaten kapalı, reinflate yok) takibi başlat
      if (!isReinflating && remainingSec <= 10 && !pumpOffTrackingActive) {
        pumpOffMinPressure = (int16_t)currentPressure;
        pumpOffTrackingActive = true;
        LOG_INFO(LogCategory::SENSOR, "Basınç artışı takibi başladı (min=%d Pa)", pumpOffMinPressure);
      }

      // Pompa kapalıyken basınç artışı takibi (son 10 saniye)
      if (pumpOffTrackingActive && remainingSec <= 10) {
        if ((int16_t)currentPressure < pumpOffMinPressure) {
          pumpOffMinPressure = (int16_t)currentPressure;
        }
        // Basınç artışı tespit → henüz TESTING değiliz, sadece log (window TESTING'de sıfırlanır)
        if ((int16_t)currentPressure >= pumpOffMinPressure + PRESSURE_RISE_TOLERANCE) {
          LOG_WARN(LogCategory::SENSOR,
                   "⚠ Conditioning son 10s: Basınç artışı tespit! (%d Pa > min %d + %d)",
                   currentPressure, pumpOffMinPressure, PRESSURE_RISE_TOLERANCE);
          pumpOffMinPressure = (int16_t)currentPressure;
        }
      }

      // KURAL 1: Son 10 saniyede degilsek motoru calistirmaya izin ver
      if (!isReinflating && remainingSec > 10 &&
          currentPressure < (activeTestRecipe.inflationPascal - hysteresis)) {
        isReinflating = true;
        lastReinflateTime = millis();
        digitalWrite(Config::hardware.relays.glove_solenoid, HIGH);
        digitalWrite(Config::hardware.relays.pump_motor, HIGH);
        LOG_INFO(LogCategory::SENSOR, "Re-inflate Triggered (%d Pa)", currentPressure);
      }

      if (isReinflating) {
        // KURAL 2: Motor calisirken 10 saniye sinirina girilirse ANINDA motoru kes
        if (remainingSec <= 10) {
          isReinflating = false;
          digitalWrite(Config::hardware.relays.pump_motor, LOW);
          digitalWrite(Config::hardware.relays.glove_solenoid, LOW);
          // Pompa durdu → basınç artışı takibini başlat
          if (!pumpOffTrackingActive) {
            pumpOffMinPressure = (int16_t)currentPressure;
            pumpOffTrackingActive = true;
            LOG_INFO(LogCategory::SENSOR, "Basınç artışı takibi başladı (min=%d Pa)", pumpOffMinPressure);
          }
          LOG_INFO(LogCategory::SENSOR, "Re-inflate Iptal: Son 10 saniye korumasi aktif.");
        } else if (millis() - lastReinflateTime < 200) {
          // Pumping...
        } else if (millis() - lastReinflateTime < 800) {
          digitalWrite(Config::hardware.relays.pump_motor, LOW);
          digitalWrite(Config::hardware.relays.glove_solenoid, LOW);
        } else {
          isReinflating = false;
        }
      }
      break;
    }

    case TestState::TESTING: {
      // ═══════════════════════════════════════════════════════════════
      // KAYAN PENCERE TEST ALGORITMASI
      // ═══════════════════════════════════════════════════════════════
      // P7 = Pencere boyutu (sn) — reçeteden gelir
      // P6 = Kabul Edilebilir Basınç Düşümü (Pa) — pencerede < P6 düşüş → PASS
      // P8 = Kritik Basınç Sınırı (Pa) — toplam düşüş > P8 → anında FAIL
      // Süre limiti YOK. Test PASS veya FAIL olana kadar devam eder.
      // ═══════════════════════════════════════════════════════════════

      // P7: Kayan pencere boyutu (saniye)
      int windowSize = activeTestRecipe.testDuration > 0
                           ? activeTestRecipe.testDuration
                           : 30;
      if (windowSize > ROLLING_WINDOW_MAX)
        windowSize = ROLLING_WINDOW_MAX;

      // P6: Kabul Edilebilir Basınç Düşümü (Pa) — pencerede bu kadardan az düşüş → PASS
      int acceptableDrop = activeTestRecipe.failThreshold > 0
                               ? activeTestRecipe.failThreshold
                               : 10;

      // P8: Kritik Basınç Sınırı (Pa) — toplam düşüş bunu aşarsa → anında FAIL
      int criticalDrop = activeTestRecipe.successDropPascal > 0
                             ? activeTestRecipe.successDropPascal
                             : 200;

      DwinService::getInstance().writeVP(0x8018, 15);
      DwinService::getInstance().writeVP(0x5502, currentPressure);

      int totalElapsedSec = (millis() - testTotalStartTime) / 1000;
      DwinService::getInstance().writeVP(0x5509, totalElapsedSec);

      // ═══ BASINÇ ARTIŞI TESPİTİ (Pompa kapalıyken dış etken koruması) ═══
      if (pumpOffTrackingActive) {
        if ((int16_t)currentPressure < pumpOffMinPressure) {
          pumpOffMinPressure = (int16_t)currentPressure;
        } else if ((int16_t)currentPressure >= pumpOffMinPressure + PRESSURE_RISE_TOLERANCE) {
          LOG_WARN(LogCategory::SENSOR,
                   "⚠ Dış etken basınç artışı! (%d Pa > min %d + %d) → Window sıfırlanıyor",
                   currentPressure, pumpOffMinPressure, PRESSURE_RISE_TOLERANCE);
          // Rolling window sıfırla
          pressureHistoryIndex = 0;
          pressureHistoryCount = 0;
          memset(pressureHistory, 0, sizeof(pressureHistory));
          // Minimum basıncı şu anki değere güncelle
          pumpOffMinPressure = (int16_t)currentPressure;
        }
      }

      if (millis() - lastRecordSampleTime >= 1000) {
        lastRecordSampleTime += 1000; // drift-free: unified timer for all phases

        // --- Kayan pencere buffer güncelle (P7 boyutunda) ---
        pressureHistory[pressureHistoryIndex] = currentPressure;
        pressureHistoryIndex = (pressureHistoryIndex + 1) % windowSize;
        if (pressureHistoryCount < windowSize)
          pressureHistoryCount++;

        // --- Test Kayıt: Basınç örneği kaydet (1Hz) ---
        if (testRecordSampleCount < MAX_PRESSURE_SAMPLES) {
          testRecordSamples[testRecordSampleCount] = (int16_t)currentPressure;
          testRecordSampleCount++;
          if ((int16_t)currentPressure > testRecordMaxPressure) {
            testRecordMaxPressure = (int16_t)currentPressure;
          }
        }

        DwinService::getInstance().writeVP(0x5508, pressureHistoryCount);

        // --- Toplam düşüş (test başından beri) ---
        int32_t totalDrop = (int32_t)testStartPressure - (int32_t)currentPressure;
        if (totalDrop < 0) totalDrop = 0;

        // --- 0x550B: Pencere dolmadan toplam düşüş, dolduktan sonra son P7 saniyelik düşüş ---
        int32_t displayDrop;
        if (pressureHistoryCount >= windowSize) {
          // pressureHistoryIndex = en eski değerin pozisyonu (bir sonraki yazma yeri)
          int32_t windowStartPressure = (int32_t)pressureHistory[pressureHistoryIndex];
          displayDrop = windowStartPressure - (int32_t)currentPressure;
          if (displayDrop < 0) displayDrop = 0;
        } else {
          displayDrop = totalDrop;
        }
        DwinService::getInstance().writeVP(0x550B, displayDrop);

        // --- FAIL KONTROLÜ: Basınç 500 Pa altına düştü ---
        if (currentPressure < 500) {
          DwinService::getInstance().writeVP(0x8014, 36);
          LOG_INFO(LogCategory::CORE,
                   "TEST FAIL (Basınç kritik düşük: %d Pa < 500 Pa)", (int)currentPressure);
          testEndTotalDrop = (int16_t)totalDrop;
          testEndWindowDrop = (int16_t)displayDrop;
          testEndPressure = (int16_t)currentPressure;
          testResult = false;
          currentTestState = TestState::FINISHED;
          DwinService::getInstance().writeVP(0x8018, 10);
          break;
        }

        // --- FAIL KONTROLÜ: Toplam düşüş > Kritik Basınç Sınırı (P8) ---
        if (totalDrop > criticalDrop) {
          DwinService::getInstance().writeVP(0x8014, 36);
          LOG_INFO(LogCategory::CORE,
                   "TEST FAIL (Kritik Sinir Asildi: %d Pa > %d Pa)",
                   (int)totalDrop, criticalDrop);
          // Karar anındaki değerleri sabitle (venting öncesi!)
          testEndTotalDrop = (int16_t)totalDrop;
          testEndWindowDrop = (int16_t)displayDrop; // pencere dolmadıysa totalDrop ile aynı
          testEndPressure = (int16_t)currentPressure;
          testResult = false;
          currentTestState = TestState::FINISHED;
          DwinService::getInstance().writeVP(0x8018, 10);
          break;
        }

        // --- PASS KONTROLÜ: P7 saniyelik pencere dolduğunda ---
        if (pressureHistoryCount >= windowSize) {
          // pressureHistoryIndex = bir sonraki yazma pozisyonu = en eski değer
          int32_t windowStartPressure = (int32_t)pressureHistory[pressureHistoryIndex];
          int32_t windowDrop = windowStartPressure - (int32_t)currentPressure;
          if (windowDrop < 0) windowDrop = 0;

          LOG_INFO(LogCategory::CORE,
                   "Pencere(%ds): Baslangic=%d Bitis=%d Dusus=%d (KabulEsik<%d, KritikEsik>%d, ToplamDusus=%d)",
                   windowSize, (int)windowStartPressure, (int)currentPressure,
                   (int)windowDrop, acceptableDrop, criticalDrop, (int)totalDrop);

          // PASS: Pencerede düşüş Kabul Edilebilir Basınç Düşümünden (P6) az veya eşit
          if (windowDrop <= acceptableDrop) {
            DwinService::getInstance().writeVP(0x8014, 37);
            LOG_INFO(LogCategory::CORE,
                     "TEST PASS (%ds Pencere Dusus Uygun: %d Pa < %d Pa)",
                     windowSize, (int)windowDrop, acceptableDrop);
            // Karar anındaki değerleri sabitle (venting öncesi!)
            testEndTotalDrop = (int16_t)totalDrop;
            testEndWindowDrop = (int16_t)windowDrop;
            testEndPressure = (int16_t)currentPressure;
            testResult = true;
            currentTestState = TestState::FINISHED;
            DwinService::getInstance().writeVP(0x8018, 9);
            break;
          }
        } else {
          LOG_INFO(LogCategory::CORE,
                   "Pencere Dolmadi: %d/%d sn (ToplamDusus=%d, KritikSinir=%d)",
                   pressureHistoryCount, windowSize, (int)totalDrop, criticalDrop);
        }
      }
      break;
    }

    case TestState::FINISHED: {
      // ── FINISHED'e ilk giriş: ekran + abort kilidi sadece BİR KEZ yazılır ──
      static bool finishedScreenWritten = false;
      if (!finishedScreenWritten) {
        finishedScreenWritten = true;

        // ABORT KILIDI
        DwinService::getInstance().writeVP(0x7006, 9);

        // Show Result on Screen
        if (testResult) {
          DwinService::getInstance().writeVP(0x601C, 88);
          DwinService::getInstance().writeVP(0x8018, 9);
          DwinService::getInstance().drawString(10, 10, 0x34, 0x07E0, 0x0000, "PASS!");
        } else {
          DwinService::getInstance().writeVP(0x601C, 99);
          DwinService::getInstance().writeVP(0x8018, 10);
          DwinService::getInstance().drawString(10, 10, 0x34, 0xF800, 0x0000, "FAIL!");
        }
      }

      // 1. Venting Active (Glove + Drain)
      digitalWrite(Config::hardware.relays.drain_solenoid, HIGH);
      digitalWrite(Config::hardware.relays.glove_solenoid,
                   HIGH); // Open glove too

      // 2. CHECK PRESSURE for Safe Release (<= 400 Pa)
      // Minimum wait: 2000ms
      // Max wait: None (safety first), but maybe timeout to IDLE if sensor
      // broken?

      bool safePressure = (currentPressure <= 400);
      bool minTimePassed = (millis() - stateStartTime > 2000);

      // Log status periodically
      if ((millis() - stateStartTime) % 1000 < 50) {
        LOG_INFO(LogCategory::SENSOR, "Venting... Pressure: %d Pa",
                 currentPressure);
      }

      if (safePressure && minTimePassed) {
        // Safe to go IDLE
        digitalWrite(Config::hardware.relays.drain_solenoid, LOW);
        digitalWrite(Config::hardware.relays.glove_solenoid, LOW);

        // ═══════════════════════════════════════════════════════════════
        // TEST KAYIT: Flash'a kaydet + PC'ye TEST_COMPLETED gönder
        // ═══════════════════════════════════════════════════════════════
        if (!testRecordSaved) {
          testRecordSaved = true;
          
          // Test süresini hesapla
          uint16_t durationSec = (testTotalStartTime > 0) 
                                 ? (uint16_t)((millis() - testTotalStartTime) / 1000) 
                                 : 0;
          
          // Son basınç — karar anındaki sabitlenmiş değerleri kullan (venting sonrası DEĞİL)
          int16_t endPressure = testEndPressure;
          int16_t totalDropVal = testEndTotalDrop;
          int16_t windowDropVal = testEndWindowDrop;
          
          // Fail reason belirle
          uint8_t failReason = testResult ? 0 : 1; // 0=PASS, 1=CriticalDrop (default)
          
          // --- Flash'a kaydet ---
          TestRecordHeader rec;
          memset(&rec, 0, sizeof(rec));
          rec.rfidTag = rfid_latched;
          rec.portNumber = rfid_latched_port;
          
          // Operatör adı
          if (espNowSlave) {
            strncpy(rec.operatorName, espNowSlave->getActiveOperator(), sizeof(rec.operatorName) - 1);
          }
          
          // Reçete adı
          strncpy(rec.recipeName, activeTestRecipe.recipeName, sizeof(rec.recipeName) - 1);
          
          // RTC zamanı
          RtcService& rtc = RtcService::getInstance();
          rec.startYear = (uint8_t)rtc.getYear();
          rec.startMonth = (uint8_t)rtc.getMonth();
          rec.startDay = (uint8_t)rtc.getDay();
          rec.startHour = (uint8_t)rtc.getHour();
          rec.startMinute = (uint8_t)rtc.getMinute();
          rec.startSecond = (uint8_t)rtc.getSecond();
          
          rec.durationSec = durationSec;
          rec.startPressure = (int16_t)testStartPressure;
          rec.endPressure = endPressure;
          rec.maxPressure = testRecordMaxPressure;
          rec.totalDrop = totalDropVal;
          rec.windowDrop = windowDropVal;
          rec.targetPressure = (int16_t)activeTestRecipe.inflationPascal;
          rec.acceptableDrop = (int16_t)activeTestRecipe.failThreshold;
          rec.criticalDrop = (int16_t)activeTestRecipe.successDropPascal;
          rec.windowSize = (int16_t)(activeTestRecipe.testDuration > 0 ? activeTestRecipe.testDuration : 30);
          rec.inflationMaxTime = (int16_t)activeTestRecipe.inflationMaxTime;
          rec.stabilizationTime = (int16_t)activeTestRecipe.stabilizationTime;
          rec.reinflateThreshold = (int16_t)activeTestRecipe.reinflateThreshold; // P4
          rec.passed = testResult ? 1 : 0;
          rec.failReason = failReason;
          
          uint32_t savedTestId = TestStorageService::getInstance().saveTest(
              rec, testRecordSamples, testRecordSampleCount);
          
          if (savedTestId > 0) {
            LOG_INFO(LogCategory::CORE, "Test #%lu Flash'a kaydedildi [%d/%d]",
                     savedTestId, TestStorageService::getInstance().getTestCount(),
                     MAX_STORED_TESTS);
          } else {
            LOG_WARN(LogCategory::CORE, "Test Flash'a kaydedilemedi! (Dolu mu?)");
          }
          
          // --- PC'ye TEST_COMPLETED gönder ---
          // NOT: ESP-NOW max 250 byte! Kısa key isimleri kullan, pressure_data gönderme.
          // PC tarafı zaten basınç verisini canlı TEST_DATA akışından topluyor.
          // PC ihtiyaç duyarsa GET_TEST_HISTORY ile flash'tan çekebilir.
          if (espNowSlave && espNowSlave->isInitialized()) {
            // Operatör adı (max 16 char, ESP-NOW boyut limiti)
            char opShort[17];
            memset(opShort, 0, sizeof(opShort));
            strncpy(opShort, espNowSlave->getActiveOperator(), 16);
            
            // Compact recipe string: "p1-p2-p3-p4-p6-p7-p8"
            char rcBuf[48];
            snprintf(rcBuf, sizeof(rcBuf), "%d-%d-%d-%d-%d-%d-%d",
                     activeTestRecipe.inflationMaxTime,
                     activeTestRecipe.inflationPascal,
                     activeTestRecipe.stabilizationTime,
                     activeTestRecipe.reinflateThreshold,
                     activeTestRecipe.failThreshold,
                     activeTestRecipe.testDuration,
                     activeTestRecipe.successDropPascal);
            
            // RTC timestamp string
            char timeStr[24];
            snprintf(timeStr, sizeof(timeStr), "20%02d-%02d-%02dT%02d:%02d:%02d",
                     rec.startYear, rec.startMonth, rec.startDay,
                     rec.startHour, rec.startMinute, rec.startSecond);
            
            // Stack buffer ile JSON oluştur (heap alloc yok)
            char jsonBuf[300];
            int jsonLen = snprintf(jsonBuf, sizeof(jsonBuf),
                "{\"cmd\":\"TEST_COMPLETED\",\"r\":\"%s\",\"did\":\"%s\","
                "\"rfid\":\"%X\",\"port\":%d,\"op\":\"%s\","
                "\"dur\":%d,\"sp\":%d,\"pl\":%d,\"ep\":%d,"
                "\"td\":%d,\"wd\":%d,\"bat\":%d,\"tid\":%lu,"
                "\"sc\":%d,\"rc\":\"%s\",\"rn\":\"%s\",\"ts\":\"%s\"}",
                testResult ? "PASS" : "FAIL",
                espNowSlave->getDeviceId(),
                rfid_latched, rfid_latched_port, opShort,
                durationSec, testStartPressure,
                (int)(testStartPressure - activeTestRecipe.successDropPascal),
                (int)endPressure, (int)totalDropVal, (int)windowDropVal,
                BatteryService::getInstance().getPercentage(),
                savedTestId, testRecordSampleCount,
                rcBuf, activeTestRecipe.recipeName, timeStr);
            
            LOG_INFO(LogCategory::CORE, "TEST_COMPLETED JSON boyut: %d byte (max 250)",
                     jsonLen);
            
            bool sent = espNowSlave->sendToMaster(jsonBuf);
            if (sent) {
              LOG_INFO(LogCategory::CORE, "TEST_COMPLETED PC'ye gönderildi (%s, %d sn)",
                       testResult ? "PASS" : "FAIL", durationSec);
              // YENİ MİMARİ: Test biter bitmez PC'ye anında grafiği (history) yolla!
              if (espNowSlave) {
                espNowSlave->triggerHistorySync();
              }
            } else {
              LOG_ERROR(LogCategory::CORE, "TEST_COMPLETED gönderilemedi! Boyut: %d",
                        jsonLen);
            }
          }
        }

        finishedScreenWritten = false;
        currentTestState = TestState::IDLE;

        // Ana sayfaya dön ve abort tuşunu tekrar aktif yap
        DwinService::getInstance().changePage(2);
        DwinService::getInstance().writeVP(0x7006, 0); // Abort tuşu kilidini aç

        // PERSISTENCE: Do NOT clear activeTestRecipe or rfid_latched here!
        // User must manually Dismount to clear them.

        DwinService::getInstance().writeVP(
            0x601C, 0); // Ready for Next Test (or Mount check)
        DwinService::getInstance().writeVP(0x8018, 0); // Reset result

        // UNLOCK RFID? No, keep it latched until Dismount.
        // But we need to switch UART back if we want to read new tags?
        // NO, if we persist RFID, we assume same tag.
        // Actually, user might want to scan NEW tag in IDLE?
        // "Operatör contayı sökene (Dismount yapana) kadar cihaz o RFID'yi
        // hafızasında tutmalı." So we do NOT unlock RFID reading. We rely on
        // the stored `rfid_latched`.

        LOG_INFO(
            LogCategory::CORE,
            "Test Bitti ve Tahliye Tamamlandı (<= 400Pa). IDLE'a dönüldü.");
        LOG_INFO(LogCategory::RFID,
                 "RFID Bilgisi korunuyor. Yeni test için hazır.");

        // Switch back to RFID UART and re-enable RFID reading.
        // CRITICAL FIX: Test sırasında rfidReadingEnabled=false kalmıştı.
        // RFID debounce tag'i 0 yaptı → sonraki MOUNT "RFID TAG YOK" diyordu.
        // Test bitti → RFID'yi yeniden aç ki yeni MOUNT/AUTH çalışsın.
        switchUart(UartMode::RFID);
        rfidReadingEnabled = true;
        LOG_INFO(LogCategory::RFID, "Test bitti - RFID kilidi açıldı (yeni test için hazır)");

        // CRITICAL: We need to enable "Start Test" button again if Gasket is
        // still mounted? Yes, if Gasket is Mounted (which it is, we didn't
        // dismount), show/enable Start Button.
        // Test bitti — dismount yapılana kadar mount/test start engelle
        dismountRequired = true;
        DwinService::getInstance().writeVP(0x5204, 0); // Butonları gizle, sadece dismount aktif
        LOG_INFO(LogCategory::CORE, "dismountRequired=true — Mount/Test Start engellendi, sadece Dismount aktif");

        // Re-write RFID info to screen just in case
        if (rfid_latched_port > 0) {
          dwinWritePort(rfid_latched_port);
        }
        DwinService::getInstance().writeVP(0x601A, 53);
      }
      break;
    }
    }

    // broadcastTestData() removed — phase/testElapsed now embedded in @S: stream
  }
}

void onESPNowReceived(const char *data) {
  if (espNowSlave) {
    espNowSlave->handleMessage(data);
  }
}
