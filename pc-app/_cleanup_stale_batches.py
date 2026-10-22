"""Birikmiş eski ACTIVE GLT batch'lerini kapat (tek seferlik temizlik).

Kullanıcı onayı: 2026-08-01. Test kayıtları/PDF'lere dokunulmaz; yalnızca
status='COMPLETED' + end_time yazılır, audit'e temizlik kaydı düşülür.

Komut: python _cleanup_stale_batches.py
"""
import sqlite3
from datetime import datetime

DB = 'database/glove_test.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT id, batch_name FROM test_batches WHERE status='ACTIVE' ORDER BY id")
rows = [dict(r) for r in cur.fetchall()]
print(f"Kapatilacak ACTIVE batch sayisi: {len(rows)}")

now = datetime.now().isoformat()
ids = [r['id'] for r in rows]
if ids:
    ph = ','.join('?' * len(ids))
    cur.execute(
        f"UPDATE test_batches SET status='COMPLETED', end_time=? "
        f"WHERE id IN ({ph})", [now] + ids)
    # Audit kaydı (tek satır, toplu temizlik)
    names = ', '.join(f"#{r['id']} '{r['batch_name']}'" for r in rows)
    cur.execute(
        "INSERT INTO audit_trail (timestamp, user_id, username, action_type, "
        "table_name, description, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now, 1, 'admin', 'BATCH_CLEANUP', 'test_batches',
         f"[BAKIM] Birikmiş {len(ids)} eski ACTIVE batch toplu kapatıldı "
         f"(kullanıcı onayı): {names}", 'GLT'),
    )
    conn.commit()
    print(f"KAPATILDI: {len(ids)} batch")

cur.execute("SELECT COUNT(*) FROM test_batches WHERE status='ACTIVE'")
print(f"Kalan ACTIVE: {cur.fetchone()[0]}")
conn.close()
