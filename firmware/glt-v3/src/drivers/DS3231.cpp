#include "drivers/DS3231.h"

namespace GLT {

DS3231::DS3231(TwoWire& wire) : wire_(wire) {}

bool DS3231::begin(int sda, int scl) {
    return wire_.begin(sda, scl);
}

DateTime DS3231::getTime() {
    DateTime dt = {0};
    
    wire_.beginTransmission(0x68);
    wire_.write(0); // Start at register 0
    if (wire_.endTransmission() != 0) {
        return dt; // Error
    }
    
    if (wire_.requestFrom(0x68, 7) != 7) {
        return dt; // Error
    }
    
    dt.second = bcdToDec(wire_.read() & 0x7F);
    dt.minute = bcdToDec(wire_.read());
    dt.hour = bcdToDec(wire_.read() & 0x3F); // 24h format assumed
    dt.dayOfWeek = wire_.read();
    dt.day = bcdToDec(wire_.read());
    dt.month = bcdToDec(wire_.read());
    dt.year = bcdToDec(wire_.read()) + 2000;
    
    return dt;
}

float DS3231::getTemperature() {
    wire_.beginTransmission(0x68);
    wire_.write(0x11);
    if (wire_.endTransmission() != 0) return 0.0f;
    
    if (wire_.requestFrom(0x68, 2) != 2) return 0.0f;
    
    uint8_t msb = wire_.read();
    uint8_t lsb = wire_.read();
    
    return (float)msb + ((lsb >> 6) * 0.25f);
}

uint8_t DS3231::bcdToDec(uint8_t val) {
    return ((val / 16 * 10) + (val % 16));
}

uint8_t DS3231::decToBcd(uint8_t val) {
    return ((val / 10 * 16) + (val % 10));
}

} // namespace GLT
