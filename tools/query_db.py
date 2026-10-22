import sqlite3

import os, glob

# Find all .db files and check sizes
base = r"c:\LCC\software\LCC\522_GLT\HardwareSoftware\teslim\glt4.3 bilim\software\glvt pc taraf"
for f in glob.glob(os.path.join(base, "**", "*.db"), recursive=True):
    sz = os.path.getsize(f)
    print(f"  {sz:>10} bytes  {f}")

# Use the biggest/most likely one
db_path = r"c:\LCC\software\LCC\522_GLT\HardwareSoftware\teslim\glt4.3 bilim\software\glvt pc taraf\database\glove_test.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

# List tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

# Show schema for each table
for t in tables:
    c.execute(f"PRAGMA table_info({t})")
    cols = c.fetchall()
    print(f"\n--- {t} ---")
    for col in cols:
        print(f"  {col[1]} ({col[2]})")

# Try to find last test
for t in tables:
    c.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 1")
    row = c.fetchone()
    if row:
        c.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in c.fetchall()]
        print(f"\n=== Last row in {t} ===")
        for col_name, val in zip(cols, row):
            print(f"  {col_name}: {val}")

conn.close()
