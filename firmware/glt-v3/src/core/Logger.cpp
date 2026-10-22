#include "Logger.h"
#include <stdarg.h>

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// SINGLETON INSTANCE
// ═══════════════════════════════════════════════════════════════════

Logger& Logger::getInstance() {
    static Logger instance;
    return instance;
}

// ═══════════════════════════════════════════════════════════════════
// CONSTRUCTOR
// ═══════════════════════════════════════════════════════════════════

Logger::Logger() 
    : globalLevel_(LogLevel::INFO)
    , timestampEnabled_(true)
{
    // Initialize all categories to global level and enabled
    for (int i = 0; i < 11; i++) {
        categoryLevels_[i] = LogLevel::INFO;
        categoryEnabled_[i] = true;
    }
}

// ═══════════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════════

void Logger::setLevel(LogLevel level) {
    globalLevel_ = level;
}

void Logger::setLevel(LogCategory category, LogLevel level) {
    categoryLevels_[static_cast<int>(category)] = level;
}

void Logger::enableCategory(LogCategory category, bool enable) {
    categoryEnabled_[static_cast<int>(category)] = enable;
}

void Logger::enableTimestamp(bool enable) {
    timestampEnabled_ = enable;
}

void Logger::setCallback(LogCallback callback) {
    callback_ = callback;
}

// ═══════════════════════════════════════════════════════════════════
// LOGGING METHODS
// ═══════════════════════════════════════════════════════════════════

void Logger::log(LogLevel level, LogCategory category, const char* format, ...) {
    if (!shouldLog(level, category)) return;
    
    va_list args;
    va_start(args, format);
    print(level, category, format, args);
    va_end(args);
}

void Logger::error(LogCategory category, const char* format, ...) {
    if (!shouldLog(LogLevel::ERROR, category)) return;
    
    va_list args;
    va_start(args, format);
    print(LogLevel::ERROR, category, format, args);
    va_end(args);
}

void Logger::warn(LogCategory category, const char* format, ...) {
    if (!shouldLog(LogLevel::WARN, category)) return;
    
    va_list args;
    va_start(args, format);
    print(LogLevel::WARN, category, format, args);
    va_end(args);
}

void Logger::info(LogCategory category, const char* format, ...) {
    if (!shouldLog(LogLevel::INFO, category)) return;
    
    va_list args;
    va_start(args, format);
    print(LogLevel::INFO, category, format, args);
    va_end(args);
}

void Logger::debug(LogCategory category, const char* format, ...) {
    if (!shouldLog(LogLevel::DEBUG, category)) return;
    
    va_list args;
    va_start(args, format);
    print(LogLevel::DEBUG, category, format, args);
    va_end(args);
}

void Logger::verbose(LogCategory category, const char* format, ...) {
    if (!shouldLog(LogLevel::VERBOSE, category)) return;
    
    va_list args;
    va_start(args, format);
    print(LogLevel::VERBOSE, category, format, args);
    va_end(args);
}

void Logger::raw(const char* format, ...) {
    va_list args;
    va_start(args, format);
    
    char buffer[512];  // Increased buffer size for better performance
    vsnprintf(buffer, sizeof(buffer), format, args);
    Serial.print(buffer);
    
    va_end(args);
}

void Logger::infoFlush(LogCategory category, const char* format, ...) {
    if (!shouldLog(LogLevel::INFO, category)) return;
    
    va_list args;
    va_start(args, format);
    print(LogLevel::INFO, category, format, args);
    va_end(args);
    
    Serial.flush();  // Immediate flush for real-time data
}

void Logger::rawFlush(const char* format, ...) {
    va_list args;
    va_start(args, format);
    
    char buffer[512];
    vsnprintf(buffer, sizeof(buffer), format, args);
    Serial.print(buffer);
    
    va_end(args);
    
    Serial.flush();  // Immediate flush for real-time data
}

// ═══════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

const char* Logger::getLevelStr(LogLevel level) {
    switch (level) {
        case LogLevel::ERROR:   return "ERROR";
        case LogLevel::WARN:    return "WARN ";
        case LogLevel::INFO:    return "INFO ";
        case LogLevel::DEBUG:   return "DEBUG";
        case LogLevel::VERBOSE: return "VERB ";
        default:                return "?????";
    }
}

const char* Logger::getCategoryStr(LogCategory category) {
    switch (category) {
        case LogCategory::CORE:    return "CORE   ";
        case LogCategory::HAL:     return "HAL    ";
        case LogCategory::DRIVER:  return "DRIVER ";
        case LogCategory::SENSOR:  return "SENSOR ";
        case LogCategory::RFID:    return "RFID   ";
        case LogCategory::CONTA:   return "CONTA  ";
        case LogCategory::TEST:    return "TEST   ";
        case LogCategory::UI: return "DISPLAY";
        case LogCategory::STORAGE: return "STORAGE";
        case LogCategory::NETWORK: return "NETWORK";
        case LogCategory::APP:     return "APP    ";
        default:                   return "???????";
    }
}

bool Logger::shouldLog(LogLevel level, LogCategory category) {
    int catIdx = static_cast<int>(category);
    
    // Check if category is enabled
    if (!categoryEnabled_[catIdx]) return false;
    
    // Check level (lower numeric value = higher priority)
    LogLevel catLevel = categoryLevels_[catIdx];
    return static_cast<int>(level) <= static_cast<int>(catLevel);
}

void Logger::print(LogLevel level, LogCategory category, const char* format, va_list args) {
    // Timestamp
    if (timestampEnabled_) {
        unsigned long ms = millis();
        Serial.printf("[%7lu] ", ms);
    }
    
    // Level and category
    Serial.printf("[%s][%s] ", getLevelStr(level), getCategoryStr(category));
    
    // Message
    char buffer[512];  // Increased buffer size for better performance
    vsnprintf(buffer, sizeof(buffer), format, args);
    Serial.println(buffer);
    
    // Callback (Remote Logging)
    if (callback_) {
        callback_(level, category, buffer);
    }
}

}  // namespace GLT
