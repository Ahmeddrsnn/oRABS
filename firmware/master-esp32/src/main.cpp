/**
 * ESP-NOW Master - GLT v3 System
 * PC ↔ ESP32 Bridge ↔ Slave Devices
 * 
 * COM13 (Native USB) - 115200 baud
 */

#include <Arduino.h>
#include <ArduinoJson.h>
#include <deque>
#include <esp_wifi.h>
#include "ESPNowMaster.h"
#include "config.h"

// ═══════════════════════════════════════════════════════════════════
// THREAD-SAFE SERIAL OUTPUT
// ═══════════════════════════════════════════════════════════════════
// ESP-NOW onDataRecv callback ISR bağlamından çağrılır.
// Serial.printf() thread-safe değil — main loop Serial.print ile
// aynı anda çalışırsa satırlar birbiriyle karışır.
// Çözüm: Gelen verileri bir kuyruğa at, main loop içinden yaz.
// ═══════════════════════════════════════════════════════════════════

#include <freertos/queue.h>

struct SerialOutItem {
    char data[300];  // [MAC] + payload + \n
};

static QueueHandle_t serialOutQueue = nullptr;
static const int SERIAL_QUEUE_SIZE = 32;

// Thread-safe: buffer'a yaz ve kuyruğa at
static void serialQueuePrint(const char* str) {
    if (!serialOutQueue) {
        Serial.println(str); // Fallback
        return;
    }
    SerialOutItem item;
    strncpy(item.data, str, sizeof(item.data) - 1);
    item.data[sizeof(item.data) - 1] = '\0';
    if (xQueueSend(serialOutQueue, &item, 0) != pdTRUE) {
        // Kuyruk dolu — düşür (nadir)
    }
}

// main loop'tan çağrılır — Serial.print atomik tek çağrı
static void drainSerialQueue() {
    SerialOutItem item;
    int maxPerTick = 10; // Tek tick'te max 10 mesaj yaz (loop bloklanmasın)
    while (maxPerTick-- > 0 && xQueueReceive(serialOutQueue, &item, 0) == pdTRUE) {
        Serial.println(item.data);
    }
}

// ═══════════════════════════════════════════════════════════════════
// HARDWARE DEFINITIONS (LEDS)
// ═══════════════════════════════════════════════════════════════════

#define LED_UART_STATUS 41  // Yellow - Blink on Activity/Heartbeat
#define LED_SD_STATUS 45    // White - Solid ON when Slave Connected

// ═══════════════════════════════════════════════════════════════════
// GLOBAL OBJECTS
// ═══════════════════════════════════════════════════════════════════

ESPNowMaster espNowMaster;
String inputBuffer = "";
unsigned long lastHeartbeat = 0;
// No queue, direct forwarding for instant response

// ═══════════════════════════════════════════════════════════════════
// FUNCTION DECLARATIONS
// ═══════════════════════════════════════════════════════════════════

void processCommand(String cmd);
void printSlaveList();
void printHelp();
void onSlaveDataReceived(const uint8_t* mac, const char* data);
void onDataSent(const uint8_t* mac, esp_now_send_status_t status);

// ═══════════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════════

void setup() {
    // Initialize LEDs
    pinMode(LED_UART_STATUS, OUTPUT);
    pinMode(LED_SD_STATUS, OUTPUT);
    digitalWrite(LED_UART_STATUS, LOW);
    digitalWrite(LED_SD_STATUS, LOW);

    // Initialize Serial (Native USB)
    Serial.setTxBufferSize(Config::Serial::BUFFER_SIZE);  // HWCDC TX ring buffer: 256 → 4096
    Serial.begin(Config::Serial::BAUD_RATE);
    delay(2000);  // Wait for USB serial
    
    // Thread-safe serial output queue oluştur
    serialOutQueue = xQueueCreate(SERIAL_QUEUE_SIZE, sizeof(SerialOutItem));
    
    Serial.println("\n╔═══════════════════════════════════════════════════════════════╗");
    Serial.println("║  ESP-NOW MASTER - GLT v3                                     ║");
    Serial.println("║  PC Serial Bridge ↔ Slave Devices                            ║");
    Serial.println("╚═══════════════════════════════════════════════════════════════╝");
    Serial.println();

    // Initialize ESP-NOW (sets WiFi.mode + fixed MAC internally)
    if (!espNowMaster.begin()) {
        Serial.println("[ERROR] ESP-NOW init failed!");
        return;
    }
    
    // Set callbacks
    espNowMaster.setRecvCallback(onSlaveDataReceived);
    espNowMaster.setSendCallback(onDataSent);
    
    printHelp();
}

// ═══════════════════════════════════════════════════════════════════
// MAIN LOOP
// ═══════════════════════════════════════════════════════════════════

