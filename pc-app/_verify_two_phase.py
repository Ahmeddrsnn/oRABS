"""İki aşamalı batch (GLT → ORABS) + makine durdurma katmanları doğrulaması.

Senaryolar:
  A) wait_glt_pass=1 config → batch phase='glt' başlar; kilit DO'ları AÇIK
     yazılır (config 'locked' dese bile); machine_stop DO'ları hepsi 1.
  B) advance_to_orabs_phase → phase='orabs'; kilitler uygulanır (locked→0);
     machine_stop normal mantık (kapı kapalı → 0, kapı açık → 1).
  C) wait_glt_pass=0 config → doğrudan phase='orabs' (legacy davranış).
  D) oraps_machine_stop_idle=1 → batch yokken machine_stop hepsi 1;
     =0 → 0.
  E) advance guard'ları: batch yokken / zaten orabs iken hata.

Komut: python _verify_two_phase.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class FakeWorker:
    def __init__(self):
        self.calls = []

    def write_do(self, channel, value):
        self.calls.append((int(channel), int(value)))

    def last_for(self, channel):
        vals = [v for c, v in self.calls if c == int(channel)]
        return vals[-1] if vals else None


def main():
    print("=" * 60)
    print("Iki asamali batch dogrulamasi")
    print("=" * 60)

    db_path = tempfile.mktemp(suffix='.db')
    from core.database import Database
    from core.auth import AuthManager
    from core.audit import AuditManager
    from core.batch_manager import BatchManager, BatchInProgress
    from core.weidmuller_bridge import WeidmullerBridge

    db = Database(db_path)
    auth = AuthManager(db)
    assert auth.login('admin', 'Admin123!')
    audit = AuditManager(db, auth)
    bm = BatchManager(db, auth, audit)
    bridge = WeidmullerBridge(db, auth, audit, bm)

    # Durdurma grubu 1 = kapı 5 (stop_group_id) — kilit için kapı 5 group'suz
    conn = db.connect()
    cur = conn.cursor()
    cur.execute("INSERT INTO oraps_door_groups (id, name, created_at) VALUES (1, 'MS', ?)",
                (datetime.now().isoformat(),))
    cur.execute("UPDATE oraps_door_labels SET stop_group_id=1 WHERE door_index=5")
    conn.commit()
    db.close()

    wm = bridge.wm
    do_pts = {p['channel']: p for p in wm.list_points(module_id=1, point_type='DO')}
    wm.set_link(do_pts[0]['id'], 'door', 5, '')                    # kilit DO
    wm.set_link(do_pts[5]['id'], 'door_group', 1, 'machine_stop')  # durdurma DO

    fw = FakeWorker()
    bridge.workers[1] = fw

    # ── A) İki aşamalı başlangıç ──
    print("\n[A] wait_glt_pass=1 -> GLT asamasi")
    cfg2 = bm.create_config('IKI-ASAMA', '', {'5': 'locked'},
                            stop_group_ids=[1], wait_glt_pass=1)
    assert bm.get_config(cfg2)['wait_glt_pass'] == 1, "config round-trip"
    bm.start_batch('B-2FAZ', cfg2)
    ab = bm.get_active_batch()
    assert ab['phase'] == 'glt', f"phase: {ab['phase']}"
    print(f"    phase='glt' OK (wait_glt_pass={ab['wait_glt_pass']})")
    bridge.on_batch_changed()
    # Kilit DO: GLT aşamasında AÇIK (1) yazılmalı — config 'locked' olsa bile.
    assert fw.last_for(0) == 1, f"GLT fazinda kilit ACIK olmali: {fw.calls}"
    # machine_stop: kapı kapalı olsa bile 1 (aşama kilidi).
    assert fw.last_for(5) == 1, "GLT fazinda machine_stop=1 olmali"
    print(f"    kilit DO0={fw.last_for(0)} (acik), machine_stop DO5={fw.last_for(5)} OK")

    # ── B) ORABS'a geçiş ──
    print("\n[B] advance_to_orabs_phase")
    bm.advance_to_orabs_phase()
    ab = bm.get_active_batch()
    assert ab['phase'] == 'orabs'
    bridge.on_batch_changed()
    assert fw.last_for(0) == 0, "ORABS fazinda locked kapi DO=0 (kilitli)"
    assert fw.last_for(5) == 0, "kapi kapali -> machine_stop=0"
    bridge._door_di_state[5] = 1   # kapı açıldı
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 1, "kapi acik -> machine_stop=1"
    print(f"    kilit DO0={fw.last_for(0)}, machine_stop kapi acikken=1 OK")
    rows = audit.get_audit_trail({'action_type': 'BATCH_PHASE_ORABS'}) or []
    assert rows, "BATCH_PHASE_ORABS audit yok"
    print("    audit BATCH_PHASE_ORABS OK")
    # Zaten orabs → tekrar advance hata
    try:
        bm.advance_to_orabs_phase()
        assert False, "ikinci advance hata vermeliydi"
    except BatchInProgress:
        print("    zaten ORABS -> BatchInProgress OK")
    bm.finish_batch()
    bridge._door_di_state[5] = 0
    bridge.on_batch_changed()

    # ── C) Tek aşamalı (legacy) ──
    print("\n[C] wait_glt_pass=0 -> dogrudan ORABS")
    cfg1 = bm.create_config('TEK-ASAMA', '', {'5': 'locked'})
    bm.start_batch('B-1FAZ', cfg1)
    ab = bm.get_active_batch()
    assert ab['phase'] == 'orabs', f"phase: {ab['phase']}"
    bridge.on_batch_changed()
    assert fw.last_for(0) == 0, "dogrudan kilitlenmeli"
    print(f"    phase='orabs', kilit DO0={fw.last_for(0)} OK")
    bm.finish_batch()
    bridge.on_batch_changed()

    # ── D) idle durdurma ayarı ──
    print("\n[D] oraps_machine_stop_idle")
    assert fw.last_for(5) == 0, "ayar kapali + batch yok -> 0"
    db.set_setting('oraps_machine_stop_idle', '1')
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 1, "ayar acik + batch yok -> 1"
    db.set_setting('oraps_machine_stop_idle', '0')
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 0, "ayar kapatilinca -> 0"
    print("    batch disi kilit: ayar 1->DO=1, 0->DO=0 OK")

    # ── E) advance guard: batch yok ──
    print("\n[E] advance guard")
    try:
        bm.advance_to_orabs_phase()
        assert False, "batch yokken advance hata vermeliydi"
    except BatchInProgress:
        print("    batch yok -> BatchInProgress OK")

    db.close()
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("\nTUM SENARYOLAR GECTI")


if __name__ == '__main__':
    main()
