
def calculate_crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

# 1. Logo Command: Write 94 (0x5E) to VP 0x6000
# Cmd(82) + Addr(60 00) + Data(00 5E)
logo_payload = [0x82, 0x60, 0x00, 0x00, 0x5E]
logo_crc = calculate_crc16(logo_payload)
print(f"Logo Payload: {[hex(x) for x in logo_payload]}")
print(f"Logo CRC: {hex(logo_crc)} (Low: {hex(logo_crc & 0xFF)}, High: {hex(logo_crc >> 8)})")

# 2. Page Change Command: Write 0 to VP 0x0084 (Address 00 84)
# Data: 5A 01 00 00 (Fixed 5A 01 + Page 00 00)
# Cmd(82) + Addr(00 84) + Data(5A 01 00 00)
page_payload = [0x82, 0x00, 0x84, 0x5A, 0x01, 0x00, 0x00]
page_crc = calculate_crc16(page_payload)
print(f"Page Payload: {[hex(x) for x in page_payload]}")
print(f"Page CRC: {hex(page_crc)} (Low: {hex(page_crc & 0xFF)}, High: {hex(page_crc >> 8)})")
