# Build Instructions

Since PlatformIO may not be available, here are alternative methods:

## Option 1: Arduino IDE

1. Open Arduino IDE
2. Install ESP32 board support
3. File → Open → `firmware/glt-v3/src/main.cpp`
4. Tools → Board → ESP32 S3 Dev Module
5. Tools → Upload Speed → 921600
6. Tools → Port → COM11
7. Upload

## Option 2: Arduino CLI (Recommended)

```powershell
# Install ESP32 platform (one time)
arduino-cli core install esp32:esp32

# Compile
arduino-cli compile --fqbn esp32:esp32:esp32s3 firmware/glt-v3/src

# Upload
arduino-cli upload -p COM11 --fqbn esp32:esp32:esp32s3 firmware/glt-v3/src

# Monitor
arduino-cli monitor -p COM11 -c baudrate=115200
```

## Option 3: Install PlatformIO

```powershell
# Install PlatformIO CLI
pip install platformio

# Build
cd firmware/glt-v3
pio run

# Upload
pio run --target upload

# Monitor
pio device monitor
```

##Next Steps

Once compiled and uploaded, open Serial Monitor at 115200 baud.

You should see:
```
═══════════════════════════════════════════════════════════════
   ESP32-S3 GLT v3 - Clean Code Edition
═══════════════════════════════════════════════════════════════

[    100] [INFO ][CORE   ] Logger initialized
[    120] [INFO ][CORE   ] Chip: ESP32-S3
...
Ready>
```

Try commands:
- `REG:0x1010=52` - Write register
- `STATUS` - Show all registers
- `HELP` - List commands
