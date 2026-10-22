"""
eski.db → glove_test.db veri aktarım scripti.

Kurallar:
- glove_test.db (yeni) formatına uymayan sütunlar atlanır.
- Mevcut veriler (admin gibi) güncellenir, çakışmayan veriler eklenir.
- batch_templates / batch_template_ports yeni DB'de yok → atlanır.
- Yedek alınır: glove_test_backup.db
"""
import sqlite3
import shutil
import os

ESKI_DB = r"C:\Users\Ahmed Dursun\Desktop\db\eski.db"
YENI_DB = r"C:\Users\Ahmed Dursun\Desktop\db\glove_test.db"
BACKUP  = r"C:\Users\Ahmed Dursun\Desktop\db\glove_test_backup.db"

# ─── Yedek al ───
shutil.copy2(YENI_DB, BACKUP)
print(f"[OK] Yedek alındı: {BACKUP}")

old = sqlite3.connect(ESKI_DB)
old.row_factory = sqlite3.Row
new = sqlite3.connect(YENI_DB)
new.execute("PRAGMA foreign_keys = OFF")
new.execute("PRAGMA journal_mode = WAL")

def get_columns(conn, table):
    """Tablodaki sütun adlarını döndür."""
    cur = conn.execute(f"PRAGMA table_info([{table}])")
    return [row[1] for row in cur.fetchall()]

def migrate_table(table, *, update_id=None, skip_ids=None, column_map=None, extra_filter=None):
    """
    Genel tablo aktarım fonksiyonu.
    - update_id: Bu ID'yi UPDATE ile güncelle (örn admin)
    - skip_ids: Bu ID'leri atla (zaten update ediliyorsa)
    - column_map: {old_col: new_col} eşleştirmesi
    - extra_filter: Eski DB'den çekerken WHERE koşulu
    """
    old_cols = get_columns(old, table)
    new_cols = get_columns(new, table)
    
    # Yeni DB'de olan sütunlarla eşleşen eski sütunları bul
    if column_map:
        # column_map: old_name -> new_name
        transfer_pairs = []  # (old_col, new_col) çiftleri
        for nc in new_cols:
            # Önce map'te ters ara (new_col hangi old_col'dan geliyor)
            matched = False
            for oc, mapped_nc in column_map.items():
                if mapped_nc == nc and oc in old_cols:
                    transfer_pairs.append((oc, nc))
                    matched = True
                    break
            if not matched and nc in old_cols:
                transfer_pairs.append((nc, nc))
    else:
        # Direkt eşleşen sütunları al
        common = [c for c in new_cols if c in old_cols]
        transfer_pairs = [(c, c) for c in common]
    
    old_select = ", ".join(f"[{oc}]" for oc, nc in transfer_pairs)
    new_insert_cols = ", ".join(f"[{nc}]" for oc, nc in transfer_pairs)
    placeholders = ", ".join("?" for _ in transfer_pairs)
    
    query = f"SELECT {old_select} FROM [{table}]"
    if extra_filter:
        query += f" WHERE {extra_filter}"
    
    rows = old.execute(query).fetchall()
    
    inserted = 0
    updated = 0
    skipped = 0
    
    for row in rows:
        values = list(row)
        # ID sütununun indeksi (genelde ilk sütun)
        id_col_idx = None
        for i, (oc, nc) in enumerate(transfer_pairs):
            if nc == 'id':
                id_col_idx = i
                break
        
        row_id = values[id_col_idx] if id_col_idx is not None else None
        
        if skip_ids and row_id in skip_ids:
            skipped += 1
            continue
        
        if update_id is not None and row_id == update_id:
            # UPDATE
            set_clause = ", ".join(f"[{nc}] = ?" for oc, nc in transfer_pairs if nc != 'id')
            update_vals = [v for i, v in enumerate(values) if transfer_pairs[i][1] != 'id']
            try:
                new.execute(f"UPDATE [{table}] SET {set_clause} WHERE id = ?", update_vals + [update_id])
                updated += 1
            except Exception as e:
                print(f"  [WARN] UPDATE {table} id={update_id}: {e}")
                skipped += 1
        else:
            # INSERT
            try:
                new.execute(f"INSERT INTO [{table}] ({new_insert_cols}) VALUES ({placeholders})", values)
                inserted += 1
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e):
                    skipped += 1  # Zaten var
                else:
                    print(f"  [WARN] INSERT {table}: {e}")
                    skipped += 1
            except Exception as e:
                print(f"  [WARN] INSERT {table}: {e}")
                skipped += 1
    
    print(f"  {table}: {inserted} inserted, {updated} updated, {skipped} skipped (total old: {len(rows)})")

