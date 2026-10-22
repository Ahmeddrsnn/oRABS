#ifndef RFID_SERVICE_H
#define RFID_SERVICE_H

#include "drivers/RFIDReader.h"
#include "services/TestParametersService.h"
#include <Arduino.h>
#include <LittleFS.h>

namespace GLT {
// ... structures remain the same ...
struct RFIDTag {
  uint32_t id;
  bool isAdmin;
  bool isActive;
  char name[16];
  uint16_t portNumber; // 0 = unassigned, encoded as (left<<8)|right for "L/R" format
  bool isNewRecord;   // true = yeni eklendi, PC'ye bildirilmedi

  // Assigned Recipe for this Tag
  TestRecipe recipe; // p1-p8 parameters
};

class RFIDService {
public:
  RFIDService(RFIDReader &rfidReader, uint8_t maxTags = 50);
  ~RFIDService() = default;

  bool begin();
  void end();
  void update();
  bool addTag(uint32_t tagId, bool isAdmin, const char *name = nullptr,
              uint16_t portNumber = 0);
  bool removeTag(uint32_t tagId);
  bool isTagAuthorized(uint32_t tagId);
  bool isAdmin(uint32_t tagId);
  int getActiveTagCount();
  void listTags();
  uint32_t getLastDetectedTag();
  void clearAllTags();
  bool assignPort(uint32_t tagId, uint16_t portNumber);
  uint16_t getTagPort(uint32_t tagId);
  uint8_t getNextAvailablePort(); // Legacy — encode'lu sistemde her zaman 0 döner
  bool isPortAssigned(uint16_t portNumber);
  String getRFIDsJSON(bool onlyNew = true, int maxItems = 3);
  void announceCurrentTag();
  void forceSyncAll();
  void clearNewFlag(uint32_t tagId);
  void resetTimeout() {
    lastDetectTime_ = millis();
  } // Prevent false remove on UART switch
  RFIDTag getTagByIndex(int index);
  void sendFastStream(uint32_t tagId, char phase = 'I', int testElapsedSec = 0);
  bool setTagRecipe(uint32_t tagId, const TestRecipe &recipe);
  TestRecipe getTagRecipe(uint32_t tagId);
  uint32_t calculateCRC();

  /** Toplu ekleme sırasında otomatik saveToFlash'ı devre dışı bırak */
  void setAutoSave(bool enabled) { autoSave_ = enabled; }
  /** Manuel saveToFlash — toplu ekleme sonrası çağır */
  void forceSave() { saveToFlash(); }
  /** Runtime maxTags_ değerini döndürür (tanı amaçlı) */
  uint8_t getMaxTags() const { return maxTags_; }

private:
  RFIDReader &rfidReader_;
  RFIDTag *tags_;
  uint8_t maxTags_;
  uint32_t lastDetectedTag_;
  unsigned long lastDetectTime_;
  uint32_t lastAnnounceTime_ = 0; // Track last periodic announcement
  bool autoSave_ = true;

  void onTagDetected(uint32_t tagId);
  void saveToFlash();
  void loadFromFlash();
};

} // namespace GLT

#endif // RFID_SERVICE_H
