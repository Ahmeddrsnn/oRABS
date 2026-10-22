#ifndef PRESSURE_SERVICE_H
#define PRESSURE_SERVICE_H

#include <Arduino.h>
#include <HardwareSerial.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

namespace GLT {

class PressureService {
public:
  PressureService();

  bool begin(uint8_t rxPin, uint8_t txPin, uint32_t baudrate, uint8_t slaveId,
             uint16_t startReg, uint16_t qty);
  void end();
  void update();

  // Thread-safe single-shot update (for IDLE one-shot reads from main loop)
  void updateBlocking();

  // Quick IDLE read helpers (no delay, no task, no LOG)
  void beginQuick();
  void endQuick();

  // Get filtered pressure in calibrated units
  uint16_t getPressure() const { return currentPressure_; }

  // Get raw pressure value (for debug)
  int32_t getRawValue() const { return lastRawValue_; }

  // Check if sensor is connected
  bool isConnected() const { return sensorConnected_; }

  // Direct Modbus read (bypasses update() cooldown)
  bool directModbusRead(uint8_t* outData);
  void forceConnected(bool state);

  // Dump debug info to Logger
  void printDebugInfo();

  // Continuous streaming
  void setContinuous(bool enable) { continuousEnabled_ = enable; }
  bool isContinuous() const { return continuousEnabled_; }

  // Verbose debug control
  void setVerboseDebug(bool enable) { verboseDebug_ = enable; }
  bool isVerboseDebug() const { return verboseDebug_; }

private:
  HardwareSerial *modbusSerial_;

  // Modbus configuration
  uint8_t slaveId_;
  uint16_t startReg_;
  uint16_t quantity_;

  // Filter variables - Basit hareketli ortalama (20 sample)
  static const int FILTER_BUFFER_SIZE = 20;

  int32_t *rawBuffer_;      // values (int32_t for high calibration multipliers)
  int32_t *filteredBuffer_; // values2
  int rawIndex_;
  int filteredIndex_;

  int64_t totalPressure_; // For averaging (int64_t to handle large sums)

  int32_t lastRawValue_;              // Raw Modbus value (after offset)
  volatile uint16_t currentPressure_; // Final result (thread-safe read)
  volatile bool sensorConnected_;     // Thread-safe connection status

  bool continuousEnabled_ = false;
  unsigned long lastStreamTime_ = 0;
  bool verboseDebug_ = false; // Modbus hata loglarını kontrol et

  // FreeRTOS background task for non-blocking Modbus reads
  TaskHandle_t taskHandle_ = nullptr;
  SemaphoreHandle_t uartMutex_ = nullptr;
  volatile bool taskActive_ = false;

  static void taskEntry(void *param);
  void taskLoop();

  // Modbus RTU helpers
  uint16_t crc16_modbus(const uint8_t *data, size_t len);
  bool modbusRead2Regs(uint8_t slaveId, uint16_t startReg, uint16_t qty,
                       uint8_t outData4[4], uint32_t timeoutMs = 50);
  bool readExact(uint8_t *dst, size_t n, uint32_t timeoutMs);
  void flushRX();
  uint32_t bytesToUint32(uint8_t a, uint8_t b, uint8_t c, uint8_t d);

  // Filter helpers
  unsigned long calculateMedian(uint16_t *data, int size);
};

} // namespace GLT

#endif // PRESSURE_SERVICE_H
