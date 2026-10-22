#ifndef DWIN_SERVICE_H
#define DWIN_SERVICE_H

#include <Arduino.h>

namespace GLT {

class DwinService {
public:
  static DwinService &getInstance() {
    static DwinService instance;
    return instance;
  }

  // Initialize UART and state
  void begin(int rxPin, int txPin, long baud = 115200);

  // Main loop update (polling)
  void update();

  // Callbacks for button events
  void setButtonCallback(void (*callback)(uint16_t buttons));

  // Status Updates
  void updateSDStatus(bool inserted);
  void updateESPNowStatus(int status); // 24=Conn, 25=Off, 26=On/Disc
  void updateDateTime(uint8_t h, uint8_t m, uint8_t d, uint8_t mo, uint8_t y);
  void updateBattery(uint16_t iconIndex);     // 0x6010: 20-23
  void updateBatteryRaw(uint16_t raw);        // 0x700A: 0-4095
  void updateBatteryVoltage(uint16_t v_x100); // 0x700C: 1400 = 14.00V
  void
  updatePressure(int32_t rawValue,
                 uint16_t calibrated); // 0x7000: raw/100, 0x7004: calibrated
  void updateGasket(uint16_t rawValue,
                    uint16_t calibrated); // 0x7006: raw, 0x7008: calibrated

  void changePage(uint16_t pageId); // New method

  // Generic VP Access
  void writeVP(uint16_t address, uint16_t value);
  uint16_t readVP(uint16_t address);

  // Direct Text Drawing (0x98 Command)
  void drawString(uint16_t x, uint16_t y, uint8_t fontId, uint16_t fgColor, 
                  uint16_t bgColor, const char* text, uint8_t mode = 0x00, uint8_t dots = 0x00);

  // VP Text Write (0x82 Command) - Writes text directly to VP address
  void writeTextToVP(uint16_t vpAddr, const char* text, uint8_t maxLen = 10);

  // Animation
  void startLoadingAnimation();
  void stopLoadingAnimation();
  void updateAnimation(); // Call often in update() or loop

  // Debug
  void printDebugInfo();
  void printStatusLine(); // Single line compact output

  static void togglePollingLog(bool enable) { showPollingLog_ = enable; }
  static bool isPollingLogEnabled() { return showPollingLog_; }

  // Traffic Log (TX WRITE...)
  static void toggleTrafficLog(bool enable) { showTrafficLog_ = enable; }
  static bool isTrafficLogEnabled() { return showTrafficLog_; }

private:
  DwinService();

  uint16_t lastSentValues_[5] = {0}; // 0:SD, 1:Now, 2:Anim, 3:H, 4:M
  static bool showPollingLog_;
  static bool showTrafficLog_;

  // UART variables
  int rxPin_;
  int txPin_;
  long baud_;

  // Polling state
  unsigned long lastPollTime_;
  uint8_t buffer_[80];

  // Animation State
  bool animationActive_;
  int animationFrame_;
  unsigned long lastAnimTime_;
  int animCommFailCount_ = 0;  // DWIN iletişim watchdog sayacı

  // Callback
  void (*buttonCallback_)(uint16_t buttons);

  // Helpers
  bool pingScreen();  // DWIN'den geçerli frame gelip gelmediğini test eder
  uint16_t calculateCRC(uint8_t *data, uint8_t length);
  void flushRX();
  // Replaced with user's implementation structure
  void sendCommand(uint8_t command, uint16_t address, uint8_t *data,
                   uint8_t dataLen);
  // void dwinWriteWord(uint16_t address, uint16_t value); // Moved to public as
  // writeVP uint16_t dwinReadWord(uint16_t address); // Moved to public as
  // readVP

  // Kept helper for polling logic adaptation
  void pollAndClearButtons();
};

} // namespace GLT

#endif // DWIN_SERVICE_H
