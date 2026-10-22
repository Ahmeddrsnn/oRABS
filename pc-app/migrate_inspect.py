import sqlite3

def show_schema(db_path, label):
    print(f"\n{'='*60}")
    print(f"  {label}: {db_path}")
    print(f"{'='*60}")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cur.fetchall()
    for name, sql in tables:
        print(f"\n--- {name} ---")
        print(sql)
        cur.execute(f"SELECT COUNT(*) FROM [{name}]")
        count = cur.fetchone()[0]
        print(f"  -> {count} rows")
        if count > 0 and count <= 20:
            cur.execute(f"SELECT * FROM [{name}]")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            print(f"  Columns: {cols}")
            for r in rows:
                print(f"    {r}")
        elif count > 20:
            cur.execute(f"SELECT * FROM [{name}] LIMIT 5")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            print(f"  Columns: {cols}")
            for r in rows:
                print(f"    {r}")
            print(f"    ... ({count - 5} more)")
    conn.close()

show_schema(r"C:\Users\Ahmed Dursun\Desktop\db\eski.db", "ESKI DB")
show_schema(r"C:\Users\Ahmed Dursun\Desktop\db\glove_test.db", "GLOVE_TEST DB (YENi)")
