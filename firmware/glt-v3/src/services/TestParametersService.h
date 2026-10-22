#pragma once

#include <Arduino.h>
#include <LittleFS.h>

namespace GLT {

// Recipe (p1-p8)
struct TestRecipe {
  int inflationMaxTime;   // p1 - Şişirme max süresi (sn)
  int inflationPascal;    // p2 - Hedef basınç (Pa)
  int stabilizationTime;  // p3 - Dengeleme süresi (sn)
  int reinflateThreshold; // p4 - Yeniden şişirme eşiği (Pa)
  int failThreshold; // p6 - Conditioning bitiminden izin verilen max düşüş (Pa)
                     // - Bu değer aşılırsa IMMEDIATE FAIL
  int testDuration;      // p7 - Test süresi (sn)
  int successDropPascal; // p8 - Test bitiminde izin verilen toplam düşüş (Pa)
  char recipeName[16];   // Recipe Name (Moved to end for NVS compatibility)

  TestRecipe()
      : inflationMaxTime(0), inflationPascal(0), stabilizationTime(0),
        reinflateThreshold(0), failThreshold(0), testDuration(0),
        successDropPascal(0) {
    memset(recipeName, 0, sizeof(recipeName));
    strncpy(recipeName, "Varsayilan", sizeof(recipeName) - 1);
  }
};

struct TestParams : public TestRecipe {
  // Calibration (c1-c4)
  float pressureOffset;     // c1
  float pressureMultiplier; // c2
  float sealOffset;         // c3
  float sealMultiplier;     // c4

  // Default Constructor
  TestParams()
      : TestRecipe(), pressureOffset(0.0f), pressureMultiplier(1.0f),
        sealOffset(0.0f), sealMultiplier(1.0f) {}
};

class TestParametersService {
public:
  static TestParametersService *getInstance() {
    if (!instance_) {
      instance_ = new TestParametersService();
    }
    return instance_;
  }

  // Initialize (Load from NVS via loadSettings())
  void begin();

  // Load/Save functions
  void loadSettings();
  void saveSettings();

  // Setters
  void updateRecipe(const String &rawRecipe); // Parse "10-3000-..." string
  void setParam(const String &key, const String &value); // Generic set param

  // Getters
  TestParams getCurrentParams() const { return currentParams_; }
  String getRecipeString() const; // Returns "10-3000-..."
  uint32_t calculateCRC() const;  // Calculate CRC32 of current parameters

private:
  TestParametersService();
  static TestParametersService *instance_;

  TestParams currentParams_;
};

} // namespace GLT
