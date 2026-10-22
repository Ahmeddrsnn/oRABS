import sqlite3, json

OLD = r"C:\Users\LCC\Desktop\database\glove_test.db"
NEW = r"c:\LCC\software\LCC\522_GLT\HardwareSoftware\teslim\glt4.3 bilim\software\glvt pc taraf\database\glove_test.db"

for label, path in [("OLD (Desktop)", OLD), ("NEW (current)", NEW)]:
    print(f"\n=== {label}: {path} ===")
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print("Tables:", tables)
    
    # Check schema_version if exists
    if 'schema_version' in tables or 'system_settings' in tables:
        try:
            c.execute("SELECT setting_value FROM system_settings WHERE setting_key='schema_version'")
            v = c.fetchone()
            print("Schema version:", v)
        except Exception as e:
            print("schema_version err:", e)

    # Show glove_ports schema and a sample row
    if 'glove_ports' in tables:
        c.execute("PRAGMA table_info(glove_ports)")
        cols = c.fetchall()
        print("\nglove_ports columns:")
        for col in cols:
            print(f"  {col[1]} ({col[2]})")
        c.execute("SELECT id, name, x_pos, y_pos, rfid_tag, recipe_id FROM glove_ports LIMIT 5")
        print("\nSample glove_ports rows:")
        for row in c.fetchall():
            print(f"  {row}")
        c.execute("SELECT COUNT(*) FROM glove_ports")
        print(f"  Total rows: {c.fetchone()[0]}")
    
    # Show test_records port-related columns
    if 'test_records' in tables:
        c.execute("PRAGMA table_info(test_records)")
        cols = [col[1] for col in c.fetchall()]
        print(f"\ntest_records columns: {cols}")
        c.execute("SELECT COUNT(*) FROM test_records")
        print(f"  Total rows: {c.fetchone()[0]}")
        # Sample port values
        if 'port' in cols or 'port_number' in cols:
            sel = []
            if 'port' in cols: sel.append('port')
            if 'port_number' in cols: sel.append('port_number')
            c.execute(f"SELECT DISTINCT {', '.join(sel)} FROM test_records LIMIT 20")
            print(f"  Distinct {sel} values:")
            for row in c.fetchall():
                print(f"    {row}")
    
    # batch_ports
    if 'batch_ports' in tables:
        c.execute("PRAGMA table_info(batch_ports)")
        cols = [col[1] for col in c.fetchall()]
        print(f"\nbatch_ports columns: {cols}")
    
    conn.close()
