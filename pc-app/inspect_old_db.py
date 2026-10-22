"""Inspect old database schema and data counts."""
import sqlite3
import sys

DB_PATH = r'C:\Users\LCC\Desktop\database\glove_test.db'

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 1. List all tables
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in c.fetchall()]
print("=== TABLES ===")
for t in tables:
    c.execute(f"SELECT COUNT(*) FROM [{t}]")
    cnt = c.fetchone()[0]
    print(f"  {t}: {cnt} rows")

print()

# 2. Schema for each table
for t in tables:
    c.execute(f"PRAGMA table_info([{t}])")
    cols = c.fetchall()
    print(f"=== {t} ===")
    for col in cols:
        print(f"  {col['name']:30s} {col['type']:20s} {'NOT NULL' if col['notnull'] else ''} {'PK' if col['pk'] else ''} default={col['dflt_value']}")
    print()

conn.close()
