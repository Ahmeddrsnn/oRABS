#include "ESPNowMaster.h"
#include "config.h"
#include <esp_wifi.h>

// Static instance for callbacks
ESPNowMaster* ESPNowMaster::instance_ = nullptr;

ESPNowMaster::ESPNowMaster()
    : recvCallback_(nullptr)
    , sendCallback_(nullptr)
{
    instance_ = this;
}

bool ESPNowMaster::begin() {
    // Set WiFi mode to STA
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    
    // KRITİK: Sabit MAC'i esp_now_init()'ten ÖNCE ayarla!
    // Slave bu MAC'e gönderiyor — sıra yanlış olursa paketler kaybolur.
    const uint8_t fixedMAC[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};
    esp_err_t macResult = esp_wifi_set_mac(WIFI_IF_STA, fixedMAC);
    if (macResult != ESP_OK) {
        Serial.printf("[ESP-NOW] MAC set HATA: %d\n", macResult);
    }
    
    // KRITİK: WiFi kanalını slave ile aynı kanala sabitle!
    // Slave channel=1 olarak peer register ediyor. Master'ın da channel=1 olması ŞART.
    esp_wifi_set_channel(Config::ESPNow::WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
    
    Serial.printf("[ESP-NOW] Fixed MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
                  fixedMAC[0], fixedMAC[1], fixedMAC[2],
                  fixedMAC[3], fixedMAC[4], fixedMAC[5]);
    Serial.printf("[ESP-NOW] Actual MAC: %s\n", WiFi.macAddress().c_str());
    Serial.printf("[ESP-NOW] Channel: %d\n", Config::ESPNow::WIFI_CHANNEL);
    
    // Initialize ESP-NOW
    if (esp_now_init() != ESP_OK) {
        Serial.println("[ESP-NOW] Init failed!");
        return false;
    }
    
    Serial.println("[ESP-NOW] Init success");
    
    // Register callbacks
    esp_now_register_recv_cb(onDataRecv);
    esp_now_register_send_cb(onDataSent);
    
    return true;
}

bool ESPNowMaster::addSlave(const uint8_t* mac, const char* name) {
    // Check if already exists — update name if MAC matches
    for (auto& slave : slaves_) {
        if (memcmp(slave.mac, mac, 6) == 0) {
            if (strcmp(slave.name, name) != 0) {
                strncpy(slave.name, name, sizeof(slave.name) - 1);
                slave.name[sizeof(slave.name) - 1] = '\0';
                // NOT: Serial çıkışı burada YAPILMAZ.
                // Bu fonksiyon WiFi task bağlamından (onDataRecv → onSlaveDataReceived)
                // çağrılabilir. Serial.printf thread-safe değil.
                // Loglama caller'da yapılır.
            }
            return true;
        }
    }
    
    // Add peer
    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, mac, 6);
    peerInfo.channel = Config::ESPNow::WIFI_CHANNEL;
    peerInfo.encrypt = false;
    
    if (esp_now_add_peer(&peerInfo) != ESP_OK) {
        // NOT: Serial çıkışı yok — caller hata durumunu kontrol eder.
        return false;
    }
    
    // Add to list
    SlaveDevice slave;
    memcpy(slave.mac, mac, 6);
    strncpy(slave.name, name, sizeof(slave.name) - 1);
    slave.connected = true;
    slave.lastSeen = millis();
    
    slaves_.push_back(slave);
    
    // NOT: Loglama burada yapılmaz (thread safety).
    // Caller loglama yapar — processCommand için Serial, callback için serialQueuePrint.
    
    return true;
}

bool ESPNowMaster::removeSlave(const uint8_t* mac) {
    for (auto it = slaves_.begin(); it != slaves_.end(); ++it) {
        if (memcmp(it->mac, mac, 6) == 0) {
            esp_now_del_peer(mac);
            slaves_.erase(it);
            Serial.println("[ESP-NOW] Slave removed");
            return true;
        }
    }
    return false;
}

SlaveDevice* ESPNowMaster::findSlaveByMAC(const uint8_t* mac) {
    for (auto& slave : slaves_) {
        if (memcmp(slave.mac, mac, 6) == 0) {
            return &slave;
        }
    }
    return nullptr;
}

SlaveDevice* ESPNowMaster::findSlaveByName(const char* name) {
    for (auto& slave : slaves_) {
        if (strcmp(slave.name, name) == 0) {
            return &slave;
        }
    }
    return nullptr;
}

bool ESPNowMaster::sendTo(const uint8_t* mac, const char* data) {
    if (!data || strlen(data) == 0) return false;
    
    esp_err_t result = esp_now_send(mac, (uint8_t*)data, strlen(data));
    
    if (result == ESP_OK) {
        return true;
    } else {
        Serial.printf("[ESP-NOW] Send error: %d\n", result);
        return false;
    }
}

void ESPNowMaster::broadcast(const char* data) {
    for (auto& slave : slaves_) {
        if (slave.connected) {
            sendTo(slave.mac, data);
        }
    }
}

void ESPNowMaster::setRecvCallback(void (*callback)(const uint8_t* mac, const char* data)) {
    recvCallback_ = callback;
}

void ESPNowMaster::setSendCallback(void (*callback)(const uint8_t* mac, esp_now_send_status_t status)) {
    sendCallback_ = callback;
}

void ESPNowMaster::updateSlaveStatus() {
    unsigned long now = millis();
    for (auto& slave : slaves_) {
        if (slave.connected && (now - slave.lastSeen > Config::ESPNow::HEARTBEAT_INTERVAL_MS)) {
            slave.connected = false;
            Serial.printf("[ESP-NOW] Slave timeout: %s\n", slave.name);
        }
    }
}

// Static callbacks
void ESPNowMaster::onDataRecv(const uint8_t *mac, const uint8_t *incomingData, int len) {
    if (!instance_) return;
    
    // Update last seen
    SlaveDevice* slave = instance_->findSlaveByMAC(mac);
    if (slave) {
        slave->lastSeen = millis();
        slave->connected = true;
    }
    
    // Call user callback
    if (instance_->recvCallback_) {
        char buffer[256];
        int copyLen = min(len, 255);
        memcpy(buffer, incomingData, copyLen);
        buffer[copyLen] = '\0';
        instance_->recvCallback_(mac, buffer);
    }
}

void ESPNowMaster::onDataSent(const uint8_t *mac, esp_now_send_status_t status) {
    if (!instance_) return;
    
    if (instance_->sendCallback_) {
        instance_->sendCallback_(mac, status);
    }
}
