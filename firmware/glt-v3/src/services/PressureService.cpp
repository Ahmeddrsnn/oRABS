#include "services/PressureService.h"
#include "config.h"
#include "core/Logger.h"

namespace GLT {

PressureService::PressureService()
    : modbusSerial_(nullptr), slaveId_(0), startReg_(0), quantity_(0),
      sensorConnected_(false), rawBuffer_(nullptr), filteredBuffer_(nullptr),
      rawIndex_(0), filteredIndex_(0), totalPressure_(0), lastRawValue_(0),
      currentPressure_(0) {
  uartMutex_ = xSemaphoreCreateMutex();
}

// ================= CRC16 MODBUS (poly 0xA001) =================
uint16_t PressureService::crc16_modbus(const uint8_t *data, size_t len) {
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

// ============ Yardımcı: RX buffer temizle ============
void PressureService::flushRX() {
  while (modbusSerial_->available())
    modbusSerial_->read();
}

// ============ Yardımcı: n byte'ı timeout ile tam oku ============
bool PressureService::readExact(uint8_t *dst, size_t n, uint32_t timeoutMs) {
  uint32_t t0 = millis();
  size_t got = 0;
  while (got < n && (millis() - t0) < timeoutMs) {
    int c = modbusSerial_->read();
    if (c >= 0)
      dst[got++] = (uint8_t)c;
    else
      delay(1);
  }
  return (got == n);
}

// ============ 4 byte -> uint32_t ============
uint32_t PressureService::bytesToUint32(uint8_t a, uint8_t b, uint8_t c,
                                        uint8_t d) {
  return ((uint32_t)a << 24) | ((uint32_t)b << 16) | ((uint32_t)c << 8) |
         (uint32_t)d;
}

// ============ Modbus 0x03 isteği gönder + cevap oku ============
bool PressureService::modbusRead2Regs(uint8_t slaveId, uint16_t startReg,
                                      uint16_t qty, uint8_t outData4[4],
                                      uint32_t timeoutMs) {
  uint8_t req[8];
  req[0] = slaveId;
  req[1] = 0x03; // Read Holding Registers
  req[2] = (startReg >> 8) & 0xFF;
  req[3] = (startReg >> 0) & 0xFF;
  req[4] = (qty >> 8) & 0xFF;
  req[5] = (qty >> 0) & 0xFF;

  uint16_t crc = crc16_modbus(req, 6);
  req[6] = (crc >> 0) & 0xFF; // CRC Low  (little-endian)
  req[7] = (crc >> 8) & 0xFF; // CRC High

  flushRX();
  modbusSerial_->write(req, sizeof(req));
  modbusSerial_->flush();

  // Beklenen normal cevap: [id][03][bytecount=4][data0..3][crclo][crchi] => 9
  // byte
  uint8_t hdr[3];
  if (!readExact(hdr, 3, timeoutMs))
    return false;

  if (hdr[0] != slaveId || hdr[1] != 0x03) {
    // Exception frame olabilir - buffer'ı boşalt
    uint8_t rest[2];
    bool gotRest = readExact(rest, 2, timeoutMs);

    // Throttle: Sadece verbose modda veya her 30 saniyede bir logla
    static unsigned long lastHeaderErr = 0;
    if (verboseDebug_ || (millis() - lastHeaderErr > 30000)) {
      if (gotRest) {
        LOG_WARN(LogCategory::SENSOR,
                 "Bad Modbus header. Got: %02X %02X %02X (rest %02X %02X)",
                 hdr[0], hdr[1], hdr[2], rest[0], rest[1]);
      } else {
        LOG_WARN(LogCategory::SENSOR, "Bad Modbus header. Got: %02X %02X %02X",
                 hdr[0], hdr[1], hdr[2]);
      }
      lastHeaderErr = millis();
    }
    return false;
  }

  uint8_t byteCount = hdr[2];
  if (byteCount != 4) {
    // Throttle: Sadece verbose modda veya her 30 saniyede bir logla
    static unsigned long lastByteCountErr = 0;
    if (verboseDebug_ || (millis() - lastByteCountErr > 30000)) {
      LOG_WARN(LogCategory::SENSOR, "Unexpected byteCount=%u (expected 4)",
               byteCount);
      lastByteCountErr = millis();
    }

    // Yanlış veri boyutu - boşalt
    uint8_t dump[64];
    size_t toRead = (size_t)byteCount + 2; // data + crc
    if (toRead > sizeof(dump))
      toRead = sizeof(dump);
    readExact(dump, toRead, timeoutMs);
    return false;
  }

  uint8_t payload[4];
  uint8_t crcBytes[2];
  if (!readExact(payload, 4, timeoutMs))
    return false;
  if (!readExact(crcBytes, 2, timeoutMs))
    return false;

  // CRC kontrol: hdr(3) + payload(4) = 7 byte
  uint8_t frame7[7];
  memcpy(frame7, hdr, 3);
  memcpy(frame7 + 3, payload, 4);
  uint16_t crcCalc = crc16_modbus(frame7, 7);
  uint16_t crcRx =
      (uint16_t)crcBytes[0] | ((uint16_t)crcBytes[1] << 8); // low,high

  if (crcCalc != crcRx) {
    // Throttle: Sadece verbose modda veya her 30 saniyede bir logla
    static unsigned long lastCrcErr = 0;
    if (verboseDebug_ || (millis() - lastCrcErr > 30000)) {
      LOG_WARN(LogCategory::SENSOR, "CRC mismatch! calc=%04X rx=%04X", crcCalc,
               crcRx);
      lastCrcErr = millis();
    }
    return false;
  }

  memcpy(outData4, payload, 4);
  return true;
}

bool PressureService::begin(uint8_t rxPin, uint8_t txPin, uint32_t baudrate,
                            uint8_t slaveId, uint16_t startReg, uint16_t qty) {
  LOG_INFO(LogCategory::SENSOR,
           "Pressure Service başlatılıyor (Modbus RTU: RX=%d, TX=%d)", rxPin,
           txPin);

  slaveId_ = slaveId;
  startReg_ = startReg;
  quantity_ = qty;

  // Allocate buffers
  if (!rawBuffer_)
    rawBuffer_ = new int32_t[FILTER_BUFFER_SIZE];
  if (!filteredBuffer_)
    filteredBuffer_ = new int32_t[FILTER_BUFFER_SIZE];

  memset(rawBuffer_, 0, FILTER_BUFFER_SIZE * sizeof(int32_t));
  memset(filteredBuffer_, 0, FILTER_BUFFER_SIZE * sizeof(int32_t));

  // Serial1 başlat (DWIN Serial2'de olduğu için Modbus Serial1'de)
  modbusSerial_ = &Serial1;
  modbusSerial_->begin(baudrate, SERIAL_8N1, rxPin, txPin);
  delay(100); // Serial stabilizasyon

  // Test okuma
  uint8_t testData[4];
  sensorConnected_ = modbusRead2Regs(slaveId_, startReg_, qty, testData, 100);

  if (sensorConnected_) {
    int32_t raw_int32 =
        (int32_t)bytesToUint32(testData[0], testData[1], testData[2], testData[3]) / 1000;
    int32_t raw_with_offset =
        raw_int32 - Config::app.calibration.pressure_zero_offset;
    LOG_INFO(LogCategory::SENSOR,
             "Modbus Basınç Sensörü Bulundu (ID:%d, Reg:%d) - Serial1",
             slaveId_, startReg_);
    LOG_INFO(LogCategory::SENSOR, "Test okuma: Raw int32=%ld, With offset=%d",
             raw_int32, raw_with_offset);
  } else {
    LOG_ERROR(
        LogCategory::SENSOR,
        "Modbus Basınç Sensörü Bulunamadı! (Check wiring/power/slave ID)");
  }

  // Create FreeRTOS task (once) and activate it
  if (!taskHandle_) {
    xTaskCreatePinnedToCore(taskEntry, "pressure", 4096, this, 2,
                            &taskHandle_, 0); // Core 0 (main loop = Core 1)
    LOG_INFO(LogCategory::SENSOR, "Pressure FreeRTOS task oluşturuldu (Core 0)");
  }
  taskActive_ = true;

  return sensorConnected_;
}

void PressureService::end() {
  // Signal the task to stop
  taskActive_ = false;

  // Wait for current Modbus read to finish (mutex ensures no race)
  if (uartMutex_) {
    xSemaphoreTake(uartMutex_, pdMS_TO_TICKS(200));
    xSemaphoreGive(uartMutex_);
  }

  // Now safe to close serial — task won't touch it
  if (modbusSerial_) {
    modbusSerial_->end();
    modbusSerial_ = nullptr;
  }
  sensorConnected_ = false;
  LOG_INFO(LogCategory::SENSOR, "Pressure Service Stopped (Serial Released)");
}
void PressureService::beginQuick() {
  // Hafif başlatma: IDLE periyodik okuma için.
  // DİKKAT: taskActive_ == true ise çağrılmamalı — Core 0 task çakışır.
  if (taskActive_) {
    LOG_WARN(LogCategory::SENSOR, "beginQuick() reddedildi: task hâlâ aktif!");
    return;
  }
  modbusSerial_ = &Serial1;
  sensorConnected_ = true;
}

void PressureService::endQuick() {
  // Hafif kapatma: pointer temizle, task'a dokunma.
  modbusSerial_ = nullptr;
  sensorConnected_ = false;
}
unsigned long PressureService::calculateMedian(uint16_t *data, int size) {
  uint16_t sortedData[size];
  memcpy(sortedData, data, size * sizeof(uint16_t));

  for (int i = 0; i < size - 1; i++) {
    for (int j = 0; j < size - i - 1; j++) {
      if (sortedData[j] > sortedData[j + 1]) {
        uint16_t temp = sortedData[j];
        sortedData[j] = sortedData[j + 1];
        sortedData[j + 1] = temp;
      }
    }
  }

  if (size % 2 == 0) {
    return (sortedData[size / 2 - 1] + sortedData[size / 2]) / 2;
  } else {
    return sortedData[size / 2];
  }
}

void PressureService::update() {
  // Return immediately if Serial is not initialized (Service Stopped)
  if (!modbusSerial_) {
    return;
  }

  // Hot-plug / Retry Logic
  if (!sensorConnected_) {
    static unsigned long lastRetry = 0;
    if (millis() - lastRetry > 1000) {
      lastRetry = millis();
      uint8_t testData[4];
      if (modbusRead2Regs(slaveId_, startReg_, quantity_, testData, 60)) {
        sensorConnected_ = true;
        // Throttle: Sadece verbose modda veya her 30 saniyede bir
        static unsigned long lastReconnect = 0;
        if (verboseDebug_ || (millis() - lastReconnect > 30000)) {
          LOG_INFO(LogCategory::SENSOR,
                   "Sensor bağlantısı kuruldu (Hot-plug/Retry)");
          lastReconnect = millis();
        }
      }
    }
    return;
  }

  // MODBUS SIKLIĞI KONTROLÜ
  // Çok sık sorgu sensörü veya hattı yorabilir. 50ms ara verelim.
  static unsigned long lastUpdateCall = 0;
  if (millis() - lastUpdateCall < 50) {
    return;
  }
  lastUpdateCall = millis();

  uint8_t data4[4];
  // Timeout 30ms (Kullanıcı isteği - Sensörle alakalıymış)
  bool ok = modbusRead2Regs(slaveId_, startReg_, quantity_, data4, 30);

  if (ok) {
    // Modbus payload: A, B, C, D (4 bytes)
    uint8_t A = data4[0];
    uint8_t B = data4[1];
    uint8_t C = data4[2];
    uint8_t D = data4[3];

    // int32 oluştur ve 10'a böl (sensör 10 katı gönderiyor)
    // Two's complement: cast ÖNCE yapılmalı, bölme sonra — negatif değerler korunsun
    int32_t raw_int32 = (int32_t)bytesToUint32(A, B, C, D) / 10;

    // Offsetli değer hesapla (filtreleme için)
    int32_t offsetPressure =
        raw_int32 - Config::app.calibration.pressure_zero_offset;

    // RAW DEĞERİ SAKLA (Offsetsiz - Kullanıcı isteği)
    lastRawValue_ = raw_int32;

    // Debug: İlk birkaç okumada raw değerleri göster
    static int debugCount = 0;
    if (debugCount < 5) {
      LOG_INFO(LogCategory::SENSOR,
               "Raw data: A=%02X B=%02X C=%02X D=%02X | int32=%ld | "
               "offsetPressure=%d",
               A, B, C, D, raw_int32, offsetPressure);
      debugCount++;
    }

    // Buffer is int32_t now - no overflow issue
    // Clamp negative values to 0
    if (offsetPressure < 0) {
      offsetPressure = 0;
    }

    rawBuffer_[rawIndex_] = offsetPressure;

    // Reset error counter on success
    static int errCount = 0;
    errCount = 0;
  } else {
    // Log sensor read failure (throttled)
    static unsigned long lastErr = 0;
    if (verboseDebug_ || (millis() - lastErr > 30000)) {
      LOG_WARN(LogCategory::SENSOR, "Modbus basınç okuma hatası! (Slave:%d)",
               slaveId_);
      lastErr = millis();
    }

    // Handle consecutive errors
    static int errCount = 0;
    errCount++;

    if (errCount > 10) {        // ~1 second of failures (10Hz)
      sensorConnected_ = false; // Trigger reconnection logic in next loop
      errCount = 0;
    }

    // ALWAYS keep previous value - NEVER use 0
    if (rawIndex_ > 0)
      rawBuffer_[rawIndex_] = rawBuffer_[rawIndex_ - 1];
    else
      rawBuffer_[rawIndex_] = rawBuffer_[FILTER_BUFFER_SIZE - 1];
  }

  rawIndex_++;
  if (rawIndex_ >= FILTER_BUFFER_SIZE)
    rawIndex_ = 0;

  // DIRECT VALUE (No Filter) - User Request
  // Buffer is kept updated just in case but output is instantaneous
  int32_t instantVal =
      rawBuffer_[(rawIndex_ > 0) ? (rawIndex_ - 1) : (FILTER_BUFFER_SIZE - 1)];

  // Apply multiplier for final calibration
  // PC'den gelen multiplier: 1.0 = nötr (%100.0), 1.001 = %100.1
  float calVal =
      (float)instantVal * (Config::app.calibration.pressure_multiplier / 100.0f);

  // Clamp to [0, 3000]
  if (calVal < 0)
    calVal = 0;
  if (calVal > 3000)
    calVal = 3000;
  currentPressure_ = (uint16_t)calVal;

  // Continuous Stream

  if (continuousEnabled_) {
    unsigned long now = millis();
    if (now - lastStreamTime_ > 100) { // 10Hz stream
      LOG_INFO(LogCategory::SENSOR,
               "STREAM > Cal: %d | Raw: %d | ZeroOff: %d | Mul: %.2f",
               currentPressure_, lastRawValue_,
               Config::app.calibration.pressure_zero_offset,
               Config::app.calibration.pressure_multiplier);
      lastStreamTime_ = now;
    }
  }
}

// ================= FreeRTOS Task =================
void PressureService::taskEntry(void *param) {
  ((PressureService *)param)->taskLoop();
}

void PressureService::taskLoop() {
  while (true) {
    if (taskActive_ && uartMutex_) {
      if (xSemaphoreTake(uartMutex_, pdMS_TO_TICKS(100))) {
        if (taskActive_) { // double-check after acquiring mutex
          update();
        }
        xSemaphoreGive(uartMutex_);
      }
    }
    vTaskDelay(pdMS_TO_TICKS(50)); // ~20Hz max (throttle inside update() also limits)
  }
}

void PressureService::updateBlocking() {
  if (uartMutex_ && xSemaphoreTake(uartMutex_, pdMS_TO_TICKS(200))) {
    update();
    xSemaphoreGive(uartMutex_);
  }
}

void PressureService::printDebugInfo() {
  if (!sensorConnected_) {
    LOG_INFO(LogCategory::SENSOR, "Basınç Sensörü: BAĞLI DEĞİL");
    return;
  }

  LOG_INFO(LogCategory::SENSOR, "--- BASINÇ SENSÖRÜ DEBUG (MODBUS RTU) ---");
  LOG_INFO(LogCategory::SENSOR, "Durum: Bağlı (Slave ID: %d, Reg: %d)",
           slaveId_, startReg_);
  LOG_INFO(LogCategory::SENSOR, "Ham (after offset): %d", lastRawValue_);
  LOG_INFO(LogCategory::SENSOR, "Filtreli (Cal): %d", currentPressure_);
  LOG_INFO(LogCategory::SENSOR, "Kalibrasyon: ZeroOffset=%d, Multiplier=%.2f",
           Config::app.calibration.pressure_zero_offset,
           Config::app.calibration.pressure_multiplier);

  LOG_INFO(LogCategory::SENSOR, "Ortalama (Total/%d): %lu", FILTER_BUFFER_SIZE,
           totalPressure_ / FILTER_BUFFER_SIZE);
}

bool PressureService::directModbusRead(uint8_t* outData) {
  if (!modbusSerial_) return false;
  // Thread-safe: Core 1 (main loop) ile Core 0 (FreeRTOS Modbus task) çakışmasını önle
  if (!uartMutex_ || xSemaphoreTake(uartMutex_, pdMS_TO_TICKS(100)) != pdTRUE) {
    return false; // Mutex alınamadı — timeout veya mutex yok
  }
  bool ok = modbusRead2Regs(slaveId_, startReg_, quantity_, outData, 100);
  xSemaphoreGive(uartMutex_);
  return ok;
}

void PressureService::forceConnected(bool state) {
  sensorConnected_ = state;
}

} // namespace GLT
