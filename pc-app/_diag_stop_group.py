"""Teşhis: durdurma grubu ataması zinciri + idle ayarı DO davranışı."""
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

    def last_for(self, ch):
        vals = [v for c, v in self.calls if c == int(ch)]
        return vals[-1] if vals else None


def main():
    from core.database import Database
    from core.auth import AuthManager
    from core.audit import AuditManager
    from core.batch_manager import BatchManager
    from core.weidmuller_bridge import WeidmullerBridge

    db_path = tempfile.mktemp(suffix='.db')
    db = Database(db_path)
    auth = AuthManager(db)
    auth.login('admin', 'Admin123!')
    audit = AuditManager(db, auth)
    bm = BatchManager(db, auth, audit)
    bridge = WeidmullerBridge(db, auth, audit, bm)
    fw = FakeWorker()
    bridge.workers[1] = fw

    print("[1] Grup olustur + KAPI DUZENLE yolu ile stop_group_id ata")
    gid = bm.create_door_group('Makine Durdurma')
    # _DoorEditDialog kaydi update_door_label ile yapiyor (ayni cagri):
    bm.update_door_label(5, label='Kapak5', group_id=None,
                         show_label=1, stop_group_id=gid)
    rows = {r['door_index']: r for r in bm.get_door_labels()}
    print(f"    kapi5 stop_group_id = {rows[5].get('stop_group_id')} (beklenen {gid})")

    print("[2] bridge uye listesi")
    print(f"    _get_stop_group_members({gid}) = {bridge._get_stop_group_members(gid)}")

    print("[3] machine_stop DO bagla + batch running iken kapi ac/kapa")
    do_pts = {p['channel']: p for p in bridge.wm.list_points(module_id=1, point_type='DO')}
    bridge.wm.set_link(do_pts[5]['id'], 'door_group', gid, 'machine_stop')
    cfg = bm.create_config('C', '', {'5': 'open'})
    bm.start_batch('B', cfg)
    bridge._door_di_state[5] = 1
    bridge._update_machine_stop_dos()
    print(f"    kapi acik -> DO5 = {fw.last_for(5)} (beklenen 1)")
    bridge._door_di_state[5] = 0
    bridge._update_machine_stop_dos()
    print(f"    kapi kapali -> DO5 = {fw.last_for(5)} (beklenen 0)")
    bm.finish_batch()

    print("[4] idle ayari ac/kapa")
    db.set_setting('oraps_machine_stop_idle', '1')
    bridge._update_machine_stop_dos()
    print(f"    ayar=1, batch yok -> DO5 = {fw.last_for(5)} (beklenen 1)")
    db.set_setting('oraps_machine_stop_idle', '0')
    bridge._update_machine_stop_dos()
    print(f"    ayar=0 -> DO5 = {fw.last_for(5)} (beklenen 0)")

    print("[5] batch config stop bolumu uye sayisi (panel mantigi)")
    _d, gset = bridge.get_machine_stop_targets()
    labels = bm.get_door_labels()
    members = {}
    for row in labels:
        g = row.get('stop_group_id')
        if g is not None:
            members.setdefault(int(g), []).append(int(row['door_index']))
    for g in gset:
        print(f"    grup {g}: {len(members.get(g, []))} kapi -> {members.get(g, [])}")

    db.close()
    os.remove(db_path)


if __name__ == '__main__':
    main()
