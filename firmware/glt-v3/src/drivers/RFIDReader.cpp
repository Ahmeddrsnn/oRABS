#include "RFIDReader.h"
#include "../core/Logger.h"

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// CONSTRUCTOR
// ═══════════════════════════════════════════════════════════════════

RFIDReader::RFIDReader() {}

// ═══════════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════════

bool RFIDReader::begin(uint8_t rxPin, uint8_t uartNum) {
  uartNum_ = uartNum;
  // Serial1'i kendimiz yönetiyoruz — rdm6300'ün new HardwareSerial
  // yapmasına izin vermiyoruz (memory leak önlenir).
  Serial1.begin(RDM6300_BAUDRATE, SERIAL_8N1, rxPin, -1);
  rdm_.begin(static_cast<Stream*>(&Serial1)); // Stream* overload: sadece pointer atar
  LOG_INFO(LogCategory::RFID, "RFID Reader initialized on RX=%d, UART=%d",
           rxPin, uartNum);
  return true;
}

void RFIDReader::end() {
  // Serial1 flush + end — pin'ler serbest kalır, Modbus tarafı begin() yapabilir
  Serial1.flush();
  Serial1.end();
  LOG_INFO(LogCategory::RFID, "RFID Reader Serial Released (UART%d)", uartNum_);
}

// ═══════════════════════════════════════════════════════════════════
// UPDATE
// ═══════════════════════════════════════════════════════════════════

void RFIDReader::update() {
  // RDM6300 library handles update internally in get_tag_id()
}

// ═══════════════════════════════════════════════════════════════════
// TAG DETECTION
// ═══════════════════════════════════════════════════════════════════

bool RFIDReader::isTagPresent() {
  uint32_t tagId = rdm_.get_tag_id();
  return (tagId != 0);
}

uint32_t RFIDReader::getCurrentTag() { return rdm_.get_tag_id(); }

uint32_t RFIDReader::getNewTag() {
  uint32_t tagId = rdm_.get_new_tag_id();
  if (tagId != 0) {
    LOG_INFO(LogCategory::RFID, "New tag detected: 0x%08X (%u)", tagId, tagId);
  }
  return tagId;
}

void RFIDReader::clearTag() {
  // Read tag to clear it
  rdm_.get_new_tag_id();
}

} // namespace GLT
