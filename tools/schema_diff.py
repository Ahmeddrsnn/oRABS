import sqlite3

OLD = r"C:\Users\LCC\Desktop\database\glove_test.db"
NEW = r"c:\LCC\software\LCC\522_GLT\HardwareSoftware\teslim\glt4.3 bilim\software\glvt pc taraf\database\glove_test.db"

def get_schema(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = sorted([r[0] for r in c.fetchall()])
    schema = {}
    for t in tables:
        c.execute(f"PRAGMA table_info({t})")
        schema[t] = {col[1]: col[2] for col in c.fetchall()}
    conn.close()
    return schema

old_s = get_schema(OLD)
new_s = get_schema(NEW)

# Tables only in one
only_old = set(old_s) - set(new_s)
only_new = set(new_s) - set(old_s)
print("Tables only in OLD:", only_old)
print("Tables only in NEW:", only_new)

print("\n=== Column differences in shared tables ===")
for t in sorted(set(old_s) & set(new_s)):
    old_cols = set(old_s[t].keys())
    new_cols = set(new_s[t].keys())
    missing_in_old = new_cols - old_cols
    missing_in_new = old_cols - new_cols
    if missing_in_old or missing_in_new:
        print(f"\n[{t}]")
        if missing_in_old:
            print(f"  OLD eksik (NEW'de var): {missing_in_old}")
            for col in missing_in_old:
                print(f"    - {col} ({new_s[t][col]})")
        if missing_in_new:
            print(f"  NEW eksik (OLD'de var): {missing_in_new}")
