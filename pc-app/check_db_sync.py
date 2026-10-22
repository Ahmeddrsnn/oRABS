import sqlite3, re, sys
sys.path.insert(0, 'src')
from gui.esp_now_control import port_from_db_name, encode_port, decode_port, port_display

conn = sqlite3.connect('database/glove_test.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute('SELECT id, name, rfid_tag FROM glove_ports ORDER BY id')
rows = c.fetchall()

print("=== RFID Sync Analizi: DB name -> encode -> DWIN gösterim ===\n")
print(f"{'ID':<4} {'DB Name':<25} {'Encoded':<8} {'DWIN Sol':<9} {'DWIN Sag':<9} {'Beklenen':<10} {'OK?'}")
print("-" * 80)

for r in rows:
    name = r['name']
    encoded = port_from_db_name(name)
    left = encoded >> 8
    right = encoded & 0xFF
    
    # Beklenen format
    m = re.search(r'(\d+)\s*/\s*(\d+)', name)
    if m:
        expected = f"{m.group(1)}/{m.group(2)}"
        ok = "OK" if left == int(m.group(1)) and right == int(m.group(2)) else "HATALI!"
    else:
        m2 = re.search(r'\d+', name)
        expected = m2.group() if m2 else "?"
        # Tek sayılı portlarda: encoded < 256 olmalı VE DWIN'e direkt yazılmalı
        # Ama dwinWritePort(8) → sol=0, sag=8 → DWIN "0" ve "8" gösterir
        ok = "TEK" if encoded < 256 else "HATALI!"
    
    print(f"{r['id']:<4} {name:<25} {encoded:<8} {left:<9} {right:<9} {expected:<10} {ok}")

conn.close()
