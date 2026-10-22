#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// Wi-Fi/OTA bilgileri git'e gönderilmez: include/secrets.h (şablon: secrets.example.h)
#if __has_include("secrets.h")
#include "secrets.h"
#else
#warning "include/secrets.h bulunamadi; secrets.example.h kullaniliyor (OTA Wi-Fi baglanmaz)"
#include "secrets.example.h"
#endif

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// HARDWARE CONFIGURATION
// ═══════════════════════════════════════════════════════════════════

struct HardwareConfig {
  // I2C Bus
  struct {
    uint8_t sda = 9;
    uint8_t scl = 8;
    uint32_t frequency = 100000; // 100kHz
  } i2c;

  // I2C Device Addresses
  struct {
    uint8_t rtc = 0x68; // DS3231
    uint8_t adc = 0x48; // ADS1115
  } i2c_addr;

  // UART - DWIN Display (not used yet)
  struct {
    uint8_t rx = 17;
    uint8_t tx = 18;
    uint32_t baud = 115200;
  } dwin;

  // Modbus RTU - Pressure Sensor (Serial2)
  struct {
    uint8_t rx = 6;
    uint8_t tx = 7;
    uint32_t baud = 9600;
    uint8_t slave_id = 83;   // 0x53
    uint16_t start_reg = 16; // 0x0010
    uint16_t quantity = 2;   // 2 registers (4 bytes)
  } modbus_pressure;

  // RFID Reader (RDM6300)
  struct {
    uint8_t rx = 19;      // GPIO19 (User Requested)
    uint8_t uart_num = 1; // CHANGED TO 1 (Shared with Modbus)
    uint32_t baud = 9600;
  } rfid;

  // SD Card (SD_MMC - 4-bit mode)
  struct {
    uint8_t clk = 36;
    uint8_t cmd = 35;
    uint8_t d0 = 37;
    uint8_t d1 = 38;
    uint8_t d2 = 33;
    uint8_t d3 = 48;
  } sd;

  // Digital Outputs (Relays)
  struct {
    uint8_t conta_solenoid = 1; // Relay_1
    uint8_t pump_motor = 2;     // Relay_2
    uint8_t glove_solenoid = 3; // Relay_3
    uint8_t drain_solenoid = 4; // Relay_4
  } relays;

  // Indicators
  struct {
    uint8_t buzzer = 21;
    uint8_t error_led = 40;  // Moved from 19 to 40 to free 19 for RFID
    uint8_t status_led = 42; // System Heartbeat
  } indicators;

  // Digital Inputs
  struct {
    uint8_t relay_fuse = 20;
    uint8_t charge_info = 39;
    uint8_t on_off_info = 41; // Moved from 19 to 41 to free 19 for RFID
  } inputs;

  // Analog Inputs
  struct {
    uint8_t adc_v1 = 5;          // Battery voltage 1
    uint8_t adc_v2 = 6;          // Battery voltage 2
    uint8_t conta_pressure = 14; // Container pressure (4-20mA)
  } analog;
};

// ═══════════════════════════════════════════════════════════════════
// APPLICATION CONFIGURATION
// ═══════════════════════════════════════════════════════════════════

struct AppConfig {
  // RFID Settings
  struct {
    char device_name[32] = "TestAparati"; // Default Name
    uint8_t max_tags = 50;
    uint16_t timeout_ms = 300;
    const char *nvs_namespace = "rfid_v5";
    uint32_t admin_tag_1 = 0x004FD0CF; // Test tag (varsayılan admin)
    uint32_t admin_tag_2 = 0;          // İkinci admin (opsiyonel)
  } rfid;

  // Battery Monitoring
  struct {
    uint8_t cell_count = 5;       // 5S configuration
    uint16_t filter_window = 100; // Moving average samples
    float voltage_full = 21.0;
    float voltage_empty = 15.0;
    float divider_r_top = 150000.0;
    float divider_r_bot = 20000.0;
  } battery;

  // Conta (Container) Control
  struct {
    float max_pressure_mbar = 100.0;
    float min_pressure_mbar = 0.0;
    uint32_t pump_timeout_ms = 30000;
    uint32_t drain_auto_close_ms = 5000;
  } conta;

  // Test System
  struct {
    uint32_t max_duration_ms = 300000; // 5 minutes
    float pass_threshold = 0.95;
  } test;

  // WiFi OTA Settings
  struct {
    char ssid[32] = GLT_WIFI_SSID;
    char password[64] = GLT_WIFI_PASSWORD;
    char ota_password[64] = GLT_OTA_PASSWORD;  // Boş = Şifresiz OTA
    char hostname[32] = "GLT_v3_OTA";
    uint16_t ota_port = 3232;
    uint32_t connection_timeout_ms = 15000;  // 15 saniye
  } wifi;

  // Logging
  struct {
    bool enable_serial = true;
    bool enable_sd = true;
    uint32_t baud = 115200;
  } logging;

  // Calibration
  struct {
    int32_t pressure_zero_offset = 99099; // Modbus zero point calibration
    float pressure_multiplier = 1.0f;     // 1.0 = nötr (%100.0), 1.001 = %100.1
    float seal_offset = 0.0f;
    float seal_multiplier = 1.0f;
  } calibration;
};

// ═══════════════════════════════════════════════════════════════════
// GLOBAL CONFIG INSTANCE
// ═══════════════════════════════════════════════════════════════════

class Config {
public:
  static HardwareConfig hardware;
  static AppConfig app;

  static void init();
  static void loadFromNVS();
  static void saveToNVS();

private:
  Config() = default;
};

} // namespace GLT

#endif // CONFIG_H