# ══════════════════════════════════════════════════════════
#  1. users — admin (id=1) güncelle, diğerlerini ekle
# ══════════════════════════════════════════════════════════
print("\n[1] users...")
migrate_table("users", update_id=1)

# ══════════════════════════════════════════════════════════
#  2. recipes — yeni şemaya uygun sütunlar
#     Eski'de: target_pressure, target_temperature, duration → YOK yeni'de
#     Eski'de zaten p1_pressure vb. var, bunları direkt al
# ══════════════════════════════════════════════════════════
print("\n[2] recipes...")
migrate_table("recipes")

# ══════════════════════════════════════════════════════════
#  3. glove_ports
# ══════════════════════════════════════════════════════════
print("\n[3] glove_ports...")
migrate_table("glove_ports")

# ══════════════════════════════════════════════════════════
#  4. layout_settings
# ══════════════════════════════════════════════════════════
print("\n[4] layout_settings...")
migrate_table("layout_settings")

# ══════════════════════════════════════════════════════════
#  5. system_settings — mevcut anahtarları güncelle, yenileri ekle
# ══════════════════════════════════════════════════════════
print("\n[5] system_settings...")
old_settings = old.execute("SELECT setting_key, setting_value FROM system_settings").fetchall()
ins_count = 0
upd_count = 0
for key, val in old_settings:
    existing = new.execute("SELECT setting_key FROM system_settings WHERE setting_key = ?", (key,)).fetchone()
    if existing:
        new.execute("UPDATE system_settings SET setting_value = ? WHERE setting_key = ?", (val, key))
        upd_count += 1
    else:
        new.execute("INSERT INTO system_settings (setting_key, setting_value) VALUES (?, ?)", (key, val))
        ins_count += 1
print(f"  system_settings: {ins_count} inserted, {upd_count} updated (total old: {len(old_settings)})")

# ══════════════════════════════════════════════════════════
#  6. system_events
# ══════════════════════════════════════════════════════════
print("\n[6] system_events...")
migrate_table("system_events")

# ══════════════════════════════════════════════════════════
#  7. audit_trail
# ══════════════════════════════════════════════════════════
print("\n[7] audit_trail...")
migrate_table("audit_trail")

# ══════════════════════════════════════════════════════════
#  8. test_batches
# ══════════════════════════════════════════════════════════
print("\n[8] test_batches...")
migrate_table("test_batches")

# ══════════════════════════════════════════════════════════
#  9. test_records — eski'de "port" sütunu var, yeni'de yok
#     Sadece ortak sütunları aktar (port atlanır otomatik)
# ══════════════════════════════════════════════════════════
print("\n[9] test_records...")
migrate_table("test_records")

# ══════════════════════════════════════════════════════════
# 10. batch_ports
# ══════════════════════════════════════════════════════════
print("\n[10] batch_ports...")
migrate_table("batch_ports")

# ══════════════════════════════════════════════════════════
# 11. electronic_signatures
# ══════════════════════════════════════════════════════════
print("\n[11] electronic_signatures...")
migrate_table("electronic_signatures")

# ══════════════════════════════════════════════════════════
# 12. sqlite_sequence güncelle
# ══════════════════════════════════════════════════════════
print("\n[12] sqlite_sequence güncelleniyor...")
for table in ['users', 'recipes', 'glove_ports', 'layout_settings', 'system_events',
              'audit_trail', 'test_batches', 'test_records', 'batch_ports', 'electronic_signatures']:
    try:
        max_id = new.execute(f"SELECT MAX(id) FROM [{table}]").fetchone()[0]
        if max_id:
            existing = new.execute("SELECT name FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
            if existing:
                new.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (max_id, table))
            else:
                new.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, max_id))
    except Exception as e:
        print(f"  [WARN] sqlite_sequence {table}: {e}")

# ══════════════════════════════════════════════════════════
# batch_templates, batch_template_ports → ATLA (yeni DB'de yok)
# ══════════════════════════════════════════════════════════
print("\n[SKIP] batch_templates — yeni DB'de bu tablo yok")
print("[SKIP] batch_template_ports — yeni DB'de bu tablo yok")

# ── Kaydet ──
new.commit()
old.close()
new.close()

# ── Doğrulama ──
print("\n" + "="*60)
print("  DOĞRULAMA")
print("="*60)
check = sqlite3.connect(YENI_DB)
tables = check.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name").fetchall()
for (tbl,) in tables:
    count = check.execute(f"SELECT COUNT(*) FROM [{tbl}]").fetchone()[0]
    print(f"  {tbl}: {count} rows")
check.close()

print("\n[OK] Migrasyon tamamlandı!")
print(f"  Yedek: {BACKUP}")
print(f"  Hedef: {YENI_DB}")
