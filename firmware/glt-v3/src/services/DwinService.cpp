#include "services/DwinService.h"
#include "core/Logger.h"

namespace GLT {

bool DwinService::showPollingLog_ = false;
bool DwinService::showTrafficLog_ = false;

DwinService::DwinService()
    : rxPin_(18), txPin_(17), baud_(115200), lastPollTime_(0),
      buttonCallback_(nullptr), animationActive_(false), animationFrame_(0),
      lastAnimTime_(0) {}

void DwinService::begin(int rxPin, int txPin, long baud) {
  rxPin_ = rxPin;
  txPin_ = txPin;
  baud_ = baud;

  Serial2.begin(baud_, SERIAL_8N1, rxPin_, txPin_);
  Serial2.setTimeout(50); // Prevent blocking for long periods (default 1000ms)
  // delay(200); // Removed as per user request ("gereksiz delay")

  LOG_INFO(LogCategory::CORE,
           "DWIN Ekran servisi başlatıldı (RX:%d, TX:%d, Baud:%ld)", rxPin_,
           txPin_, baud_);
}

void DwinService::update() {
  // Poll every 200ms
  if (millis() - lastPollTime_ > 200) {
    lastPollTime_ = millis();
    pollAndClearButtons();
  }

  updateAnimation();
}

void DwinService::setButtonCallback(void (*callback)(uint16_t buttons)) {
  buttonCallback_ = callback;
}

// ---------------- STATUS UPDATES ----------------

void DwinService::updateSDStatus(bool inserted) {
  // 30=Inserted, 31=Removed
  uint16_t val = inserted ? 30 : 31;
  if (val != lastSentValues_[0]) {
    LOG_INFO(LogCategory::CORE, "SD Status Update: Inserted=%d, Val=%d",
             inserted, val);
  }
  lastSentValues_[0] = val;
  writeVP(0x5106, val);
}

void DwinService::updateESPNowStatus(int status) {
  // 0x5104: 24=Connected, 25=Apps Off, 26=Apps On but Disconnected
  lastSentValues_[1] = (uint16_t)status;
  writeVP(0x5104, (uint16_t)status);
}

void DwinService::updateDateTime(uint8_t h, uint8_t m, uint8_t d, uint8_t mo,
                                 uint8_t y) {
  lastSentValues_[3] = h;
  lastSentValues_[4] = m;

  // 0x6105: Hour
  writeVP(0x6105, (uint16_t)h);
  // 0x6016: Minute
  writeVP(0x6016, (uint16_t)m);
  // 0x6017: Day
  writeVP(0x6017, (uint16_t)d);
  // 0x6018: Month
  writeVP(0x6018, (uint16_t)mo);
  // 0x6019: Year
  writeVP(0x6019, (uint16_t)y);
}

void DwinService::updateBattery(uint16_t iconIndex) {
  // 0x6010: Battery Icon (20-23)
  writeVP(0x6010, iconIndex);
}

void DwinService::updateBatteryRaw(uint16_t raw) {
  // 0x700A: Raw Battery ADC (0-4095)
  writeVP(0x700A, raw);
}

void DwinService::updateBatteryVoltage(uint16_t v_x100) {
  // 0x700C: Calibrated Voltage (x100)
  writeVP(0x700C, v_x100);
}

void DwinService::updatePressure(int32_t rawValue, uint16_t calibrated) {
  // 0x7000: raw / 100 (basitleştirilmiş)
  uint16_t val100 = (rawValue >= 0) ? (rawValue / 100) : 0;
  writeVP(0x7000, val100);

  // 0x7004: calibrated (0-3000)
  writeVP(0x7004, calibrated);
}

void DwinService::changePage(uint16_t pageId) {
  // Protocol: 5A A5 LEN 82 00 84 5A 01 HIGHPAGE LOWPAGE CRC_L CRC_H
  // Use sendCommand with proper CRC calculation
  
  // Payload: Command(82) + Address(0084) + Data(5A 01 00 PAGE)
  uint8_t payload[] = {
      0x82,                    // Write Command
      0x00, 0x84,              // Address (Page Switching)
      0x5A, 0x01,              // Fixed Data
      (uint8_t)(pageId >> 8),  // Page High
      (uint8_t)(pageId & 0xFF) // Page Low
  };
  
  // Calculate CRC on payload
  uint16_t crc = calculateCRC(payload, sizeof(payload));
  
  // Build complete packet: Header + Payload + CRC
  uint8_t packet[3 + sizeof(payload) + 2]; // Header(3) + Payload(7) + CRC(2)
  packet[0] = 0x5A;
  packet[1] = 0xA5;
  packet[2] = sizeof(payload) + 2; // Length = Payload + CRC
  memcpy(&packet[3], payload, sizeof(payload));
  packet[3 + sizeof(payload)] = crc & 0xFF;        // CRC Low
  packet[3 + sizeof(payload) + 1] = (crc >> 8) & 0xFF; // CRC High
  
  Serial2.write(packet, sizeof(packet));
  LOG_INFO(LogCategory::CORE, "DWIN Sayfa Değiştirildi: %d (CRC: 0x%04X)", pageId, crc);
}

// ---------------- ANIMATION ----------------

void DwinService::startLoadingAnimation() {
  animationActive_ = true;
  animationFrame_ = 0;
  lastAnimTime_ = millis();
}

void DwinService::stopLoadingAnimation() { animationActive_ = false; }

void DwinService::updateAnimation() {
  if (!animationActive_)
    return;

  if (millis() - lastAnimTime_ < 33) return; // ~30fps throttle
  lastAnimTime_ = millis();

  // DWIN iletişim watchdog: önceki frame'i geri oku (33ms gecikmeyle kontrol)
  if (millis() > 15000 && animationFrame_ > 0) {
    uint16_t expectedPrev = (animationFrame_ == 0) ? 35 : (animationFrame_ - 1);
    uint16_t readBack = readVP(0x6014);
    if (readBack != expectedPrev) {
      animCommFailCount_++;
      if (animCommFailCount_ >= 10) {
        animationActive_ = false;
        LOG_ERROR(LogCategory::CORE, "DWIN iletisim KOPTU! Animasyon durduruldu (beklenen:%d, okunan:%d)",
                  expectedPrev, readBack);
        return;
      }
    } else {
      animCommFailCount_ = 0;
    }
  }

  // Yeni frame'i yaz
  lastSentValues_[2] = animationFrame_;
  writeVP(0x6014, animationFrame_);

  // Standard Increment
  animationFrame_++;
  if (animationFrame_ > 35) {
    animationFrame_ = 0;
  }
}

void DwinService::printDebugInfo() {
  Serial.println(
      "\n╔═══════════════════════════════════════════════════════════════╗");
  Serial.println(
      "║  DWIN Ekran Son Giden Veriler                                 ║");
  Serial.println(
      "╠═══════════════════════════════════════════════════════════════╣");
  Serial.printf(
      "║  VP 0x5106 (SD Durum):   %-4d (30=Takılı, 31=Yok)        ║\n",
      lastSentValues_[0]);
  Serial.printf(
      "║  VP 0x5104 (ESP-NOW):    %-4d (24=Bağlı, 26=Tara)        ║\n",
      lastSentValues_[1]);
  Serial.printf(
      "║  VP 0x5102 (Animasyon):  0x%02X (0-35 BCD)               ║\n",
      lastSentValues_[2]);
  Serial.printf(
      "║  VP 0x5000 (Saat):       %02d:%02d                           ║\n",
      lastSentValues_[3], lastSentValues_[4]);
  Serial.println(
      "╚═══════════════════════════════════════════════════════════════╝");
}

void DwinService::printStatusLine() {
  // TIM:18:05:00 SD:30 NOW:24 ANIM:0x0C
  char buf[128];
  snprintf(buf, sizeof(buf), "TIM:%02d:%02d SD:%d NOW:%d ANIM:0x%02X",
           lastSentValues_[3], lastSentValues_[4], // H, M
           lastSentValues_[0],                     // SD
           lastSentValues_[1],                     // NOW
           lastSentValues_[2]                      // ANIM
  );
  Serial.println(buf);
}

// ---------------- CRC16 MODBUS (A001) ----------------
// --- 1. CRC HESAPLAMA ---
// Modbus CRC-16 (Polynomial: 0xA001, Init: 0xFFFF)
uint16_t DwinService::calculateCRC(uint8_t *data, uint8_t length) {
  uint16_t crc = 0xFFFF;
  for (int i = 0; i < length; i++) {
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

// --- RX Buffer Temizleme ---
void DwinService::flushRX() {
  while (Serial2.available())
    Serial2.read();
}

// --- 2. KOMUT GÖNDERME ---
void DwinService::sendCommand(uint8_t command, uint16_t address, uint8_t *data,
                              uint8_t dataLen) {
  uint8_t payloadLen = 1 + 2 + dataLen;
  uint8_t totalLen = payloadLen + 2; // +2 for CRC

  uint8_t tx[64];
  uint8_t idx = 0;

  // Header
  tx[idx++] = 0x5A;
  tx[idx++] = 0xA5;
  tx[idx++] = totalLen;

  // Komut ve Adres
  tx[idx++] = command;
  tx[idx++] = (address >> 8) & 0xFF; // Address High
  tx[idx++] = (address >> 0) & 0xFF; // Address Low

  // Veri (Varsa)
  if (data != NULL && dataLen > 0) {
    for (int i = 0; i < dataLen; i++) {
      tx[idx++] = data[i];
    }
  }

  // CRC Hesapla (Uzunluk byte'ından sonraki kısımdan başlar: Cmd...Data)
  // tx[3] (Cmd) adresinden itibaren (idx - 3) kadar byte
  uint16_t crc = calculateCRC(&tx[3], idx - 3);

  tx[idx++] = crc & 0xFF;        // CRC Low Byte
  tx[idx++] = (crc >> 8) & 0xFF; // CRC High Byte

  // Paketi gönder
  Serial2.write(tx, idx);
  Serial2.flush();

  // Debug Log (To match previous verification visibility)
  // Serial.printf("TX CMD 0x%02X ADDR 0x%04X LEN %d\n", command, address,
  // dataLen);
}

// --- 3. WRITE WORD (16-bit Yazma) ---
void DwinService::writeVP(uint16_t address, uint16_t value) {
  uint8_t data[2];
  data[0] = (value >> 8) & 0xFF; // High Byte
  data[1] = (value >> 0) & 0xFF; // Low Byte

  sendCommand(0x82, address, data, 2);

  // Debug mirroring previous behavior for verification (Compact format)
  if (address == 0x5102 && showTrafficLog_) {
    // Keep User's "TX WRITE" format request from earlier
    Serial.printf("TX WRITE VP 0x%04X = 0x%04X | ", address, value);
    // No newline
  }
}

// --- 3.5. DRAW STRING (0x98 Command - Direct Text Drawing) ---
void DwinService::drawString(uint16_t x, uint16_t y, uint8_t fontId, 
                             uint16_t fgColor, uint16_t bgColor, 
                             const char* text, uint8_t mode, uint8_t dots) {
  if (!text) return;
  
  uint8_t textLen = strlen(text);
  if (textLen == 0) return;
  
  // Command format: 5A A5 [Len] 98 [X_H] [X_L] [Y_H] [Y_L] [Font] [Mode] [Dots] [FG_H] [FG_L] [BG_H] [BG_L] [String...] [CRC_L] [CRC_H]
  // Fixed part byte count: Cmd(1) + X(2) + Y(2) + Font(1) + Mode(1) + Dots(1) + FG(2) + BG(2) = 12 bytes
  uint8_t payloadLen = 12 + textLen;
  uint8_t totalLen = payloadLen + 2; // +2 for CRC
  
  uint8_t buffer[128]; // Max string length ~100 chars
  if (totalLen + 3 > 128) return; // Overflow protection
  
  uint8_t idx = 0;
  
  // Header
  buffer[idx++] = 0x5A;
  buffer[idx++] = 0xA5;
  buffer[idx++] = totalLen;
  
  // Payload starts here (for CRC calculation)
  uint8_t payloadStart = idx;
  
  buffer[idx++] = 0x98; // Draw String Command
  buffer[idx++] = (x >> 8) & 0xFF;   // X High
  buffer[idx++] = x & 0xFF;          // X Low
  buffer[idx++] = (y >> 8) & 0xFF;   // Y High
  buffer[idx++] = y & 0xFF;          // Y Low
  buffer[idx++] = fontId;            // Font ID
  buffer[idx++] = mode;              // Mode (0x00 = normal)
  buffer[idx++] = dots;              // Dots (0x00 = default)
  buffer[idx++] = (fgColor >> 8) & 0xFF; // Foreground Color High
  buffer[idx++] = fgColor & 0xFF;        // Foreground Color Low
  buffer[idx++] = (bgColor >> 8) & 0xFF; // Background Color High
  buffer[idx++] = bgColor & 0xFF;        // Background Color Low
  
  // Copy string
  memcpy(&buffer[idx], text, textLen);
  idx += textLen;
  
  // Calculate CRC on payload (from command to end of string)
  uint16_t crc = calculateCRC(&buffer[payloadStart], payloadLen);
  
  buffer[idx++] = crc & 0xFF;        // CRC Low
  buffer[idx++] = (crc >> 8) & 0xFF; // CRC High
  
  // Send via Serial2 (DWIN display)
  Serial2.write(buffer, idx);
  Serial2.flush();
  
  if (showTrafficLog_) {
    Serial.printf("TX DRAW_STRING @ (%d,%d) Font:%d \"%s\" CRC:0x%04X | ", x, y, fontId, text, crc);
  }
}

// --- 3.6. WRITE TEXT TO VP (0x82 Command - VP Address Write) ---
void DwinService::writeTextToVP(uint16_t vpAddr, const char* text, uint8_t maxLen) {
  if (!text) return;
  
  uint8_t textLen = strlen(text);
  if (textLen == 0) return;
  if (textLen > maxLen) textLen = maxLen; // Truncate to max length
  
  // Packet format: 5A A5 [Len] 82 [VP_H] [VP_L] [Text bytes...] [CRC_L] [CRC_H]
  // Payload: Cmd(1) + VP(2) + Text(N)
  uint8_t payloadLen = 1 + 2 + textLen;
  uint8_t totalLen = payloadLen + 2; // +2 for CRC
  
  uint8_t buffer[128];
  if (totalLen + 3 > 128) return; // Overflow protection
  
  uint8_t idx = 0;
  
  // Header
  buffer[idx++] = 0x5A;
  buffer[idx++] = 0xA5;
  buffer[idx++] = totalLen;
  
  // Payload starts here (for CRC calculation)
  uint8_t payloadStart = idx;
  
  buffer[idx++] = 0x82; // Write Command
  buffer[idx++] = (vpAddr >> 8) & 0xFF;  // VP High Byte
  buffer[idx++] = vpAddr & 0xFF;         // VP Low Byte
  
  // Copy text
  for (uint8_t i = 0; i < textLen; i++) {
    buffer[idx++] = (uint8_t)text[i];
  }
  
  // Calculate CRC on payload
  uint16_t crc = calculateCRC(&buffer[payloadStart], payloadLen);
  
  buffer[idx++] = crc & 0xFF;        // CRC Low
  buffer[idx++] = (crc >> 8) & 0xFF; // CRC High
  
  // Send via Serial2 (DWIN display)
  Serial2.write(buffer, idx);
  Serial2.flush();
  
  if (showTrafficLog_) {
    Serial.printf("TX WRITE_TEXT VP:0x%04X \"%s\" (Len:%d) CRC:0x%04X | ", vpAddr, text, textLen, crc);
  }
}

// --- 4. READ WORD (16-bit Okuma) ---
uint16_t DwinService::readVP(uint16_t address) {
  flushRX();

  // Okuma isteği: Word Count = 1
  uint8_t data[1] = {0x01};
  sendCommand(0x83, address, data, 1);

  // Cevabı bekle
  uint32_t t0 = millis();
  uint8_t headerFound = 0;

  // Header senkronizasyonu (Timeout Reduced to 20ms for speed)
  while (millis() - t0 < 20) {
    if (Serial2.available()) {
      uint8_t b = Serial2.read();
      if (headerFound == 0 && b == 0x5A)
        headerFound = 1;
      else if (headerFound == 1 && b == 0xA5) {
        headerFound = 2;
        break;
      } else
        headerFound = 0;
    }
  }

  if (headerFound != 2)
    return 0;

  // Uzunluk byte'ını oku
  uint8_t rxBuffer[128];
  if (Serial2.readBytes(rxBuffer, 1) != 1)
    return 0;
  uint8_t len = rxBuffer[0];

  if (len < 8 || len > sizeof(rxBuffer))
    return 0;

  if (Serial2.readBytes(rxBuffer, len) != len)
    return 0;

  // CRC Kontrol
  uint16_t receivedCRC = rxBuffer[len - 2] | (rxBuffer[len - 1] << 8);
  uint16_t calculatedCRC = calculateCRC(rxBuffer, len - 2);

  if (receivedCRC != calculatedCRC)
    return 0;

  // Adres doğrulaması: yanıttaki VP adresinin istenen adresle eşleştiğini kontrol et
  uint16_t respAddr = (rxBuffer[1] << 8) | rxBuffer[2];
  if (respAddr != address)
    return 0;

  // Veri: rxBuffer[4] (High), rxBuffer[5] (Low) - Offset map based on user code
  // Cmd(0) + Addr(1,2) + Len(3) + Data(4,5) ...
  // Wait, user code said: rxBuffer starts reading AFTER len byte.
  // "Serial2.readBytes(rxBuffer, len)" -> rxBuffer[0] is CMD.
  // User code: if (rxBuffer[0] != CMD_READ ...
  // User code: readValue = (rxBuffer[4] << 8) | rxBuffer[5];
  // Correct.

  uint16_t readValue = (rxBuffer[4] << 8) | rxBuffer[5];
  return readValue;
}

void DwinService::pollAndClearButtons() {
  uint16_t VP_BTN = 0x5900;

  // Use User's primitive
  uint16_t val = readVP(VP_BTN);

  // DwinReadWord returns 0 on error OR if value is 0.
  // Assuming 0 means no button or read fail, we do nothing.
  // To match previous logic: "if val == 0 return".
  if (val == 0x0000) {
    // Log "Alive" check occasionally if requested?
    static unsigned long lastSuccess = 0;
    if (millis() - lastSuccess > 5000) {
      lastSuccess = millis();
      if (showPollingLog_) {
        LOG_INFO(LogCategory::CORE, "DWIN Ekran Bağlantısı Aktif (Polling...)");
      }
    }
    return;
  }

  // Check if any button pressed
  LOG_INFO(LogCategory::CORE, "DWIN Button: 0x%04X", val);

  // Notify application
  if (buttonCallback_) {
    buttonCallback_(val);
  }

  // FORCE CLEAR VP -> 0x0000 (User Logic)
  writeVP(VP_BTN, 0x0000);
}

// updatePressure already exists above (line 71)

#ifdef DISPLAY
#undef DISPLAY
#endif

void DwinService::updateGasket(uint16_t rawValue, uint16_t calibrated) {
  if (showTrafficLog_) {
    LOG_INFO(LogCategory::UI, "DWIN Gasket Update: Raw=%d, Cal=%d", rawValue,
             calibrated);
  }

  // 0x700A: Raw Value scaled to 8000 max (rawValue * 2, capped at 8000)
  uint16_t scaledRaw = (rawValue * 2 > 8000) ? 8000 : (rawValue * 2);
  writeVP(0x700A, scaledRaw);

  // 0x7008: Calibrated Pressure (capped at 8000)
  uint16_t cappedCal = (calibrated > 8000) ? 8000 : calibrated;
  writeVP(0x7008, cappedCal);
}

} // namespace GLT