void loop() {
    // 0. Thread-safe kuyruktan seri port'a yaz (ESP-NOW callback'lerden gelen veriler)
    drainSerialQueue();

    // 1. Read serial commands from PC — auto-forward JSON to all slaves
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (inputBuffer.length() > 0) {
                // JSON komutları doğrudan tüm slave'lere ilet (köprü modu)
                if (inputBuffer.startsWith("{")) {
                    auto& slaves = espNowMaster.getSlaves();
                    for (auto& slave : slaves) {
                        if (slave.connected) {
                            espNowMaster.sendTo(slave.mac, inputBuffer.c_str());
                        }
                    }
                } else {
                    // Dahili komutlar (help, list, addslave vs.)
                    processCommand(inputBuffer);
                }
                inputBuffer = "";
            }
        } else {
            inputBuffer += c;
        }
    }
    
    // 3. Update slave timeouts
    unsigned long now = millis();
    if (now - lastHeartbeat > Config::ESPNow::HEARTBEAT_INTERVAL_MS) {
        espNowMaster.updateSlaveStatus();
        lastHeartbeat = now;

        // --- LED LOGIC ---
        bool anySlaveConnected = false;
        auto& slaves = espNowMaster.getSlaves();
        for (auto& slave : slaves) {
            if (slave.connected) {
                anySlaveConnected = true;
                break;
            }
        }
        digitalWrite(LED_SD_STATUS, anySlaveConnected ? HIGH : LOW);
    }
    
    // 4. Activity Blink
    static unsigned long lastBlink = 0;
    if (now - lastBlink > 1000) {
        lastBlink = now;
        static bool blinkState = false;
        blinkState = !blinkState;
        digitalWrite(LED_UART_STATUS, blinkState ? HIGH : LOW);
    }
    
    // delay(1); // Removed for max speed
    yield();     // Yield to system tasks
}

// ═══════════════════════════════════════════════════════════════════
// ESP-NOW CALLBACKS
// ═══════════════════════════════════════════════════════════════════

void onSlaveDataReceived(const uint8_t* mac, const char* data) {
    // ── Auto-register unknown slave ──
    SlaveDevice* slave = espNowMaster.findSlaveByMAC(mac);
    if (!slave) {
        // İlk kez gören slave — otomatik kaydet
        char autoName[32];
        snprintf(autoName, sizeof(autoName), "Slave_%02X%02X", mac[4], mac[5]);
        if (espNowMaster.addSlave(mac, autoName)) {
            char logBuf[80];
            snprintf(logBuf, sizeof(logBuf), "[ESP-NOW] Auto-registered: %s (%02X:%02X:%02X:%02X:%02X:%02X)",
                     autoName, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
            serialQueuePrint(logBuf);
        } else {
            serialQueuePrint("[ESP-NOW] Auto-register failed");
        }
    }
    
    // Forward all data to serial for PC — ATOMIK buffer yazma
    // Serial.printf ISR/callback bağlamından thread-safe değil.
    // Önce buffer'a yaz, sonra kuyruğa at → main loop'tan Serial.println.
    char buf[300];
    snprintf(buf, sizeof(buf), "[%02X:%02X:%02X:%02X:%02X:%02X] %s", 
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5], data);
    serialQueuePrint(buf);
}

void onDataSent(const uint8_t* mac, esp_now_send_status_t status) {
    if (status != ESP_NOW_SEND_SUCCESS) {
        serialQueuePrint("[WARN] ESP-NOW Send failed");
    }
}

// ═══════════════════════════════════════════════════════════════════
// COMMAND PROCESSING
// ═══════════════════════════════════════════════════════════════════

