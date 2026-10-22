#ifndef SERIAL_DEBUG_H
#define SERIAL_DEBUG_H

#include <Arduino.h>
#include "services/RFIDService.h"

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// SERIAL DEBUG INTERFACE
// ═══════════════════════════════════════════════════════════════════

class SerialDebug {
public:
    SerialDebug(RFIDService& rfidService);
    ~SerialDebug() = default;
    
    /**
     * Initialize debug interface
     */
    void begin();
    
    /**
     * Update - call in loop() to process serial input
     */
    void update();
    
    /**
     * Print help menu
     */
    void printHelp();
    
    /**
     * Print system status
     */
    void printStatus();
    
private:
    RFIDService& rfidService_;
    String inputBuffer_;
    
    bool dwinMonitorActive_ = false;
    unsigned long lastDwinLog_ = 0;
    
    void processCommand(String cmd);
    void printPrompt();
};

}  // namespace GLT

#endif  // SERIAL_DEBUG_H
