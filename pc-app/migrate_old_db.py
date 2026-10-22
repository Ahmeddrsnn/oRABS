"""
Eski glove_test.db veritabanını yeni şemaya uyarlar.
Verilere DOKUNMAZ — sadece eksik sütunları/tabloları ekler.

Kullanım:
  python migrate_old_db.py
  python migrate_old_db.py C:\path\to\glove_test.db
"""
import sqlite3
import sys
import os
import shutil
from datetime import datetime

DEFAULT_PATH = r'C:\Users\LCC\Desktop\database\glove_test.db'

def migrate(db_path: str):
    if not os.path.exists(db_path):
        print(f"HATA: {db_path} bulunamadı!")
        sys.exit(1)

    # ── Yedek al ──
    backup = db_path + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, backup)
    print(f"Yedek alındı: {backup}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    def get_columns(table):
        c.execute(f"PRAGMA table_info([{table}])")
        return {r['name'] for r in c.fetchall()}

    def table_exists(table):
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return c.fetchone() is not None

    def add_column(table, col, typedef):
        cols = get_columns(table)
        if col not in cols:
            c.execute(f"ALTER TABLE [{table}] ADD COLUMN {col} {typedef}")
            print(f"  + {table}.{col} ({typedef})")
            return True
        return False

    changes = 0

    # ════════════════════════════════════════════════════════════
    # 1. users tablosu
    # ════════════════════════════════════════════════════════════
    print("\n[users]")
    if add_column('users', 'must_change_password', 'INTEGER DEFAULT 0'):
        changes += 1
    if add_column('users', 'pin', 'TEXT'):
        changes += 1

    # ════════════════════════════════════════════════════════════
    # 2. test_records tablosu
    # ════════════════════════════════════════════════════════════
    print("\n[test_records]")
    if add_column('test_records', 'device_id', 'TEXT'):
        changes += 1
    if add_column('test_records', 'port_number', 'INTEGER'):
        changes += 1

    # Eski 'port' sütunundan 'port_number'a veri taşı (eğer port var ve port_number boşsa)
    tr_cols = get_columns('test_records')
    if 'port' in tr_cols and 'port_number' in tr_cols:
        c.execute("UPDATE test_records SET port_number = port WHERE port IS NOT NULL AND port_number IS NULL")
        moved = c.rowcount
        if moved > 0:
            print(f"  ~ {moved} kayıt: port → port_number aktarıldı")
            changes += 1

    # ════════════════════════════════════════════════════════════
    # 3. recipes tablosu — yeni parametre sütunları
    # ════════════════════════════════════════════════════════════
    print("\n[recipes]")
    recipe_new_cols = [
        ('p1_pressure', 'INTEGER DEFAULT 500'),
        ('p2_hysteresis', 'INTEGER DEFAULT 50'),
        ('p3_limit', 'INTEGER DEFAULT 100'),
        ('t1_inflation', 'INTEGER DEFAULT 10'),
        ('t2_stabilization', 'INTEGER DEFAULT 10'),
        ('t3_measurement', 'INTEGER DEFAULT 60'),
        ('p8_success_drop', 'INTEGER DEFAULT 200'),
        ('is_active', 'INTEGER DEFAULT 1'),
    ]
    for col, typedef in recipe_new_cols:
        if add_column('recipes', col, typedef):
            changes += 1

    # Eski 'target_pressure' → 'p1_pressure' için: eğer p1_pressure hâlâ 500 default ama
    # target_pressure farklıysa, güncelle
    rcp_cols = get_columns('recipes')
    if 'target_pressure' in rcp_cols and 'p1_pressure' in rcp_cols:
        c.execute("""
            UPDATE recipes SET p1_pressure = CAST(target_pressure AS INTEGER)
            WHERE p1_pressure = 500 AND target_pressure IS NOT NULL AND target_pressure != 500
        """)
        if c.rowcount > 0:
            print(f"  ~ {c.rowcount} reçete: target_pressure → p1_pressure kopyalandı")
            changes += 1

    # ════════════════════════════════════════════════════════════
    # 4. Eksik tablolar (IF NOT EXISTS ile güvenli)
    # ════════════════════════════════════════════════════════════
    print("\n[tablolar]")
    if not table_exists('system_settings'):
        c.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT
            )
        """)
        print("  + system_settings tablosu oluşturuldu")
        changes += 1

    if not table_exists('layout_settings'):
        c.execute("""
            CREATE TABLE IF NOT EXISTS layout_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT,
                scale_factor REAL DEFAULT 1.0
            )
        """)
        print("  + layout_settings tablosu oluşturuldu")
        changes += 1

    if not table_exists('glove_ports'):
        c.execute("""
            CREATE TABLE IF NOT EXISTS glove_ports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                x_pos INTEGER NOT NULL,
                y_pos INTEGER NOT NULL,
                rfid_tag TEXT,
                recipe_id INTEGER,
                last_updated TEXT,
                FOREIGN KEY (recipe_id) REFERENCES recipes(id)
            )
        """)
        print("  + glove_ports tablosu oluşturuldu")
        changes += 1

    if not table_exists('test_batches'):
        c.execute("""
            CREATE TABLE IF NOT EXISTS test_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_name TEXT NOT NULL,
                operator_id INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                FOREIGN KEY (operator_id) REFERENCES users(id)
            )
        """)
        print("  + test_batches tablosu oluşturuldu")
        changes += 1

    if not table_exists('batch_ports'):
        c.execute("""
            CREATE TABLE IF NOT EXISTS batch_ports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                port_id INTEGER NOT NULL,
                rfid_tag TEXT,
                test_record_id INTEGER,
                status TEXT NOT NULL DEFAULT 'PENDING',
                explanation TEXT,
                FOREIGN KEY (batch_id) REFERENCES test_batches(id),
                FOREIGN KEY (test_record_id) REFERENCES test_records(id)
            )
        """)
        print("  + batch_ports tablosu oluşturuldu")
        changes += 1

    if not table_exists('batch_templates'):
        c.execute("""
            CREATE TABLE IF NOT EXISTS batch_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_name TEXT NOT NULL UNIQUE,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        """)
        print("  + batch_templates tablosu oluşturuldu")
        changes += 1

    if not table_exists('batch_template_ports'):
        c.execute("""
            CREATE TABLE IF NOT EXISTS batch_template_ports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL,
                port_id INTEGER NOT NULL,
                FOREIGN KEY (template_id) REFERENCES batch_templates(id) ON DELETE CASCADE,
                FOREIGN KEY (port_id) REFERENCES glove_ports(id)
            )
        """)
        print("  + batch_template_ports tablosu oluşturuldu")
        changes += 1

    # ════════════════════════════════════════════════════════════
    # 5. Varsayılan ayarlar (yoksa ekle)
    # ════════════════════════════════════════════════════════════
    print("\n[system_settings]")
    defaults = [
        ('auto_logout_minutes', '15'),
        ('company_logo_path', 'assets/logo.jpg'),
    ]
    for key, val in defaults:
        c.execute('INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES (?, ?)', (key, val))
        if c.rowcount > 0:
            print(f"  + {key} = {val}")
            changes += 1

    # ════════════════════════════════════════════════════════════
    # 6. Integrity check
    # ════════════════════════════════════════════════════════════
    print("\n[bütünlük kontrolü]")
    c.execute("PRAGMA integrity_check")
    result = c.fetchone()[0]
    print(f"  SQLite integrity_check: {result}")

    conn.commit()
    conn.close()

    print(f"\n{'='*50}")
    if changes > 0:
        print(f"Toplam {changes} değişiklik yapıldı.")
    else:
        print("Veritabanı zaten güncel — değişiklik gerekmedi.")
    print(f"Yedek: {backup}")
    print("Göç tamamlandı.")


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    print(f"Veritabanı: {path}")
    migrate(path)
