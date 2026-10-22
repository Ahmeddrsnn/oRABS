#ifndef BATTERY_SERVICE_H
#define BATTERY_SERVICE_H

#include <Arduino.h>

namespace GLT {

class BatteryService {
public:
  static BatteryService &getInstance() {
    static BatteryService instance;
    return instance;
  }

  void begin();
  void update();

  // Getters
  float getVoltage() const { return voltage_; }
  int getPercentage() const { return percentage_; }
  int getRawADC() const { return rawADC_; }
  uint16_t getIconIndex() const;

private:
  BatteryService();

  // Constants
  static const int PIN_ADC = 5;
  static const int FILTER_WINDOW = 10;

  // Calibration: y = mx + b
  static const float CAL_SLOPE;  // 0.00692f
  static const float CAL_OFFSET; // 0.6793f

  // Thresholds (5S Li-ion)
  static const float V_100;
  static const float V_85;
  static const float V_50;
  static const float V_10;
  static const float V_0;

  // Filter variables
  int readings_[FILTER_WINDOW];
  int readingIndex_;
  bool firstReadingsDone_;
  unsigned long lastReadTime_;
  int readInterval_;

  // State
  float voltage_;
  int percentage_;
  int rawADC_;

  // Helpers
  int readRawADC();
  int calculatePercentage(float voltage);
};

} // namespace GLT

#endif // BATTERY_SERVICE_H
