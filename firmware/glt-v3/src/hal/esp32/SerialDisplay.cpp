#include "SerialDisplay.h"
#include "../../core/Logger.h"

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// CONSTRUCTOR
// ═════════════════════════════════════════════════════════════════

SerialDisplay::SerialDisplay(Stream& serial)
    : serial_(serial)
    , currentPage_(0)
{
}

// ═══════════════════════════════════════════════════════════════════
// IDISPLAY IMPLEMENTATION
// ═══════════════════════════════════════════════════════════════════

bool SerialDisplay::begin() {
    LOG_INFO(LogCategory::UI, "SerialDisplay initialized (debug mode)");
    printHelp();
    return true;
}

void SerialDisplay::writeRegister(uint16_t address, uint16_t value) {
    registers_[address] = value;
    LOG_DEBUG(LogCategory::UI, "Write  REG[0x%04X] = %u (0x%04X)", 
             address, value, value);
}

void SerialDisplay::writeText(uint16_t address, const char* text) {
    // For text, we'll just log it (no actual display)
    LOG_DEBUG(LogCategory::UI, "Write TEXT[0x%04X] = \"%s\"", address, text);
}

uint16_t SerialDisplay::readRegister(uint16_t address) {
    auto it = registers_.find(address);
    uint16_t value = (it != registers_.end()) ? it->second : 0;
    LOG_DEBUG(LogCategory::UI, "Read   REG[0x%04X] = %u (0x%04X)", 
             address, value, value);
    return value;
}

void SerialDisplay::setPage(uint16_t pageId) {
    currentPage_ = pageId;
    LOG_INFO(LogCategory::UI, "Page changed: %u", pageId);
}

uint16_t SerialDisplay::getCurrentPage() {
    return currentPage_;
}

bool SerialDisplay::isConnected() {
    return true;  // Serial is always "connected"
}

void SerialDisplay::update() {
    // Check for incoming Serial commands
    while (serial_.available()) {
        char c = serial_.read();
        
        if (c == '\n' || c == '\r') {
            if (inputBuffer_.length() > 0) {
                processCommand(inputBuffer_);
                inputBuffer_ = "";
                serial_.print("\nReady> ");
            }
        } else {
            inputBuffer_ += c;
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
// COMMAND PROCESSING
// ═══════════════════════════════════════════════════════════════════

void SerialDisplay::processCommand(const String& cmd) {
    String trimmed = cmd;
    trimmed.trim();
    trimmed.toUpperCase();
    
    LOG_VERBOSE(LogCategory::UI, "Command: %s", trimmed.c_str());
    
    if (trimmed.startsWith("REG:")) {
        if (trimmed.indexOf('=') >= 0) {
            handleRegisterWrite(trimmed);
        } else if (trimmed.indexOf('?') >= 0) {
            handleRegisterRead(trimmed);
        }
    }
    else if (trimmed.startsWith("PAGE:")) {
        int page = trimmed.substring(5).toInt();
        setPage(page);
        serial_.printf("Page set to %d\n", page);
    }
    else if (trimmed == "PAGE?") {
        serial_.printf("Current page: %u\n", currentPage_);
    }
    else if (trimmed == "STATUS") {
        printStatus();
    }
    else if (trimmed == "HELP") {
        printHelp();
    }
    else {
        serial_.println("Unknown command. Type HELP for commands.");
    }
}

void SerialDisplay::handleRegisterWrite(const String& cmd) {
    // Format: REG:0x1010=52
    int eqPos = cmd.indexOf('=');
    String addrPart = cmd.substring(4, eqPos);
    String valuePart = cmd.substring(eqPos + 1);
    
    uint16_t address = (uint16_t)strtol(addrPart.c_str(), nullptr, 0);
    uint16_t value = (uint16_t)strtol(valuePart.c_str(), nullptr, 0);
    
    writeRegister(address, value);
    serial_.printf("REG[0x%04X] = %u\n", address, value);
}

void SerialDisplay::handleRegisterRead(const String& cmd) {
    // Format: REG:0x1010?
    String addrPart = cmd.substring(4);
    addrPart.replace("?", "");
    
    uint16_t address = (uint16_t)strtol(addrPart.c_str(), nullptr, 0);
    uint16_t value = readRegister(address);
    
    serial_.printf("REG[0x%04X] = %u (0x%04X)\n", address, value, value);
}

// ═══════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

void SerialDisplay::printHelp() {
    serial_.println("\n═══════════════════════════════════════");
    serial_.println("  Serial Display Commands");
    serial_.println("═══════════════════════════════════════");
    serial_.println("REG:0xADDR=VALUE  - Write register");
    serial_.println("REG:0xADDR?       - Read register");
    serial_.println("PAGE:N            - Set page to N");
    serial_.println("PAGE?             - Get current page");
    serial_.println("STATUS            - Show all registers");
    serial_.println("HELP              - Show this help");
    serial_.println("═══════════════════════════════════════\n");
}

void SerialDisplay::printStatus() {
    serial_.println("\n═══════════════════════════════════════");
    serial_.printf("Current Page: %u\n", currentPage_);
    serial_.printf("Registers: %d\n", registers_.size());
    serial_.println("───────────────────────────────────────");
    
    for (const auto& pair : registers_) {
        serial_.printf("  0x%04X = %5u (0x%04X)\n", 
                      pair.first, pair.second, pair.second);
    }
    
    serial_.println("═══════════════════════════════════════\n");
}

}  // namespace GLT
