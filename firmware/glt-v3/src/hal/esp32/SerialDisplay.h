#ifndef SERIAL_DISPLAY_H
#define SERIAL_DISPLAY_H

#include "../interfaces/IDisplay.h"
#include <map>

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// SERIAL DISPLAY (Debug Interface)
// ═══════════════════════════════════════════════════════════════════

/**
 * Serial-based display implementation for debugging
 * 
 * Commands (via Serial Monitor):
 *   REG:0x1010=52       - Write register 0x1010 with value 52
 *   REG:0x1010?         - Read register 0x1010
 *   PAGE:0              - Set page to 0
 *   PAGE?               - Get current page
 *   STATUS              - Print all registers
 *   HELP                - Show command help
 */
class SerialDisplay : public IDisplay {
public:
    explicit SerialDisplay(Stream& serial);
    ~SerialDisplay() override = default;
    
    // IDisplay implementation
    void writeRegister(uint16_t address, uint16_t value) override;
    void writeText(uint16_t address, const char* text) override;
    uint16_t readRegister(uint16_t address) override;
    void setPage(uint16_t pageId) override;
    uint16_t getCurrentPage() override;
    bool isConnected() override;
    bool begin() override;
    void update() override;
    
    // Serial-specific methods
    void printHelp();
    void printStatus();
    
private:
    Stream& serial_;
    std::map<uint16_t, uint16_t> registers_;  // Simulated registers
    uint16_t currentPage_;
    String inputBuffer_;
    
    void processCommand(const String& cmd);
    void handleRegisterWrite(const String& cmd);
    void handleRegisterRead(const String& cmd);
};

}  // namespace GLT

#endif  // SERIAL_DISPLAY_H
