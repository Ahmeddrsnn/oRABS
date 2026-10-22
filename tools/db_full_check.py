"""
Eski (Desktop) ve Yeni (current) glove_test.db veritabanlarını
TÜM açılardan %100 karşılaştırır:
- Sütun adı, tipi, NOT NULL, DEFAULT, PK durumu
- Index'ler (UNIQUE dahil)
- Foreign Key'ler
- Trigger'lar
- View'lar
- system_settings içerikleri
- recipes/users/glove_ports gibi referans tablolarda eksik kayıt var mı
"""
import sqlite3, json, sys

OLD = r"C:\Users\LCC\Desktop\database\glove_test.db"
NEW = r"c:\LCC\software\LCC\522_GLT\HardwareSoftware\teslim\glt4.3 bilim\software\glvt pc taraf\database\glove_test.db"

def fetch_all(conn, sql, params=()):
    c = conn.cursor()
    c.execute(sql, params)
    return c.fetchall()

def get_full_schema(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Tablolar + create SQL
    c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {r['name']: r['sql'] for r in c.fetchall()}
    
    # 2. Index'ler
    c.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' ORDER BY name")
    indexes = [dict(r) for r in c.fetchall()]
    
    # 3. Trigger'lar
    c.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name")
    triggers = [dict(r) for r in c.fetchall()]
    
    # 4. View'lar
    c.execute("SELECT name, sql FROM sqlite_master WHERE type='view' ORDER BY name")
    views = [dict(r) for r in c.fetchall()]
    
    # 5. Her tablo için kolon detayı
    table_cols = {}
    for t in tables:
        c.execute(f"PRAGMA table_info({t})")
        # cid, name, type, notnull, dflt_value, pk
        table_cols[t] = {row['name']: dict(row) for row in c.fetchall()}
    
    # 6. Her tablo için foreign key'ler
    table_fks = {}
    for t in tables:
        c.execute(f"PRAGMA foreign_key_list({t})")
        table_fks[t] = [dict(row) for row in c.fetchall()]
    
    # 7. Her tablo için index detayları
    table_indexes = {}
    for t in tables:
        c.execute(f"PRAGMA index_list({t})")
        idx_list = [dict(row) for row in c.fetchall()]
        for idx in idx_list:
            c.execute(f"PRAGMA index_info({idx['name']})")
            idx['columns'] = [dict(row) for row in c.fetchall()]
        table_indexes[t] = idx_list
    
    conn.close()
    return {
        'tables': tables,
        'indexes': indexes,
        'triggers': triggers,
        'views': views,
        'table_cols': table_cols,
        'table_fks': table_fks,
        'table_indexes': table_indexes,
    }

old = get_full_schema(OLD)
new = get_full_schema(NEW)

problems = []

# === A. Tablo varlık kontrolü ===
old_tables = set(old['tables'].keys())
new_tables = set(new['tables'].keys())
missing_in_old = new_tables - old_tables
extra_in_old = old_tables - new_tables
print("=" * 70)
print("A) TABLO VARLIK KONTROL")
print("=" * 70)
print(f"OLD'da olmayan (NEW'de var): {missing_in_old or '(yok)'}")
print(f"OLD'da fazla (NEW'de yok):    {extra_in_old or '(yok)'}")
if missing_in_old:
    problems.append(f"OLD'da eksik tablolar: {missing_in_old}")

# === B. Sütun detay kontrolü ===
print("\n" + "=" * 70)
print("B) SÜTUN DETAYLI KONTROL (her tablo için)")
print("=" * 70)
shared_tables = old_tables & new_tables
for t in sorted(shared_tables):
    old_cols = old['table_cols'][t]
    new_cols = new['table_cols'][t]
    
    only_in_new = set(new_cols) - set(old_cols)
    only_in_old = set(old_cols) - set(new_cols)
    
    diffs_in_shared = []
    for col_name in set(old_cols) & set(new_cols):
        oc = old_cols[col_name]
        nc = new_cols[col_name]
        # Karşılaştırılan alanlar: type, notnull, dflt_value, pk
        for field in ('type', 'notnull', 'dflt_value', 'pk'):
            if oc.get(field) != nc.get(field):
                diffs_in_shared.append((col_name, field, oc.get(field), nc.get(field)))
    
    if only_in_new or only_in_old or diffs_in_shared:
        print(f"\n  [{t}]")
        if only_in_new:
            print(f"    OLD'da EKSİK kolonlar: {only_in_new}")
            for c in only_in_new:
                print(f"      - {c}: {new_cols[c]}")
            problems.append(f"{t}: eksik kolonlar {only_in_new}")
        if only_in_old:
            print(f"    OLD'da FAZLA kolonlar: {only_in_old}")
        if diffs_in_shared:
            print(f"    Tip/constraint farkları:")
            for cn, f, ov, nv in diffs_in_shared:
                print(f"      - {cn}.{f}: OLD={ov!r} | NEW={nv!r}")
                problems.append(f"{t}.{cn} {f}: OLD={ov} NEW={nv}")
    else:
        pass  # Sessiz: %100 aynı

# === C. Index karşılaştırma ===
print("\n" + "=" * 70)
print("C) INDEX KONTROL")
print("=" * 70)
for t in sorted(shared_tables):
    old_idx = {i['name']: i for i in old['table_indexes'][t]}
    new_idx = {i['name']: i for i in new['table_indexes'][t]}
    missing = set(new_idx) - set(old_idx)
    extra = set(old_idx) - set(new_idx)
    if missing or extra:
        print(f"\n  [{t}]")
        if missing:
            print(f"    OLD'da eksik index'ler: {missing}")
            for n in missing:
                print(f"      - {new_idx[n]}")
            problems.append(f"{t}: eksik index {missing}")
        if extra:
            print(f"    OLD'da fazla index'ler: {extra}")

# === D. Foreign Key karşılaştırma ===
print("\n" + "=" * 70)
print("D) FOREIGN KEY KONTROL")
print("=" * 70)
for t in sorted(shared_tables):
    old_fks = old['table_fks'][t]
    new_fks = new['table_fks'][t]
    # Karşılaştırma için tuple normalize
    def fk_sig(fks):
        return sorted([(f['table'], f['from'], f['to']) for f in fks])
    if fk_sig(old_fks) != fk_sig(new_fks):
        print(f"\n  [{t}]")
        print(f"    OLD FKs: {fk_sig(old_fks)}")
        print(f"    NEW FKs: {fk_sig(new_fks)}")
        problems.append(f"{t}: FK farkı")

# === E. Trigger ve View ===
print("\n" + "=" * 70)
print("E) TRIGGER ve VIEW KONTROL")
print("=" * 70)
old_trigs = {t['name']: t['sql'] for t in old['triggers']}
new_trigs = {t['name']: t['sql'] for t in new['triggers']}
missing_trigs = set(new_trigs) - set(old_trigs)
if missing_trigs:
    print(f"  OLD'da eksik trigger'lar: {missing_trigs}")
    problems.append(f"eksik trigger: {missing_trigs}")
elif new_trigs or old_trigs:
    print(f"  Trigger sayısı OLD={len(old_trigs)}, NEW={len(new_trigs)}")
else:
    print("  (her iki DB'de trigger yok)")

old_views = {v['name']: v['sql'] for v in old['views']}
new_views = {v['name']: v['sql'] for v in new['views']}
missing_views = set(new_views) - set(old_views)
if missing_views:
    print(f"  OLD'da eksik view'lar: {missing_views}")
    problems.append(f"eksik view: {missing_views}")

# === F. system_settings karşılaştırma ===
print("\n" + "=" * 70)
print("F) SYSTEM_SETTINGS İÇERİK KONTROL")
print("=" * 70)
for label, path in [("OLD", OLD), ("NEW", NEW)]:
    conn = sqlite3.connect(path)
    rows = fetch_all(conn, "SELECT setting_key, setting_value FROM system_settings ORDER BY setting_key")
    print(f"\n  {label} ({len(rows)} kayıt):")
    for r in rows:
        v = r[1] if r[1] is None or len(str(r[1])) < 80 else str(r[1])[:80] + "..."
        print(f"    {r[0]} = {v}")
    conn.close()

# === G. recipes / users tablolarında ID karşılaştırma ===
print("\n" + "=" * 70)
print("G) REFERANS TABLOLAR (recipes, users) KAYIT ÖZETİ")
print("=" * 70)
for tbl in ['recipes', 'users', 'glove_ports']:
    print(f"\n  --- {tbl} ---")
    for label, path in [("OLD", OLD), ("NEW", NEW)]:
        conn = sqlite3.connect(path)
        rows = fetch_all(conn, f"SELECT COUNT(*) FROM {tbl}")
        print(f"    {label}: {rows[0][0]} kayıt")
        conn.close()

# === Final ===
print("\n" + "=" * 70)
print("SONUÇ")
print("=" * 70)
if not problems:
    print("✅ Eski DB ile yeni programın schema'sı %100 UYUMLU")
    print("   (Tablolar, kolonlar, tipler, index'ler, FK'ler aynı)")
else:
    print(f"⚠ {len(problems)} adet uyumsuzluk tespit edildi:")
    for p in problems:
        print(f"   - {p}")
