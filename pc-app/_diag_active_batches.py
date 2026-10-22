"""GLT batch bitmeme teşhisi: ACTIVE test_batches satırlarını listele."""
import sqlite3, sys

DB = sys.argv[1] if len(sys.argv) > 1 else 'database/glove_test.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print('=== ACTIVE test_batches ===')
cur.execute("SELECT id, batch_name, status, start_time, end_time, linked_oraps_batch_id "
            "FROM test_batches WHERE status='ACTIVE' ORDER BY id")
rows = [dict(r) for r in cur.fetchall()]
for r in rows:
    print(r)
print(f'TOPLAM ACTIVE: {len(rows)}')

print('\n=== Son 10 batch (her durum) ===')
cur.execute("SELECT id, batch_name, status, start_time, end_time, linked_oraps_batch_id "
            "FROM test_batches ORDER BY id DESC LIMIT 10")
for r in cur.fetchall():
    print(dict(r))

print('\n=== ORABS active_batch ===')
cur.execute("SELECT * FROM active_batch WHERE id=1")
row = cur.fetchone()
print(dict(row) if row else None)
conn.close()
