"""Batch config'te seçilebilir makine durdurma grupları doğrulaması.

Senaryolar:
  A) get_config/create_config stop_group_ids round-trip: [1] / None / [].
  B) Config stop=[1] ile batch: grup1 kapısı açık → DO=1; grup2 kapısı
     açık → DO=0 (seçilmemiş); tekil kapı DO'su seçimden bağımsız 1.
  C) Eski tip config (stop=None) → tüm gruplar aktif.
  D) stop=[] (hiçbiri seçilmemiş) → hiçbir grup tetiklemez, tekil çalışır.

Komut: python _verify_stop_groups.py
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
    print("Secilebilir makine durdurma gruplari dogrulamasi")
    print("=" * 60)

    db_path = tempfile.mktemp(suffix='.db')
    from core.database import Database
    from core.auth import AuthManager
    from core.audit import AuditManager
    from core.batch_manager import BatchManager
    from core.weidmuller_bridge import WeidmullerBridge

    db = Database(db_path)
    auth = AuthManager(db)
    assert auth.login('admin', 'Admin123!')
    audit = AuditManager(db, auth)
    bm = BatchManager(db, auth, audit)
    bridge = WeidmullerBridge(db, auth, audit, bm)

    # Gruplar: 1=(5,6), 2=(8,) — Faz-10b: durdurma üyeliği stop_group_id
    conn = db.connect()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute("INSERT INTO oraps_door_groups (id, name, created_at) VALUES (1, 'STOP-A', ?)", (now,))
    cur.execute("INSERT INTO oraps_door_groups (id, name, created_at) VALUES (2, 'STOP-B', ?)", (now,))
    cur.execute("UPDATE oraps_door_labels SET stop_group_id=1 WHERE door_index IN (5, 6)")
    cur.execute("UPDATE oraps_door_labels SET stop_group_id=2 WHERE door_index=8")
    conn.commit()
    db.close()

    wm = bridge.wm
    do_pts = wm.list_points(module_id=1, point_type='DO')
    by_ch = {p['channel']: p for p in do_pts}
    wm.set_link(by_ch[5]['id'], 'door_group', 1, 'machine_stop')
    wm.set_link(by_ch[6]['id'], 'door_group', 2, 'machine_stop')
    wm.set_link(by_ch[7]['id'], 'door', 9, 'machine_stop')

    # Bridge hedef listesi (config dialog kaynağı)
    _doors, gset = bridge.get_machine_stop_targets()
    assert gset == {1, 2} and _doors == {9}, f"hedefler: {_doors}, {gset}"
    print(f"\nget_machine_stop_targets: doors={_doors} groups={gset} OK")

    fw = FakeWorker()
    bridge.workers[1] = fw

    # ── A) Round-trip ──
    print("\n[A] stop_group_ids round-trip")
    cfg_sel = bm.create_config('SEL-1', '', {'1': 'locked'}, stop_group_ids=[1])
    cfg_old = bm.create_config('ESKI', '', {'1': 'locked'})                 # None
    cfg_none = bm.create_config('HICBIRI', '', {'1': 'locked'}, stop_group_ids=[])
    assert bm.get_config(cfg_sel)['stop_group_ids'] == [1]
    assert bm.get_config(cfg_old)['stop_group_ids'] is None
    assert bm.get_config(cfg_none)['stop_group_ids'] == []
    print("    [1] / None / [] dogru saklandi OK")

    # ── B) stop=[1]: grup1 tetikler, grup2 tetiklemez, tekil bağımsız ──
    print("\n[B] stop=[1] gating")
    bm.start_batch('B-SEL', cfg_sel)
    ab = bm.get_active_batch()
    assert ab['stop_group_ids'] == [1], f"aktif batch stop listesi: {ab.get('stop_group_ids')}"
    bridge._door_di_state[5] = 1   # grup1 kapısı açık
    bridge._door_di_state[8] = 1   # grup2 kapısı açık
    bridge._door_di_state[9] = 1   # tekil bağlı kapı açık
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 1, "secili grup1 DO=1 olmali"
    assert fw.last_for(6) == 0, "secilmemis grup2 DO=0 kalmali"
    assert fw.last_for(7) == 1, "tekil kapi DO'su secimden bagimsiz 1"
    print(f"    DO5={fw.last_for(5)} DO6={fw.last_for(6)} DO7={fw.last_for(7)} (1/0/1) OK")
    bm.finish_batch()
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 0 and fw.last_for(7) == 0
    print("    finish -> hepsi 0 OK")

    # ── C) Eski config (None) → hepsi aktif ──
    print("\n[C] stop=None -> tum gruplar aktif")
    bm.start_batch('B-ESKI', cfg_old)
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 1 and fw.last_for(6) == 1 and fw.last_for(7) == 1
    print(f"    DO5={fw.last_for(5)} DO6={fw.last_for(6)} DO7={fw.last_for(7)} (1/1/1) OK")
    bm.finish_batch()
    bridge._update_machine_stop_dos()

    # ── D) stop=[] → hiçbir grup tetiklemez, tekil çalışır ──
    print("\n[D] stop=[] -> gruplar pasif, tekil aktif")
    bm.start_batch('B-BOS', cfg_none)
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 0 and fw.last_for(6) == 0, "gruplar tetiklememeli"
    assert fw.last_for(7) == 1, "tekil kapi DO'su calismali"
    print(f"    DO5={fw.last_for(5)} DO6={fw.last_for(6)} DO7={fw.last_for(7)} (0/0/1) OK")
    bm.finish_batch()

    db.close()
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("\nTUM SENARYOLAR GECTI")


if __name__ == '__main__':
    main()
