"""machine_stop rolü doğrulaması — kapı açılınca makine durdurma rölesi.

Senaryolar:
  A) Batch YOKKEN kapı açık → DO=0 (tetiklenmez).
  B) Batch running + grup kapısı (5) açık → grup DO=1, tekil DO(kapı 7)=0.
  C) Grubun diğer kapısı (6) da açık, 5 kapandı → DO=1 kalır; ikisi de
     kapanınca DO=0 + MACHINE_STOP_CLEARED audit.
  D) Tekil bağlı kapı 7 açılınca kendi DO'su 1.
  E) Batch finish → kapı açık olsa da tüm machine_stop DO=0.
  F) Kilit yazma mantığı machine_stop DO'larını KULLANMAZ.

Komut: python _verify_machine_stop.py
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
    """write_do çağrılarını toplayan sahte worker (Modbus yok)."""
    def __init__(self):
        self.calls = []

    def write_do(self, channel, value):
        self.calls.append((int(channel), int(value)))

    def last_for(self, channel):
        vals = [v for c, v in self.calls if c == int(channel)]
        return vals[-1] if vals else None


def main():
    print("=" * 60)
    print("machine_stop rolu dogrulamasi")
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

    # Kapı grubu: STOP-G1 = kapılar 5,6 (Faz-10b: stop_group_id üzerinden)
    conn = db.connect()
    cur = conn.cursor()
    cur.execute("INSERT INTO oraps_door_groups (id, name, created_at) VALUES (1, 'STOP-G1', ?)",
                (datetime.now().isoformat(),))
    cur.execute("UPDATE oraps_door_labels SET stop_group_id=1 WHERE door_index IN (5, 6)")
    conn.commit()
    db.close()

    # DO noktaları: modül 1 kanal 5 → grup 1 (machine_stop);
    #               modül 1 kanal 6 → kapı 7 (machine_stop)
    wm = bridge.wm
    do_pts = wm.list_points(module_id=1, point_type='DO')
    grp_pt = next(p for p in do_pts if p['channel'] == 5)
    door_pt = next(p for p in do_pts if p['channel'] == 6)
    wm.set_link(grp_pt['id'], 'door_group', 1, 'machine_stop')
    wm.set_link(door_pt['id'], 'door', 7, 'machine_stop')
    # Ayrıca bir kilit DO'su (rolsüz) — F senaryosu için: kanal 0 → kapı 5
    lock_pt = next(p for p in do_pts if p['channel'] == 0)
    wm.set_link(lock_pt['id'], 'door', 5, '')

    fw = FakeWorker()
    bridge.workers[1] = fw   # gerçek thread yok

    # ── A) Batch yokken kapı 5 açık → DO=0 ──
    print("\n[A] Batch yokken kapi acik")
    bridge._door_di_state[5] = 1
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 0, f"batch yokken DO 0 olmali: {fw.calls}"
    assert fw.last_for(6) == 0
    print(f"    DO5={fw.last_for(5)}, DO6={fw.last_for(6)} (0/0) OK")

    # ── B) Batch running + kapı 5 açık → grup DO=1 ──
    print("\n[B] Batch running + grup kapisi acik")
    cfg_id = bm.create_config('MS-CFG', '', {'1': 'locked'})
    bm.start_batch('MS-BATCH', cfg_id)
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 1, f"grup DO=1 olmali: {fw.calls}"
    assert fw.last_for(6) == 0, "kapi 7 kapali -> tekil DO=0 kalmali"
    print(f"    DO5={fw.last_for(5)}, DO6={fw.last_for(6)} (1/0) OK")
    rows = audit.get_audit_trail({'action_type': 'MACHINE_STOP_TRIGGERED'}) or []
    assert rows, "MACHINE_STOP_TRIGGERED audit yok"
    print(f"    audit: {rows[0].get('description')}")

    # ── C) 6 açıldı, 5 kapandı → 1 kalır; ikisi de kapandı → 0 ──
    print("\n[C] Grup: herhangi biri acik -> 1, hepsi kapali -> 0")
    bridge._door_di_state[6] = 1
    bridge._door_di_state[5] = 0
    n_calls = len(fw.calls)
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 1 and len(fw.calls) == n_calls, \
        "deger degismedi -> tekrar yazilMAmali"
    print("    kapi 6 acikken DO=1 sabit (gereksiz yazma yok) OK")
    bridge._door_di_state[6] = 0
    bridge._update_machine_stop_dos()
    assert fw.last_for(5) == 0, "hepsi kapali -> DO=0"
    rows = audit.get_audit_trail({'action_type': 'MACHINE_STOP_CLEARED'}) or []
    assert rows, "MACHINE_STOP_CLEARED audit yok"
    print(f"    hepsi kapali DO5=0 + CLEARED audit OK")

    # ── D) Tekil bağlı kapı 7 ──
    print("\n[D] Tekil kapi bagli DO")
    bridge._door_di_state[7] = 1
    bridge._update_machine_stop_dos()
    assert fw.last_for(6) == 1, "kapi 7 acik -> DO6=1"
    print(f"    DO6={fw.last_for(6)} OK")

    # ── E) Batch finish → hepsi 0 ──
    print("\n[E] Batch finish -> tum machine_stop DO=0")
    bm.finish_batch()
    bridge._update_machine_stop_dos()   # on_batch_changed normalde çağırır
    assert fw.last_for(5) == 0 and fw.last_for(6) == 0
    print(f"    DO5={fw.last_for(5)}, DO6={fw.last_for(6)} (0/0) OK")

    # ── F) Kilit mantığı machine_stop DO'larına dokunmaz ──
    print("\n[F] Kilit yazmalari machine_stop DO'larini atlar")
    writes = bridge.compute_door_lock_writes({'5': 'locked', '7': 'locked'})
    chans = {ch for _mid, ch, _v in writes}
    assert 5 not in chans and 6 not in chans, f"machine_stop DO kilit yazdi: {writes}"
    assert 0 in chans, "gercek kilit DO'su (kanal 0) yazilmali"
    print(f"    kilit yazmalari: {writes} (yalniz kanal 0) OK")

    db.close()
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("\nTUM SENARYOLAR GECTI")


if __name__ == '__main__':
    main()
