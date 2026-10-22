#ifndef DS3231_H
#define DS3231_H

#include <Arduino.h>
#include <Wire.h>

namespace GLT {

struct DateTime {
    uint8_t second;
    uint8_t minute;
    uint8_t hour;
    uint8_t dayOfWeek; // 1-7
    uint8_t day;
    uint8_t month;
    uint16_t year;
};

class DS3231 {
public:
    DS3231(TwoWire& wire = Wire);
    
    bool begin(int sda, int scl);
    DateTime getTime();
    float getTemperature();

private:
    TwoWire& wire_;
    uint8_t bcdToDec(uint8_t val);
    uint8_t decToBcd(uint8_t val);
};

} // namespace GLT

#endif // DS3231_H
