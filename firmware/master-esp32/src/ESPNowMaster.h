#ifndef ESPNOW_MASTER_H
#define ESPNOW_MASTER_H

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <vector>

// ═══════════════════════════════════════════════════════════════════
// SLAVE DEVICE STRUCTURE
// ═══════════════════════════════════════════════════════════════════

struct SlaveDevice {
    uint8_t mac[6];
    char name[32];
    bool connected;
    unsigned long lastSeen;
    
    SlaveDevice() : connected(false), lastSeen(0) {
        memset(mac, 0, 6);
        memset(name, 0, 32);
    }
};

// ═══════════════════════════════════════════════════════════════════
// ESP-NOW MASTER CLASS
// ═══════════════════════════════════════════════════════════════════

class ESPNowMaster {
public:
    ESPNowMaster();
    ~ESPNowMaster() = default;
    
    bool begin();
    bool addSlave(const uint8_t* mac, const char* name);
    bool removeSlave(const uint8_t* mac);
    SlaveDevice* findSlaveByMAC(const uint8_t* mac);
    SlaveDevice* findSlaveByName(const char* name);
    
    bool sendTo(const uint8_t* mac, const char* data);
    void broadcast(const char* data);
    
    void setRecvCallback(void (*callback)(const uint8_t* mac, const char* data));
    void setSendCallback(void (*callback)(const uint8_t* mac, esp_now_send_status_t status));
    
    std::vector<SlaveDevice>& getSlaves() { return slaves_; }
    void updateSlaveStatus();  // Check timeouts
    
private:
    std::vector<SlaveDevice> slaves_;
    void (*recvCallback_)(const uint8_t* mac, const char* data);
    void (*sendCallback_)(const uint8_t* mac, esp_now_send_status_t status);
    
    static void onDataRecv(const uint8_t *mac, const uint8_t *incomingData, int len);
    static void onDataSent(const uint8_t *mac, esp_now_send_status_t status);
    
    static ESPNowMaster* instance_;  // For callbacks
};

#endif  // ESPNOW_MASTER_H
