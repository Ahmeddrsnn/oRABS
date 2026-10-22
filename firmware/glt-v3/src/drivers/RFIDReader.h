#ifndef RFID_READER_H
#define RFID_READER_H

#include <Arduino.h>
#include <rdm6300.h>

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// RFID READER (RDM6300 Wrapper)
// ═══════════════════════════════════════════════════════════════════

class RFIDReader {
public:
  RFIDReader();
  ~RFIDReader() = default;

  /**
   * Initialize RFID reader
   * @param rxPin RX pin number (e.g. 19)
   * @param uartNum UART number (e.g. 2)
   * @return true if successful
   */
  bool begin(uint8_t rxPin, uint8_t uartNum = 2);

  /**
   * Update - call periodically to read tags
   */
  void update();

  /**
   * Check if a tag is currently present
   * @return true if tag detected
   */
  bool isTagPresent();

  /**
   * Get current tag ID (valid only if isTagPresent() returns true)
   * @return Tag ID (32-bit)
   */
  uint32_t getCurrentTag();

  /**
   * Get new tag ID (returns ID only once per new tag)
   * @return Tag ID or 0 if no new tag
   */
  uint32_t getNewTag();

  /**
   * Clear current tag
   */
  /**
   * Clear current tag
   */
  void clearTag();

  /**
   * Stop RFID reader and release Serial
   */
  void end();

private:
  Rdm6300 rdm_;
  uint8_t uartNum_;
};

} // namespace GLT

#endif // RFID_READER_H
