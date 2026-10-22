#ifndef I_DISPLAY_H
#define I_DISPLAY_H

#include <Arduino.h>

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// DISPLAY INTERFACE
// ═══════════════════════════════════════════════════════════════════

class IDisplay {
public:
    virtual ~IDisplay() = default;
    
    // ═══════════════════════════════════════════════════════════════
    // WRITE OPERATIONS
    // ═══════════════════════════════════════════════════════════════
    
    /**
     * Write a value to a register
     * @param address Register address (e.g. 0x1010)
     * @param value Value to write
     */
    virtual void writeRegister(uint16_t address, uint16_t value) = 0;
    
    /**
     * Write text to a text display area
     * @ address Starting address
     * @param text Null-terminated string
     */
    virtual void writeText(uint16_t address, const char* text) = 0;
    
    // ═══════════════════════════════════════════════════════════════
    // READ OPERATIONS
    // ═══════════════════════════════════════════════════════════════
    
    /**
     * Read a value from a register
     * @param address Register address
     * @return Register value
     */
    virtual uint16_t readRegister(uint16_t address) = 0;
    
    // ═══════════════════════════════════════════════════════════════
    // PAGE CONTROL
    // ═══════════════════════════════════════════════════════════════
    
    /**
     * Set current display page
     * @param pageId Page ID (0 = main, 6 = menu, etc.)
     */
    virtual void setPage(uint16_t pageId) = 0;
    
    /**
     * Get current display page
     * @return Current page ID
     */
    virtual uint16_t getCurrentPage() = 0;
    
    // ═══════════════════════════════════════════════════════════════
    // STATUS
    // ═══════════════════════════════════════════════════════════════
    
    /**
     * Check if display is connected and responsive
     * @return true if connected
     */
    virtual bool isConnected() = 0;
    
    /**
     * Initialize display
     * @return true if successful
     */
    virtual bool begin() = 0;
    
    /**
     * Update/poll display (call periodically)
     */
    virtual void update() = 0;
};

}  // namespace GLT

#endif  // I_DISPLAY_H
