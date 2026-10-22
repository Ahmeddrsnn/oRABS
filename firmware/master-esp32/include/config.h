#ifndef CONFIG_H
#define CONFIG_H

namespace Config {

// ═══════════════════════════════════════════════════════════════════
// ESP-NOW CONFIGURATION
// ═══════════════════════════════════════════════════════════════════

namespace ESPNow {
    constexpr uint8_t WIFI_CHANNEL = 1;          // ESP-NOW kanal
    constexpr int MAX_SLAVES = 20;               // Maksimum slave sayısı
    constexpr int MESSAGE_TIMEOUT_MS = 5000;     // Mesaj timeout
    constexpr int HEARTBEAT_INTERVAL_MS = 10000; // Heartbeat aralığı
}

// ═══════════════════════════════════════════════════════════════════
// SERIAL CONFIGURATION
// ═══════════════════════════════════════════════════════════════════

namespace Serial {
    // STABİLİTE: Stream verilerinin UART'ta şişmesini engellemek için hız ve buffer 8 katına çıkarıldı.
    constexpr int BAUD_RATE = 921600;
    constexpr int BUFFER_SIZE = 4096;
}

}  // namespace Config

#endif  // CONFIG_H
