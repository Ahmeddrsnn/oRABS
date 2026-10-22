# ESP32-S3 GLT v3 - Clean Code Edition

Modern, modular firmware for GLT v3 test system with:
- SOLID principles
- Hardware abstraction layers
- Comprehensive logging
- Serial-based debugging
- Test-driven development

## Quick Start

```bash
# Build
pio run

# Upload to ESP32-S3
pio run --target upload

# Monitor serial output
pio device monitor
```

## Architecture

See `docs/` folder for detailed documentation.

## Hardware

- **MCU:** ESP32-S3 (4MB Flash, PSRAM)
- **Sensors:** Honeywell ABP2, DS3231 RTC, ADS1115
- **RFID:** RDM6300 125kHz reader
- **Display:** Serial debug (DWIN later)
- **Storage:** SD Card + NVS

## Features

- ✅ RFID tag management (30 slots)
- ✅ Container pressure control
- ✅ Test execution system
- ✅ Battery monitoring
- ✅ Data logging (SD card)
- ✅ OTA firmware updates
- ✅ Multi-user support

## License

Proprietary - GLT v3 Project
