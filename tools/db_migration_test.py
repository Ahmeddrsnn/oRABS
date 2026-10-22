"""
Migration simülasyonu: Eski DB'nin geçici kopyasını oluşturup
yeni programın init/migration kodunu çalıştırır. Veriyi doğrular.
"""
import shutil, os, sys, tempfile, sqlite3

OLD = r"C:\Users\LCC\Desktop\database\glove_test.db"

# Kopya oluştur
tmp_dir = tempfile.mkdtemp(prefix="db_migrate_test_")
test_db = os.path.join(tmp_dir, "glove_test.db")
shutil.copy2(OLD, test_db)
print(f"Test DB kopyası: {test_db}")

# Önce kayıt sayılarını al (migration sonrası karşılaştırmak için)
conn = sqlite3.connect(test_db)
c = conn.cursor()
before_counts = {}
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
for (t,) in c.fetchall():
    c.execute(f"SELECT COUNT(*) FROM {t}")
    before_counts[t] = c.fetchone()[0]
conn.close()
print(f"\n--- Migration ÖNCESİ kayıt sayıları ---")
for t, n in sorted(before_counts.items()):
    print(f"  {t:30s}: {n}")

# Yeni programın database modülünü import et ve kopya üzerinde çalıştır
sys.path.insert(0, r"c:\LCC\software\LCC\522_GLT\HardwareSoftware\teslim\glt4.3 bilim\software\glvt pc taraf\src")
try:
    from core.database import Database
    db = Database(db_path=test_db)
    db.initialize_database()
    print("\n✅ init_database() başarılı çalıştı")
except Exception as e:
    print(f"\n❌ init_database() HATASI: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Migration sonrası kayıt sayılarını al
conn = sqlite3.connect(test_db)
c = conn.cursor()
after_counts = {}
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
for (t,) in c.fetchall():
    c.execute(f"SELECT COUNT(*) FROM {t}")
    after_counts[t] = c.fetchone()[0]
conn.close()

print(f"\n--- Migration SONRASI kayıt sayıları ---")
all_ok = True
for t, n_after in sorted(after_counts.items()):
    n_before = before_counts.get(t, 0)
    diff = n_after - n_before
    marker = "✅" if diff >= 0 else "❌"
    extra = f" (+{diff} eklendi)" if diff > 0 else (" (değişmedi)" if diff == 0 else f" (KAYIP! {diff})")
    print(f"  {marker} {t:30s}: {n_before} → {n_after}{extra}")
    if diff < 0:
        all_ok = False

# Test sorguları çalıştır - yeni programın yapacağı tipik işlemleri simüle et
print(f"\n--- Tipik sorgu testleri ---")
conn = sqlite3.connect(test_db)
c = conn.cursor()

queries = [
    ("test_records SELECT", "SELECT id, test_id, glove_batch_number, port_number, device_id FROM test_records LIMIT 3"),
    ("recipes SELECT (yeni kolonlar)", "SELECT id, name, p1_pressure, p2_hysteresis, t1_inflation, t2_stabilization, t3_measurement, p8_success_drop, is_active FROM recipes LIMIT 3"),
    ("users SELECT (yeni kolonlar)", "SELECT id, username, must_change_password, pin FROM users LIMIT 3"),
    ("glove_ports SELECT", "SELECT id, name, rfid_tag, recipe_id FROM glove_ports LIMIT 3"),
    ("audit_trail SELECT", "SELECT COUNT(*) FROM audit_trail"),
    ("electronic_signatures SELECT", "SELECT COUNT(*) FROM electronic_signatures"),
]

for label, q in queries:
    try:
        c.execute(q)
        rows = c.fetchall()
        print(f"  ✅ {label}: {len(rows)} satır")
    except Exception as e:
        print(f"  ❌ {label}: {type(e).__name__}: {e}")
        all_ok = False
conn.close()

# Geçici dosyayı temizle
shutil.rmtree(tmp_dir)
print(f"\n(Geçici dizin silindi: {tmp_dir})")

print("\n" + "=" * 60)
if all_ok:
    print("✅ TÜM TESTLER GEÇTİ — Eski DB yeni programla %100 UYUMLU")
else:
    print("⚠ BAZI TESTLER BAŞARISIZ")
print("=" * 60)
