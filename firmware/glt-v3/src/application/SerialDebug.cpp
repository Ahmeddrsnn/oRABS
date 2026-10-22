#include "application/SerialDebug.h"
#include "core/Logger.h"
#include "services/DwinService.h"
#include "services/ESPNowSlave.h"
#include "services/PressureService.h"
#include "services/RtcService.h"

// Defined in main.cpp (Global)
extern GLT::PressureService *pressureService;

namespace GLT {

SerialDebug::SerialDebug(RFIDService &rfidService)
    : rfidService_(rfidService) {}

void SerialDebug::begin() {
  Serial.println(
      "\n╔═══════════════════════════════════════════════════════════════╗");
  Serial.println(
      "║  ESP32-S3 GLT v3 - Temiz Kod Versiyonu                       ║");
  Serial.println(
      "╚═══════════════════════════════════════════════════════════════╝");
  Serial.println();
  printHelp();
  printPrompt();
}

void SerialDebug::update() {
  // Continuous DWIN Monitor
  if (dwinMonitorActive_) {
    if (millis() - lastDwinLog_ > 200) { // 5Hz update
      lastDwinLog_ = millis();
      DwinService::getInstance().printStatusLine();
    }
  }

  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      if (inputBuffer_.length() > 0) {
        processCommand(inputBuffer_);
        inputBuffer_ = "";
        // printPrompt(); // Disable prompt in monitor mode to keep clean
        if (!dwinMonitorActive_)
          printPrompt();
      }
    } else {
      inputBuffer_ += c;
    }
  }
}

void SerialDebug::printHelp() {
  // Print in chunks to avoid watchdog timeout
  Serial.println(
      "╔═══════════════════════════════════════════════════════════════╗");
  Serial.println(
      "║  Komutlar                                                     ║");
  Serial.println(
      "╠═══════════════════════════════════════════════════════════════╣");
  yield(); // Feed watchdog

  Serial.println(
      "║  HELP               - Bu yardım menüsünü göster               ║");
  Serial.println(
      "║  STATUS             - Sistem durumu                           ║");
  Serial.println(
      "║  TAGS               - Tüm RFID tagları listele                ║");
  Serial.println(
      "║  ADD:0xHEX          - Kullanıcı tagı ekle                     ║");
  Serial.println(
      "║  ADDADMIN:0xHEX     - Admin tagı ekle                         ║");
  yield(); // Feed watchdog

  Serial.println(
      "║  REMOVE:0xHEX       - Tagı sil                                ║");
  Serial.println(
      "║  CLEAR              - Tüm tagları sil                         ║");
  Serial.println(
      "║  PORTS              - RFID-Port eşleşmeleri                   ║");
  Serial.println(
      "║  ASSIGN:0xHEX:PORT  - Taga port ata (1-50)                    ║");
  Serial.println(
      "║  REG:PORT           - Son okunan taga port ata                ║");
  yield(); // Feed watchdog

  Serial.println(
      "║  QUERY:0xHEX        - Tag detaylarını NVS'den göster          ║");
  Serial.println(
      "║  NEXTPORT           - Sıradaki boş portu göster               ║");
  Serial.println(
      "║  PRESSURE           - Basınç sensörü detaylı raporu           ║");
  Serial.println(
      "║  STREAM             - Sürekli basınç akışını aç/kapat         ║");
  yield(); // Feed watchdog

  Serial.println(
      "║  DWIN_STATUS        - DWIN Ekranına giden son veriler         ║");
  Serial.println(
      "║  DWIN_LOG ON/OFF    - DWIN Polling loglarını aç/kapat         ║");
  Serial.println(
      "║  RFID_LOG ON/OFF    - RFID loglarını aç/kapat                 ║");
  Serial.println(
      "║  ESPNOW_LOG ON/OFF  - ESP-NOW hata loglarını aç/kapat         ║");
  yield(); // Feed watchdog

  Serial.println(
      "╚═══════════════════════════════════════════════════════════════╝");
}

void SerialDebug::printStatus() {
  Serial.println(
      "╔═══════════════════════════════════════════════════════════════╗");
  Serial.println(
      "║  Sistem Durumu                                                ║");
  Serial.println(
      "╠═══════════════════════════════════════════════════════════════╣");
  Serial.printf("║  Chip:       %-49s║\n", ESP.getChipModel());
  Serial.printf("║  CPU:        %-42d MHz   ║\n", ESP.getCpuFreqMHz());
  Serial.printf("║  Serbest RAM:%-42d KB    ║\n", ESP.getFreeHeap() / 1024);
  Serial.printf("║  Çalışma:    %-42lu s     ║\n", millis() / 1000);
  Serial.printf("║  RFID Taglar:%-42d       ║\n",
                rfidService_.getActiveTagCount());
  Serial.println(
      "╚═══════════════════════════════════════════════════════════════╝");
}

