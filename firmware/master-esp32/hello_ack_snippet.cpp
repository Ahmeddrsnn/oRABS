void onSlaveDataReceived(const uint8_t* mac, const char* data) {
    // Check for HELLO message and send ACK
    if (strstr(data, "\"cmd\":\"HELLO\"") != nullptr) {
        // Slave is sending HELLO - check if registered
        SlaveDevice* slave = espNow.findSlaveByMAC(mac);
        if (slave != nullptr) {
            // Registered - send ACK
            espNow.sendToSlave(mac, "{\"cmd\":\"HELLO_ACK\"}");
        }
    }
    
    // Forward all messages to serial for PC
    Serial.printf("[%02X:%02X:%02X:%02X:%02X:%02X] %s\n", 
                  mac[0], mac[1], mac[2], mac[3], mac[4], mac[5], data);
}

void onDataSent(const uint8_t* mac, esp_now_send_status_t status) {
    if (status != ESP_NOW_SEND_SUCCESS) {
        Serial.println("[WARN] ESP-NOW Send failed");
    }
}
