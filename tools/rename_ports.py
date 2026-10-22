"""
Eski masaüstü database'inde glove_ports.name kolonunu güncelle.
SADECE name sütununu değiştirir, diğer hiçbir veriye dokunmaz.
"""
import sqlite3

DB = r"C:\Users\LCC\Desktop\database\glove_test.db"

# Eski name → Yeni name
mapping = {
    'Port 01': '9 Numaralı Eldiven',
    'Port 02': '8 Numaralı Eldiven',
    'Port 03': '7 Numaralı Eldiven',
    'Port 04': '6 Numaralı Eldiven',
    'Port 05': '5/1 Numaralı Eldiven',
    'Port 06': '5/2 Numaralı Eldiven',
    'Port 07': '4/1 Numaralı Eldiven',
    'Port 08': '4/2 Numaralı Eldiven',
    'Port 09': '3/1 Numaralı Eldiven',
    'Port 10': '3/2 Numaralı Eldiven',
    'Port 11': '2/1 Numaralı Eldiven',
    'Port 12': '2/2 Numaralı Eldiven',
    'Port 13': '1/1 Numaralı Eldiven',
    'Port 14': '1/2 Numaralı Eldiven',
    'Port 15': '32/1 Numaralı Eldiven',
    'Port 16': '32/2 Numaralı Eldiven',
    'Port 17': '30/1 Numaralı Eldiven',
    'Port 18': '30/2 Numaralı Eldiven',
    'Port 19': '29/1 Numaralı Eldiven',
    'Port 20': '29/2 Numaralı Eldiven',
    'Port 21': '27 Numaralı Eldiven',
    'Port 22': '26/1 Numaralı Eldiven',
    'Port 23': '26/2 Numaralı Eldiven',
    'Port 24': '24 Numaralı Eldiven',
    'Port 25': '20 Numaralı Eldiven',
    'Port 26': '19/1 Numaralı Eldiven',
    'Port 27': '19/2 Numaralı Eldiven',
    'Port 28': '16 Numaralı Eldiven',
}

conn = sqlite3.connect(DB)
c = conn.cursor()

# Önce mevcut isimleri kontrol et
c.execute("SELECT id, name FROM glove_ports")
existing = {r[1]: r[0] for r in c.fetchall()}

print("=== GÜNCELLEME ÖNCESİ ===")
for old, new in mapping.items():
    pid = existing.get(old)
    if pid is None:
        print(f"  ⚠ '{old}' DB'de bulunamadı")
    else:
        print(f"  ID={pid}  '{old}' → '{new}'")

# Güncelleme: önce hepsi geçici prefix ile değişsin, sonra son isime — name UNIQUE değil ama yine de güvenli olalım
print("\n=== GÜNCELLEME UYGULANIYOR ===")
updated = 0
for old, new in mapping.items():
    if old in existing:
        c.execute("UPDATE glove_ports SET name=? WHERE name=?", (new, old))
        updated += c.rowcount

conn.commit()

# Sonrası
print(f"\n{updated} satır güncellendi. Yeni durum:")
c.execute("SELECT id, name, rfid_tag, recipe_id FROM glove_ports ORDER BY id")
for r in c.fetchall():
    print(f"  ID={r[0]:3d}  name={r[1]!r:<30}  rfid={r[2]}  recipe_id={r[3]}")

conn.close()
print("\n✅ Tamam")
