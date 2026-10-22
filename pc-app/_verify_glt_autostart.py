"""ORABS start → GLT batch oto-başlatma + finish veri akışı doğrulaması.

Senaryolar:
  A) Konfigde RFID'li portlar seçili → ORABS start GLT batch'i otomatik
     başlatır (aynı ad, linked=1, doğru port listesi, PENDING).
  B) Kullanıcı GLT batch'i ÖNCE elle başlatmış → ORABS start yenisini
     AÇMAZ, mevcanı bağlar.
  C) Konfigde port yok → GLT batch açılmaz, BATCH_GLT_SKIPPED audit düşer.
  D) get_batch_details(id) portları döndürür (finish akışının veri kaynağı).

Komut: python _verify_glt_autostart.py
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def main():
    print("=" * 60)
    print("ORABS start -> GLT oto-baslatma dogrulamasi")
    print("=" * 60)

    db_path = tempfile.mktemp(suffix='.db')
    from core.database import Database
    from core.auth import AuthManager
    from core.audit import AuditManager
    from core.batch_manager import BatchManager

    db = Database(db_path)
    auth = AuthManager(db)
    assert auth.login('admin', 'Admin123!')
    audit = AuditManager(db, auth)
    bm = BatchManager(db, auth, audit)

    # GLT portları + ORABS port etiketlerine RFID eşle
    conn = db.connect()
    cur = conn.cursor()
    for i, (name, tag) in enumerate(
            [('P1', 'AA11'), ('P2', 'BB22'), ('P3', 'CC33')], start=1):
        cur.execute(
            "INSERT INTO glove_ports (name, x_pos, y_pos, rfid_tag) "
            "VALUES (?, ?, ?, ?)", (name, i, i, tag))
        cur.execute(
            "UPDATE oraps_port_labels SET rfid_tag=?, label=? "
            "WHERE port_index=?", (tag.lower(), f'Port {i}', i))  # case farkı bilerek
    conn.commit()
    db.close()

    # ── A) Portlu konfig → GLT oto-başlar ──
    print("\n[A] Portlu konfig ile ORABS start")
    cfg_id = bm.create_config('CFG-A', '', {'1': 'locked'}, port_indices=[1, 2, 3])
    bm.start_batch('ORABS-OTO', cfg_id)

    glt = db.find_active_linked_glt_batch(1)
    assert glt, "GLT batch otomatik baslamadi!"
    assert glt['batch_name'] == 'ORABS-OTO', f"ad farkli: {glt['batch_name']}"
    det = db.get_batch_details(glt['id'])
    assert det and len(det['ports']) == 3, f"port sayisi: {det and len(det['ports'])}"
    assert all(p['status'] == 'PENDING' for p in det['ports'])
    tags = sorted((p['rfid_tag'] or '').upper() for p in det['ports'])
    assert tags == ['AA11', 'BB22', 'CC33'], f"tags: {tags}"
    print(f"    GLT '{det['batch_name']}' #{det['id']} 3 port PENDING OK (case-insensitive RFID)")
    rows = audit.get_audit_trail({'action_type': 'BATCH_GLT_STARTED'}) or []
    assert rows, "BATCH_GLT_STARTED audit yok"
    print("    audit BATCH_GLT_STARTED OK")

    bm.finish_batch()
    db.complete_batch(glt['id'])

    # ── B) Elle başlatılmış GLT varsa yenisi açılmaz ──
    print("\n[B] Elle baslatilmis GLT varken ORABS start")
    manual_id = db.create_batch('MANUEL-GLT', 1)  # standalone
    bm.start_batch('ORABS-B', cfg_id)
    linked = db.find_active_linked_glt_batch(1)
    assert linked and linked['id'] == manual_id, "mevcut GLT baglanmaliydi"
    conn = db.connect(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM test_batches WHERE status='ACTIVE'")
    n_active = cur.fetchone()[0]
    db.close()
    assert n_active == 1, f"duplike GLT acildi! aktif={n_active}"
    print(f"    mevcut GLT #{manual_id} baglandi, duplike yok OK")
    bm.finish_batch()
    db.complete_batch(manual_id)

    # ── C) Portsuz konfig → GLT açılmaz + SKIPPED audit ──
    print("\n[C] Portsuz konfig ile ORABS start")
    cfg_np = bm.create_config('CFG-C', '', {'1': 'open'}, port_indices=[])
    bm.start_batch('ORABS-PORTSUZ', cfg_np)
    assert db.find_active_linked_glt_batch(1) is None, "GLT acilmamaliydi"
    rows = audit.get_audit_trail({'action_type': 'BATCH_GLT_SKIPPED'}) or []
    assert rows, "BATCH_GLT_SKIPPED audit yok"
    print("    GLT acilmadi + BATCH_GLT_SKIPPED audit OK")
    bm.finish_batch()

    # ── D) get_batch_details COMPLETED batch için de çalışır ──
    print("\n[D] get_batch_details (finish akisi veri kaynagi)")
    det2 = db.get_batch_details(manual_id)
    assert det2 is not None and det2['status'] == 'COMPLETED'
    assert 'ports' in det2
    print(f"    COMPLETED batch #{manual_id} detay+port listesi geldi OK")

    db.close()
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("\nTUM SENARYOLAR GECTI")


if __name__ == '__main__':
    main()
