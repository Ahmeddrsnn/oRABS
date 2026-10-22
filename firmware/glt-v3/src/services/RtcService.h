#ifndef RTC_SERVICE_H
#define RTC_SERVICE_H

#include <Arduino.h>
#include <DS3231.h>

namespace GLT {

class RtcService {
public:
  static RtcService &getInstance() {
    static RtcService instance;
    return instance;
  }

  void begin();
  void update();
  void setTime(uint16_t year, uint8_t month, uint8_t day, uint8_t hour,
               uint8_t minute, uint8_t second);

  // Getters for individual components (reads from DS3231 internal variables)
  int getYear()   { return year_; }    // 2-digit year (e.g. 26 = 2026)
  int getMonth()  { return month_; }   // 1-12
  int getDay()    { return day_; }
  int getHour()   { return hour_; }
  int getMinute() { return minute_; }
  int getSecond() { return second_; }

private:
  RtcService();

  DS3231 myRTC_;

  // Variables for raw reading (populated from DS3231 in update())
  int year_;
  int month_;
  int day_;
  int hour_;
  int minute_;
  int second_;

  bool century_ = false;
  bool h12Flag_;
  bool pmFlag_;

  unsigned long lastSyncTime_ = 0;
};

} // namespace GLT

#endif // RTC_SERVICE_H