void processCommand(String cmd) {
    cmd.trim();
    Serial.println();  // New line after command
    
    if (cmd.equalsIgnoreCase("help")) {
        printHelp();
        printSlaveList();
    }
    else if (cmd.equalsIgnoreCase("list")) {
        printSlaveList();
    }
    else if (cmd.startsWith("addslave ")) {
        int spaceIdx = cmd.indexOf(' ', 9);
        if (spaceIdx > 0) {
            String name = cmd.substring(9, spaceIdx);
            String macStr = cmd.substring(spaceIdx + 1);
            macStr.trim();
            
            uint8_t mac[6];
            if (sscanf(macStr.c_str(), "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx",
                      &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5]) == 6) {
                if (espNowMaster.addSlave(mac, name.c_str())) {
                    Serial.printf("[OK] Slave added: %s (%s)\n", name.c_str(), macStr.c_str());
                } else {
                    Serial.println("[ERROR] Failed to add slave (peer add failed)");
                }
            } else {
                Serial.println("[ERROR] Invalid MAC format. Use: AA:BB:CC:DD:EE:FF");
            }
        }
    }
    else if (cmd.startsWith("setparam ")) {
        int space1 = cmd.indexOf(' ', 9);
        if (space1 > 0) {
            String target = cmd.substring(9, space1);
            int space2 = cmd.indexOf(' ', space1 + 1);
            if (space2 > 0) {
                String key = cmd.substring(space1 + 1, space2);
                String value = cmd.substring(space2 + 1);
                
                SlaveDevice* slave = espNowMaster.findSlaveByName(target.c_str());
                if (slave) {
                    JsonDocument doc;
                    doc["cmd"] = "SET_PARAM";
                    doc["key"] = key;
                    doc["value"] = value;
                    char buffer[256];
                    serializeJson(doc, buffer);
                    espNowMaster.sendTo(slave->mac, buffer);
                    Serial.printf("[OK] Command sent to %s\n", target.c_str());
                } else {
                    Serial.printf("[ERROR] setparam target not found: %s\n", target.c_str());
                }
            }
        }
    }
    else if (cmd.startsWith("getparam ")) {
        int spaceIdx = cmd.indexOf(' ', 9);
        if (spaceIdx > 0) {
            String target = cmd.substring(9, spaceIdx);
            String key = cmd.substring(spaceIdx + 1);
            SlaveDevice* slave = espNowMaster.findSlaveByName(target.c_str());
            if (slave) {
                JsonDocument doc;
                doc["cmd"] = "GET_PARAM";
                doc["key"] = key;
                char buffer[256];
                serializeJson(doc, buffer);
                espNowMaster.sendTo(slave->mac, buffer);
                Serial.printf("[WAIT] Request sent to %s\n", target.c_str());
            } else {
                Serial.printf("[ERROR] getparam target not found: %s\n", target.c_str());
            }
        }
    }
    else if (cmd.startsWith("setname ")) {
        int spaceIdx = cmd.indexOf(' ', 8);
        if (spaceIdx > 0) {
            String target = cmd.substring(8, spaceIdx);
            String newName = cmd.substring(spaceIdx + 1);
            SlaveDevice* slave = espNowMaster.findSlaveByName(target.c_str());
            if (slave) {
                JsonDocument doc;
                doc["cmd"] = "SET_NAME";
                doc["name"] = newName;
                char buffer[256];
                serializeJson(doc, buffer);
                if (espNowMaster.sendTo(slave->mac, buffer)) {
                    strncpy(slave->name, newName.c_str(), sizeof(slave->name) - 1);
                    Serial.printf("[OK] Name changed to %s\n", newName.c_str());
                }
            } else {
                Serial.printf("[ERROR] setname target not found: %s\n", target.c_str());
            }
        }
    }
    else if (cmd.startsWith("send ")) {
        int spaceIdx = cmd.indexOf(' ', 5);
        if (spaceIdx > 0) {
            String target = cmd.substring(5, spaceIdx);
            String message = cmd.substring(spaceIdx + 1);
            SlaveDevice* slave = espNowMaster.findSlaveByName(target.c_str());
            // FIX: İsimle bulunamazsa MAC adresi olarak çözümle
            if (!slave && target.indexOf(':') > 0) {
                uint8_t mac[6];
                if (sscanf(target.c_str(), "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx",
                           &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5]) == 6) {
                    slave = espNowMaster.findSlaveByMAC(mac);
                    // On-the-fly: MAC peer listesinde yoksa anında ekle
                    if (!slave) {
                        espNowMaster.addSlave(mac, target.c_str());
                        slave = espNowMaster.findSlaveByMAC(mac);
                        Serial.printf("[ESP-NOW] On-the-fly peer added: %s\n", target.c_str());
                    }
                }
            }
            if (slave) {
                if (!espNowMaster.sendTo(slave->mac, message.c_str())) {
                    Serial.printf("[ERROR] ESP-NOW send failed to %s\n", target.c_str());
                }
            } else {
                Serial.printf("[ERROR] send target not found: %s\n", target.c_str());
            }
        }
    }
}

void printSlaveList() {
    Serial.println("--- SLAVE LIST ---");
    auto& slaves = espNowMaster.getSlaves();
    if (slaves.empty()) {
        Serial.println("(No slaves registered)");
    } else {
        int index = 1;
        for (auto& slave : slaves) {
            char macStr[18];
            snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
                    slave.mac[0], slave.mac[1], slave.mac[2],
                    slave.mac[3], slave.mac[4], slave.mac[5]);
            Serial.printf("[%d] %s (%s) | %s\n", index++, slave.name, macStr, slave.connected ? "BAGLI" : "BAGLANTIKESILDI");
        }
    }
    Serial.println("------------------");
}

void printHelp() {
    Serial.println("╔═══════════════════════════════════════════════════════════════╗");
    Serial.println("║  Commands (PC Compatible)                                    ║");
    Serial.println("╠═══════════════════════════════════════════════════════════════╣");
    Serial.println("║  help               - Show this menu + slave list            ║");
    Serial.println("║  list               - Show slave list only                   ║");
    Serial.println("║  addslave NAME MAC  - Add slave device                       ║");
    Serial.println("║  setparam T K V     - Set parameter on target                ║");
    Serial.println("║  getparam T K       - Get parameter from target              ║");
    Serial.println("║  setname T NAME     - Change slave name                      ║");
    Serial.println("║  send T MSG         - Send raw message to target             ║");
    Serial.println("╚═══════════════════════════════════════════════════════════════╝");
}
