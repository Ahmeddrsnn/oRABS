import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'database', 'glove_test.db')
print(f"DB: {db_path}")
print(f"Exists: {os.path.exists(db_path)}")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# List tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(f"\nTables: {tables}")

# Check glove_ports
if 'glove_ports' in tables:
    c.execute("SELECT * FROM glove_ports LIMIT 20")
    rows = c.fetchall()
    print(f"\n=== glove_ports ({len(rows)} rows) ===")
    if rows:
        print(f"Columns: {[d[0] for d in c.description]}")
        for r in rows:
            print(dict(r))
else:
    print("\n!! glove_ports tablosu YOK")

# Check test_records port_number
if 'test_records' in tables:
    c.execute("SELECT port_number, COUNT(*) as cnt FROM test_records GROUP BY port_number LIMIT 20")
    rows = c.fetchall()
    print(f"\n=== test_records port_number distribution ===")
    for r in rows:
        print(f"  port_number={r[0]}, count={r[1]}")
    
    # Sample rows
    c.execute("SELECT id, port_number, glove_batch_number, test_start_time FROM test_records ORDER BY id DESC LIMIT 5")
    rows = c.fetchall()
    print(f"\n=== test_records recent ===")
    for r in rows:
        print(dict(r))
else:
    print("\n!! test_records tablosu YOK")

conn.close()
