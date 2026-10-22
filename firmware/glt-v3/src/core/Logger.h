#ifndef LOGGER_H
#define LOGGER_H

#include <Arduino.h>

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// LOG LEVELS
// ═══════════════════════════════════════════════════════════════════

enum class LogLevel {
    NONE = 0,
    ERROR = 1,
    WARN = 2,
    INFO = 3,
    DEBUG = 4,
    VERBOSE = 5
};

// ═══════════════════════════════════════════════════════════════════
// LOG CATEGORIES
// ═══════════════════════════════════════════════════════════════════

enum class LogCategory {
    CORE,
    HAL,
    DRIVER,
    SENSOR,
    RFID,
    CONTA,
    TEST,
    UI,        // Changed from DISPLAY to avoid ESP32 macro conflict
    STORAGE,
    NETWORK,
    APP
};

// ═══════════════════════════════════════════════════════════════════
// LOGGER CLASS (Singleton)
// ═══════════════════════════════════════════════════════════════════

class Logger {
public:
    static Logger& getInstance();
    
    // Configuration
    void setLevel(LogLevel level);
    void setLevel(LogCategory category, LogLevel level);
    void enableCategory(LogCategory category, bool enable = true);
    void enableTimestamp(bool enable = true);
    
    // Logging methods
    void log(LogLevel level, LogCategory category, const char* format, ...);
    void error(LogCategory category, const char* format, ...);
    void warn(LogCategory category, const char* format, ...);
    void info(LogCategory category, const char* format, ...);
    void debug(LogCategory category, const char* format, ...);
    void verbose(LogCategory category, const char* format, ...);
    
    // Callback support for Remote Logging (ESP-NOW)
    typedef void (*LogCallback)(LogLevel level, LogCategory category, const char* message);
    void setCallback(LogCallback callback);

    // Helper for raw output (no formatting)
    void raw(const char* format, ...);
    
    // Immediate flush methods for critical real-time data
    void infoFlush(LogCategory category, const char* format, ...);
    void rawFlush(const char* format, ...);
    
private:
    Logger();
    Logger(const Logger&) = delete;
    Logger& operator=(const Logger&) = delete;
    
    LogLevel globalLevel_;
    LogLevel categoryLevels_[11];  // One for each category
    bool categoryEnabled_[11];
    bool timestampEnabled_;
    LogCallback callback_ = nullptr;
    
    const char* getLevelStr(LogLevel level);
    const char* getCategoryStr(LogCategory category);
    bool shouldLog(LogLevel level, LogCategory category);
    void print(LogLevel level, LogCategory category, const char* format, va_list args);
};

// ═══════════════════════════════════════════════════════════════════
// CONVENIENCE MACROS
// ═══════════════════════════════════════════════════════════════════

#define LOG_ERROR(cat, ...) GLT::Logger::getInstance().error(cat, __VA_ARGS__)
#define LOG_WARN(cat, ...)  GLT::Logger::getInstance().warn(cat, __VA_ARGS__)
#define LOG_INFO(cat, ...)  GLT::Logger::getInstance().info(cat, __VA_ARGS__)
#define LOG_DEBUG(cat, ...) GLT::Logger::getInstance().debug(cat, __VA_ARGS__)
#define LOG_VERBOSE(cat, ...) GLT::Logger::getInstance().verbose(cat, __VA_ARGS__)
#define LOG_RAW(...) GLT::Logger::getInstance().raw(__VA_ARGS__)
#define LOG_INFO_FLUSH(cat, ...) GLT::Logger::getInstance().infoFlush(cat, __VA_ARGS__)
#define LOG_RAW_FLUSH(...) GLT::Logger::getInstance().rawFlush(__VA_ARGS__)

}  // namespace GLT

#endif  // LOGGER_H
