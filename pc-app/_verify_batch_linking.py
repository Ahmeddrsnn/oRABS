"""ORABS↔GLT batch bağlama doğrulaması (iki yön) + rapor dialog syntax.

Komut: python _verify_batch_linking.py
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
    print("ORABS<->GLT batch baglama dogrulamasi")
    print("=" * 60)

    db_path = tempfile.mktemp(suffix='.db')
    from core.database import Database
    from core.auth import AuthManager
    from core.audit import AuditManager
    from core.batch_manager import BatchManager

    db = Database(db_path)
    auth = AuthManager(db)
    assert auth.login('admin', 'Admin123!'), "admin login"
    audit = AuditManager(db, auth)
    bm = BatchManager(db, auth, audit)

    cfgs = bm.list_configs()
    assert cfgs, "seed konfig yok"
    cfg_id = cfgs[0]['id']

    # ── Senaryo A: ORABS batch çalışırken GLT batch başlat → bağlanır ──
    print("\n[A] ORABS calisirken GLT batch -> otomatik bagli")
    bm.start_batch('ORABS-A', cfg_id)
    assert db.is_oraps_batch_active() is True, "is_oraps_batch_active True olmali"
    linked_flag = 1 if db.is_oraps_batch_active() else None   # batch_panel mantığı
    glt_a = db.create_batch('GLT-A', 1, linked_oraps_batch_id=linked_flag)
    assert glt_a, "GLT batch olusturulamadi"
    found = db.find_active_linked_glt_batch(1)
    assert found and found['id'] == glt_a, f"bagli GLT bulunamadi: {found}"
    print(f"    create_batch(linked=1) -> find_active_linked_glt_batch id={found['id']} OK")

    # Temizle: her ikisini bitir
    bm.finish_batch()
    db.complete_batch(glt_a)
    assert db.find_active_linked_glt_batch(1) is None
    assert db.is_oraps_batch_active() is False, "finished -> False olmali"
    print("    finish sonrasi bagli aktif GLT yok OK")

    # ── Senaryo B: Önce standalone GLT, sonra ORABS start → bağlanır ──
    print("\n[B] Standalone GLT aktifken ORABS start -> otomatik bagla")
    glt_b = db.create_batch('GLT-B', 1)   # linked=None (standalone)
    assert db.find_active_linked_glt_batch(1) is None, "henuz bagli olmamali"
    bm.start_batch('ORABS-B', cfg_id)
    found_b = db.find_active_linked_glt_batch(1)
    assert found_b and found_b['id'] == glt_b, f"ORABS start baglamadi: {found_b}"
    print(f"    start_batch() aktif GLT'yi bagladi id={found_b['id']} OK")

    # Audit'te BATCH_GLT_LINKED düştü mü?
    rows = audit.get_audit_trail({'action_type': 'BATCH_GLT_LINKED'}) or []
    assert rows, "BATCH_GLT_LINKED audit kaydi yok"
    print(f"    audit BATCH_GLT_LINKED OK ({rows[0].get('description')})")

    # ── Senaryo C: tamamlanmış GLT batch'e dokunulmaz ──
    print("\n[C] COMPLETED GLT batch'e dokunulmaz")
    bm.finish_batch()
    db.complete_batch(glt_b)
    glt_c = db.create_batch('GLT-C', 1)
    db.complete_batch(glt_c)             # hemen bitir (COMPLETED, unlinked)
    bm.start_batch('ORABS-C', cfg_id)
    conn = db.connect()
    cur = conn.cursor()
    cur.execute('SELECT linked_oraps_batch_id FROM test_batches WHERE id=?', (glt_c,))
    val = cur.fetchone()[0]
    db.close()
    assert val is None, f"COMPLETED batch baglanmamali (val={val})"
    print("    COMPLETED batch linked=NULL kaldi OK")
    bm.finish_batch()

    # ── Rapor dialogu: syntax/import kontrolü (Qt instance gerektirmez) ──
    print("\n[D] reports_browser_dialog import")
    import gui.reports_browser_dialog as rbd
    assert hasattr(rbd.ReportsBrowserDialog, '_on_refresh')
    assert hasattr(rbd.ReportsBrowserDialog, '_on_to_changed_by_user')
    print("    import + yeni metodlar OK")

    db.close()
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("\nTUM SENARYOLAR GECTI")


if __name__ == '__main__':
    main()