void SerialDebug::printPrompt() { Serial.print("\nHazır> "); }

// ═══════════════════════════════════════════════════════════════════
// PRIVATE METHODS
// ═══════════════════════════════════════════════════════════════════

void SerialDebug::processCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();

  Serial.println(); // New line after command

  if (cmd == "HELP") {
    printHelp();
  } else if (cmd.startsWith("SET_TIME:")) {
    // Format: SET_TIME:2024-02-19 08:30:00
    String timeStr = cmd.substring(9);
    timeStr.trim();
    int year, month, day, hour, minute, second;
    if (sscanf(timeStr.c_str(), "%d-%d-%d %d:%d:%d", &year, &month, &day, &hour,
               &minute, &second) == 6) {
      RtcService::getInstance().setTime(year, month, day, hour, minute, second);

      // Broadcast to Slaves
      char buf[64];
      snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d", year, month,
               day, hour, minute, second);
      ESPNowSlave::broadcastTime(buf); // Static call

      Serial.println("✅ Zaman güncellendi ve yayınlandı.");
    } else {
      Serial.println("❌ Zaman formatı hatalı: YYYY-MM-DD HH:MM:SS");
    }
  } else if (cmd == "STATUS") {
    printStatus();
  } else if (cmd == "TAGS") {
    rfidService_.listTags();
  } else if (cmd.startsWith("ADD:")) {
    String hex = cmd.substring(4);
    hex.trim();
    uint32_t tagId = strtoul(hex.c_str(), nullptr, 16);
    if (tagId != 0) {
      if (rfidService_.addTag(tagId, false)) {
        Serial.printf("✅ Tag 0x%08X eklendi\n", tagId);
      } else {
        Serial.printf("❌ Tag eklenemedi: 0x%08X\n", tagId);
      }
    } else {
      Serial.println("❌ Geçersiz tag ID");
    }
  } else if (cmd.startsWith("ADDADMIN:")) {
    String hex = cmd.substring(9);
    hex.trim();
    uint32_t tagId = strtoul(hex.c_str(), nullptr, 16);
    if (tagId != 0) {
      if (rfidService_.addTag(tagId, true)) {
        Serial.printf("✅ Admin tag 0x%08X eklendi\n", tagId);
      } else {
        Serial.printf("❌ Tag eklenemedi: 0x%08X\n", tagId);
      }
    } else {
      Serial.println("❌ Geçersiz tag ID");
    }
  } else if (cmd.startsWith("REMOVE:")) {
    String hex = cmd.substring(7);
    hex.trim();
    uint32_t tagId = strtoul(hex.c_str(), nullptr, 16);
    if (rfidService_.removeTag(tagId)) {
      Serial.printf("✅ Tag 0x%08X silindi\n", tagId);
    } else {
      Serial.printf("❌ Tag bulunamadı: 0x%08X\n", tagId);
    }
  } else if (cmd == "CLEAR") {
    Serial.println("⚠️  Tüm taglar silinecek! Onaylıyor musunuz? (E/H)");
    Serial.print("Cevap> ");

    // Wait for confirmation
    unsigned long startTime = millis();
    String confirm = "";
    while (millis() - startTime < 10000) { // 10 second timeout
      if (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
          confirm.toUpperCase();
          if (confirm == "E" || confirm == "EVET") {
            rfidService_.clearAllTags();
            Serial.println("\n✅ Tüm taglar silindi");
          } else {
            Serial.println("\n❌ İptal edildi");
          }
          return;
        } else {
          confirm += c;
        }
      }
      delay(10);
    }
    Serial.println("\n❌ Zaman aşımı - iptal edildi");
  } else if (cmd == "PORTS") {
    rfidService_.listTags(); // Already shows port numbers
  } else if (cmd.startsWith("ASSIGN:")) {
    // Format: ASSIGN:0xHEXTAGID:SOL/SAG (encoded port)
    int firstColon = cmd.indexOf(':', 7);
    if (firstColon > 0) {
      String hexStr = cmd.substring(7, firstColon);
      String portStr = cmd.substring(firstColon + 1);
      hexStr.trim();
      portStr.trim();

      uint32_t tagId = strtoul(hexStr.c_str(), nullptr, 16);
      // Parse "sol/sag" format
      int slashIdx = portStr.indexOf('/');
      uint16_t port = 0;
      if (slashIdx > 0) {
        uint8_t left = portStr.substring(0, slashIdx).toInt();
        uint8_t right = portStr.substring(slashIdx + 1).toInt();
        port = (left << 8) | right;
      }

      if (tagId != 0 && port != 0) {
        if (rfidService_.assignPort(tagId, port)) {
          Serial.printf("✅ Port %d/%d -> Tag 0x%08X atandı\n", port >> 8, port & 0xFF, tagId);
        } else {
          if (rfidService_.isPortAssigned(port)) {
            Serial.printf("❌ Port %d/%d kullanımda\n", port >> 8, port & 0xFF);
          } else {
            Serial.printf("❌ Tag 0x%08X bulunamadı veya port geçersiz\n",
                          tagId);
          }
        }
      } else {
        Serial.println("❌ Geçersiz format. Örnek: ASSIGN:0x004FD0CF:3/5");
      }
    }
  } else if (cmd.startsWith("REG:")) {
    // Format: REG:PORT (Uses last detected tag)
    uint32_t lastTag = rfidService_.getLastDetectedTag();
    if (lastTag == 0) {
      Serial.println("❌ Bekleyen tag yok. Önce bir kart okutun!");
      return;
    }

    String portStr = cmd.substring(4);
    portStr.trim();
    // Parse "sol/sag" format
    int slashIdx = portStr.indexOf('/');
    uint16_t port = 0;
    if (slashIdx > 0) {
      uint8_t left = portStr.substring(0, slashIdx).toInt();
      uint8_t right = portStr.substring(slashIdx + 1).toInt();
      port = (left << 8) | right;
    }

    if (port != 0) {
      // Auto-add if not exists
      if (!rfidService_.isTagAuthorized(lastTag)) {
        rfidService_.addTag(lastTag, false);
        Serial.printf("🆕 Yeni tag otomatik kaydedildi: 0x%08X\n", lastTag);
      }

      if (rfidService_.assignPort(lastTag, port)) {
        Serial.printf("✅ Port %d/%d -> Tag 0x%08X (Son Okunan) atandı\n", port >> 8, port & 0xFF,
                      lastTag);
      } else {
        Serial.printf("❌ Port %d/%d atanamadı\n", port >> 8, port & 0xFF);
      }
    } else {
      Serial.println("❌ Geçersiz port. Örnek: REG:3/5");
    }
  } else if (cmd.startsWith("QUERY:")) {
    String hex = cmd.substring(6);
    hex.trim();
    uint32_t tagId = strtoul(hex.c_str(), nullptr, 16);
    if (tagId != 0) {
      bool found = false;
      for (int i = 0; i < 50; i++) {
        RFIDTag tag = rfidService_.getTagByIndex(i);
        if (tag.isActive && tag.id == tagId) {
          found = true;
          Serial.println("\n═══════════════════════════════════════════════════"
                         "════════════");
          Serial.printf("  Tag Detayları (NVS'den)\n");
          Serial.println("═════════════════════════════════════════════════════"
                         "══════════");
          Serial.printf("  HEX ID:     0x%08X\n", tag.id);
          Serial.printf("  İsim:       %s\n", tag.name);
          Serial.printf("  Tip:        %s\n", tag.isAdmin ? "ADMIN" : "USER");
          Serial.printf("  Port:       %d/%d %s\n", tag.portNumber >> 8, tag.portNumber & 0xFF,
                        tag.portNumber == 0 ? "(Atanmamış)" : "");
          Serial.printf("  Yeni Kayıt: %s\n",
                        tag.isNewRecord ? "Evet" : "Hayır");
          Serial.printf("  Reçete İsmi: %s\n", tag.recipe.recipeName);
          Serial.println("  Parametreler:");
          Serial.printf("    P1 (Şişirme Max): %d ms\n",
                        tag.recipe.inflationMaxTime);
          Serial.printf("    P2 (Hedef Basınç): %d Pa\n",
                        tag.recipe.inflationPascal);
          Serial.printf("    P3 (Stabilizasyon): %d ms\n",
                        tag.recipe.stabilizationTime);
          Serial.printf("    P4 (Yeniden Basınç): %d Pa\n",
                        tag.recipe.reinflateThreshold);
          Serial.printf("    P6 (Başarısız Eşik): %d Pa\n",
                        tag.recipe.failThreshold);
          Serial.printf("    P7 (Test Süresi): %d ms\n",
                        tag.recipe.testDuration);
          Serial.printf("    P8 (Başarı Düşüş): %d Pa\n",
                        tag.recipe.successDropPascal);
          Serial.println("═════════════════════════════════════════════════════"
                         "══════════\n");
          break;
        }
      }
      if (!found) {
        Serial.printf("❌ Tag 0x%08X NVS'de bulunamadı veya aktif değil\n",
                      tagId);
      }
    } else {
      Serial.println("❌ Geçersiz tag ID. Örnek: QUERY:0x004FD0CF");
    }
  } else if (cmd == "NEXTPORT") {
    Serial.println("Port sistemi artik sol/sag encode formatinda. NEXTPORT devre disi.");
  } else if (cmd == "PRESSURE" || cmd == "P") {
    if (pressureService) {
      pressureService->printDebugInfo();
    } else {
      Serial.println("❌ PressureService başlatılmamış!");
    }
  } else if (cmd == "STREAM") {
    if (pressureService) {
      bool newState = !pressureService->isContinuous();
      pressureService->setContinuous(newState);
      if (newState) {
        Serial.println("🌊 Sürekli akış AÇIK (Durdurmak için 'STREAM' yazın)");
      } else {
        Serial.println("🛑 Sürekli akış KAPALI");
      }
    } else {
      Serial.println("❌ PressureService başlatılmamış!");
    }
  } else if (cmd == "DWIN_STATUS") {
    dwinMonitorActive_ = !dwinMonitorActive_;
    if (dwinMonitorActive_) {
      Serial.println("✅ DWIN Monitör Modu: AÇIK (Durdurmak için tekrar "
                     "'DWIN_STATUS' yazın)");
      Serial.println("Rehber: TIM:Saat SD:Durum NOW:EspNow ANIM:Animasyon");
    } else {
      Serial.println("\n🛑 DWIN Monitör Modu: KAPALI");
    }
  } else if (cmd.startsWith("DWIN_LOG")) {
    if (cmd.indexOf("ON") > 0) {
      DwinService::togglePollingLog(true);
      DwinService::toggleTrafficLog(true); // Enable Traffic Logs too
      Serial.println("✅ DWIN Logları (Polling + Traffic): AÇIK");
    } else if (cmd.indexOf("OFF") > 0) {
      DwinService::togglePollingLog(false);
      DwinService::toggleTrafficLog(false); // Disable Traffic Logs too
      Serial.println("✅ DWIN Logları (Polling + Traffic): KAPALI");
    } else {
      bool state = DwinService::isPollingLogEnabled();
      Serial.printf("ℹ️ DWIN Log Durumu: %s (Değiştirmek için ON/OFF ekleyin)\n",
                    state ? "AÇIK" : "KAPALI");
    }
  } else if (cmd.startsWith("ESPNOW_LOG")) {
    // ESPNOW_LOG ON or OFF
    if (cmd.indexOf("ON") > 0) {
      ESPNowSlave::toggleErrorLog(true);
      Serial.println("✅ ESP-NOW Hata Logları: AÇIK");
    } else if (cmd.indexOf("OFF") > 0) {
      ESPNowSlave::toggleErrorLog(false);
      Serial.println("✅ ESP-NOW Hata Logları: KAPALI");
    } else {
      bool state = ESPNowSlave::isErrorLogEnabled();
      Serial.printf(
          "ℹ️ ESP-NOW Log Durumu: %s (Değiştirmek için ON/OFF ekleyin)\n",
          state ? "AÇIK" : "KAPALI");
    }
  } else if (cmd.startsWith("RFID_LOG")) {
    if (cmd.indexOf("ON") > 0) {
      Logger::getInstance().enableCategory(LogCategory::RFID, true);
      Logger::getInstance().setLevel(LogCategory::RFID, LogLevel::VERBOSE);
      Serial.println("✅ RFID Logları: AÇIK (VERBOSE)");
    } else if (cmd.indexOf("OFF") > 0) {
      Logger::getInstance().enableCategory(LogCategory::RFID,
                                           false); // Or just set to INFO/WARN
      Serial.println("✅ RFID Logları: KAPALI (Sadece Önemli)");
    } else {
      Serial.println("ℹ️ Kullanım: RFID_LOG ON veya RFID_LOG OFF");
    }
  } else if (cmd.startsWith("SEND ")) {
    // Format: SEND <TARGET> <MESSAGE>
    // Example: SEND FF:FF:FF:FF:FF:FF {"cmd":"HELLO"}
    int firstSpace = cmd.indexOf(' ');
    int secondSpace = cmd.indexOf(' ', firstSpace + 1);

    if (secondSpace > 0) {
      String target = cmd.substring(firstSpace + 1, secondSpace);
      String message = cmd.substring(secondSpace + 1);
      target.trim();

      if (target.length() > 0 && message.length() > 0) {
        ESPNowSlave::sendToDevice(target.c_str(), message.c_str());
      } else {
        Serial.println(
            "❌ Hatalı format. Örnek: SEND FF:FF:FF:FF:FF:FF {json}");
      }
    } else {
      Serial.println("❌ Hatalı format. Örnek: SEND <TARGET> <MESSAGE>");
    }
  } else {
    Serial.println("❌ Bilinmeyen komut. HELP yazın.");
  }
}

} // namespace GLT
